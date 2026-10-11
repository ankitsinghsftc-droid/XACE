#include "XaceNativeContract.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
THIRD_PARTY_INCLUDES_START
#include <openssl/sha.h>
THIRD_PARTY_INCLUDES_END

namespace
{
    TSharedPtr<FJsonObject> Obj(const TSharedPtr<FJsonObject>& O, const FString& K)
    { const TSharedPtr<FJsonObject>* V=nullptr; return O.IsValid() && O->TryGetObjectField(K,V) ? *V : nullptr; }
    FString Str(const TSharedPtr<FJsonObject>& O, const FString& K)
    { FString V; if(O.IsValid())O->TryGetStringField(K,V); return V; }
    const TArray<TSharedPtr<FJsonValue>>* Arr(const TSharedPtr<FJsonObject>& O, const FString& K)
    { const TArray<TSharedPtr<FJsonValue>>* V=nullptr; if(O.IsValid())O->TryGetArrayField(K,V); return V; }
    bool EqualVector(const TSharedPtr<FJsonObject>& A, const TSharedPtr<FJsonObject>& B)
    { FVector X,Y; return XaceCanonical::Vector(A,X,true) && XaceCanonical::Vector(B,Y,true) && X==Y; }
    TArray<FString> Supported() { return {TEXT("session.projection.v1"),TEXT("input.timed.v1"),TEXT("world.aabb.v1"),TEXT("world.semantic_bindings.v3")}; }
}
namespace XaceCanonical
{
    TSharedPtr<FJsonObject> Parse(const FString& Raw)
    { TSharedPtr<FJsonObject> O; auto R=TJsonReaderFactory<>::Create(Raw); return FJsonSerializer::Deserialize(R,O) ? O : nullptr; }
    FString Json(const TSharedPtr<FJsonObject>& O)
    { FString S; if(O.IsValid()){auto W=TJsonWriterFactory<>::Create(&S); FJsonSerializer::Serialize(O.ToSharedRef(),W);}return S; }
    FString Hash(const FString& Raw)
    { FTCHARToUTF8 Bytes(*Raw); uint8 Digest[SHA256_DIGEST_LENGTH]; return SHA256(reinterpret_cast<const uint8*>(Bytes.Get()),Bytes.Length(),Digest) ? BytesToHex(Digest,SHA256_DIGEST_LENGTH).ToLower() : TEXT(""); }
    bool Integer(const TSharedPtr<FJsonObject>& O,const FString& K,int64& Out,int64 Minimum)
    { double V; if(!O.IsValid() || !O->TryGetNumberField(K,V) || !FMath::IsFinite(V) || V<Minimum || V>double(MaxExact) || FMath::TruncToDouble(V)!=V)return false; Out=int64(V);return true; }
    bool Vector(const TSharedPtr<FJsonObject>& O,FVector& Out,bool bScale)
    {
        int64 X,Y,Z; if(!Integer(O,TEXT("x"),X,-MaxExact) || !Integer(O,TEXT("y"),Y,-MaxExact) || !Integer(O,TEXT("z"),Z,-MaxExact))return false;
        // Canonical metres/Y-up/right-handed -> Unreal centimetres/Z-up/left-handed.
        Out=bScale ? FVector(double(Z),double(X),double(Y))/1000000.0 : FVector(-double(Z),double(X),double(Y))/10000.0;return true;
    }
    bool Rotation(const TSharedPtr<FJsonObject>& O,FQuat& Out)
    { int64 X,Y,Z,W; if(!Integer(O,TEXT("x"),X,-MaxExact)||!Integer(O,TEXT("y"),Y,-MaxExact)||!Integer(O,TEXT("z"),Z,-MaxExact)||!Integer(O,TEXT("w"),W,-MaxExact))return false;
      Out=FQuat(double(Z)/1e6,-double(X)/1e6,-double(Y)/1e6,double(W)/1e6);if(Out.SizeSquared()<1e-6)return false;Out.Normalize();return true; }
    bool Entities(const TArray<TSharedPtr<FJsonValue>>& Values)
    {
        TMap<int64,int64> Parents;int64 Last=0;
        for(const auto& Value:Values)
        {
            const auto E=Value->AsObject();int64 Id,Parent;auto C=Obj(E,TEXT("components"));
            if(!Integer(E,TEXT("id"),Id,1)||Id<=Last||!C.IsValid())return false;Last=Id;
            for(const auto& Pair:C->Values){FString Raw;uint64 Type=0;if(Pair.Key.IsEmpty()||!Pair.Key.IsNumeric()||!LexTryParseString(Type,*Pair.Key)||Type==0||Type>MAX_uint32||!Pair.Value->TryGetString(Raw)||!Parse(Raw).IsValid())return false;}
            if(!C->HasField(TEXT("1"))){Parents.Add(Id,0);continue;}
            auto T=Parse(Str(C,TEXT("1")));FVector V,S;FQuat Q;
            if(!Vector(Obj(T,TEXT("position")),V)||!Vector(Obj(T,TEXT("scale")),S,true)||S.X==0||S.Y==0||S.Z==0||!Rotation(Obj(T,TEXT("rotation")),Q)||!Integer(T,TEXT("parent_entity_id"),Parent))return false;
            Parents.Add(Id,Parent);
        }
        for(const auto& Pair:Parents){TSet<int64> Seen;int64 Current=Pair.Key;while(Current!=0){if(Seen.Contains(Current)||!Parents.Contains(Current))return false;Seen.Add(Current);Current=Parents[Current];}}
        return true;
    }
}
bool FXaceNativeSession::Configure(const FString& TicketJson,const FString& WorldJson)
{
    Error=TEXT("Malformed/unsupported native session");
    const auto Ticket=XaceCanonical::Parse(TicketJson);const auto Offer=XaceCanonical::Parse(Str(Ticket,TEXT("offer_json")));
    auto Contract=Obj(Offer,TEXT("contract"));auto Client=Obj(Offer,TEXT("client"));auto Adapter=Obj(Client,TEXT("adapter"));
    auto Gameplay=Obj(Contract,TEXT("gameplay"));auto Artifact=Obj(Obj(Gameplay,TEXT("world")),TEXT("artifact"));
    auto CandidateWorld=XaceCanonical::Parse(WorldJson);auto CandidateEpoch=Obj(Contract,TEXT("epoch"));int64 EpochNumber;
    int64 Peer,Controller;
    if(Str(Ticket,TEXT("schema"))!=TEXT("xace.session_ticket.v1") || Str(Contract,TEXT("schema"))!=TEXT("xace.session_contract.v1") || !Adapter.IsValid() || !XaceCanonical::Integer(Ticket,TEXT("peer_id"),Peer,1) || !XaceCanonical::Integer(Ticket,TEXT("controller_id"),Controller,1) || Str(Ticket,TEXT("credential")).IsEmpty() || !XaceCanonical::Integer(CandidateEpoch,TEXT("ruleset_epoch"),EpochNumber))return false;
    const auto Caps=Arr(Contract,TEXT("required_capabilities"));if(!Caps)return false;
    for(const auto& Cap:*Caps){FString S;if(!Cap->TryGetString(S)||!Supported().Contains(S))return false;}
    int64 WorldVersion;
    if(Str(CandidateWorld,TEXT("schema"))!=TEXT("xace.world_contract.v3") || !XaceCanonical::Integer(CandidateWorld,TEXT("contract_version"),WorldVersion)||WorldVersion!=3||XaceCanonical::Hash(WorldJson)!=Str(Artifact,TEXT("content_hash")))return false;
    const auto Profiles=Arr(CandidateWorld,TEXT("geometry_profiles"));const auto Objects=Arr(CandidateWorld,TEXT("objects"));if(!Profiles||!Objects)return false;
    for(const auto& P:*Profiles){auto O=P->AsObject();bool Required;if(!O.IsValid()||!O->TryGetBoolField(TEXT("required"),Required)||(Required&&Str(O,TEXT("id"))!=TEXT("world.aabb.v1")))return false;}
    TSet<FString> Ids;for(const auto& P:*Objects){auto O=P->AsObject();FString Id=Str(O,TEXT("id"));if(Id.IsEmpty()||Ids.Contains(Id))return false;Ids.Add(Id);auto G=Obj(O,TEXT("geometry"));if(G.IsValid()&&Str(G,TEXT("profile"))!=TEXT("world.aabb.v1"))return false;}
    Adapter->SetStringField(TEXT("engine"),TEXT("unreal"));TArray<TSharedPtr<FJsonValue>> CapValues;for(const auto& C:Supported())CapValues.Add(MakeShared<FJsonValueString>(C));Client->SetArrayField(TEXT("capabilities"),CapValues);
    OfferJson=XaceCanonical::Json(Offer);Credential=Str(Ticket,TEXT("credential"));CgsHash=Str(Obj(Gameplay,TEXT("cgs")),TEXT("cgs_hash"));PeerId=Peer;ControllerId=Controller;World=CandidateWorld;Epoch=CandidateEpoch;Generation=PlayerId=Sequence=0;Bindings.Reset();Fence();Error.Reset();return true;
}
bool FXaceNativeSession::Bind(const TSharedPtr<FJsonObject>& Map,const TArray<TSharedPtr<FJsonValue>>& Entities)
{
    if(!Map.IsValid())return false;TMap<int64,TSharedPtr<FJsonObject>> ById;for(const auto& V:Entities){int64 Id;auto E=V->AsObject();if(!XaceCanonical::Integer(E,TEXT("id"),Id,1))return false;ById.Add(Id,E);}
    TMap<FString,int64> Next;const auto Objects=Arr(World,TEXT("objects"));if(!Objects)return false;
    for(const auto& V:*Objects)
    {
        auto O=V->AsObject();FString Key=Str(O,TEXT("id")),Raw=Str(Map,Key);int64 Id=0;
        if(Raw.IsEmpty() || !Raw.IsNumeric() || !LexTryParseString(Id,*Raw) || Id<=0 || Id>XaceCanonical::MaxExact || !ById.Contains(Id))return false;
        auto Geometry=Obj(O,TEXT("geometry"));
        if(Geometry.IsValid())
        {
            auto Collider=XaceCanonical::Parse(Str(Obj(ById[Id],TEXT("components")),TEXT("4")));bool A,B;int64 LA,LB=1;
            if(Str(Collider,TEXT("shape"))!=TEXT("BOX")||!EqualVector(Obj(Geometry,TEXT("size")),Obj(Collider,TEXT("size")))||!EqualVector(Obj(Geometry,TEXT("offset")),Obj(Collider,TEXT("offset")))||!Geometry->TryGetBoolField(TEXT("is_trigger"),A)||!Collider->TryGetBoolField(TEXT("is_trigger"),B)||A!=B||!XaceCanonical::Integer(Geometry,TEXT("layer_mask"),LA)||(Collider->HasField(TEXT("layer_mask"))&&!XaceCanonical::Integer(Collider,TEXT("layer_mask"),LB))||LA!=LB)return false;
        }
        Next.Add(Key,Id);
    }
    Bindings=MoveTemp(Next);return true;
}
FString FXaceNativeSession::Verify(const TSharedPtr<FJsonObject>& M)
{
    Error=TEXT("Invalid live projection");FString Kind=Str(M,TEXT("msg_type"));bool Initial=Kind==TEXT("handshake_ack"),Baseline=Kind==TEXT("session_baseline");
    const auto Stamp=XaceCanonical::Parse(Str(M,TEXT("sync_json")));int64 Gen=0,Seq=0,Tick=0,EP=0,Expected=0;
    if(!Stamp.IsValid()||Stamp->Values.Num()!=9||Str(Stamp,TEXT("schema"))!=TEXT("xace.session_projection.v1")||Str(Stamp,TEXT("baseline_id")).IsEmpty()||Str(Stamp,TEXT("session_id"))!=Str(Epoch,TEXT("session_id"))||Str(Stamp,TEXT("authority_incarnation"))!=Str(Epoch,TEXT("authority_incarnation"))||!XaceCanonical::Integer(Stamp,TEXT("ruleset_epoch"),EP)||!XaceCanonical::Integer(Epoch,TEXT("ruleset_epoch"),Expected)||EP!=Expected||!XaceCanonical::Integer(Stamp,TEXT("connection_generation"),Gen,1)||!XaceCanonical::Integer(Stamp,TEXT("sequence"),Seq,1)||!XaceCanonical::Integer(Stamp,TEXT("next_tick"),Tick))return TEXT("reject");
    if(Initial ? Gen<=Generation : Gen!=Generation||Seq<=Sequence)return TEXT("drop");
    if(!Initial&&!Baseline&&(bRecovering||Seq!=Sequence+1||Tick!=NextTick+1)){Fence();return TEXT("recover");}
    FString Raw=Str(M,TEXT("projection_json"));auto Wrapper=XaceCanonical::Parse(TEXT("{\"entities\":")+Raw+TEXT("}"));const auto Values=Arr(Wrapper,TEXT("entities"));
    if(!Values||XaceCanonical::Hash(Raw)!=Str(Stamp,TEXT("projection_digest"))){if(Initial)return TEXT("reject");Fence();return TEXT("recover");}
    if(!XaceCanonical::Entities(*Values))return TEXT("reject");if(!Initial&&Tick<NextTick)return TEXT("drop");
    if(Initial)
    {
        int64 HandshakeEpoch=0;
        if(Str(M,TEXT("session_id"))!=Str(Epoch,TEXT("session_id"))||Str(M,TEXT("authority_incarnation"))!=Str(Epoch,TEXT("authority_incarnation"))||!XaceCanonical::Integer(M,TEXT("ruleset_epoch"),HandshakeEpoch)||HandshakeEpoch!=Expected||Str(M,TEXT("cgs_hash"))!=CgsHash)return TEXT("reject");
        int64 Player,Peer;bool Owned=false;
        if(!XaceCanonical::Integer(M,TEXT("assigned_player_id"),Player,1)||!XaceCanonical::Integer(M,TEXT("assigned_peer_id"),Peer,1)||Peer!=PeerId||(PlayerId!=0&&Player!=PlayerId)||Str(M,TEXT("reconnect_credential")).IsEmpty())return TEXT("reject");
        for(const auto& V:*Values){auto E=V->AsObject();int64 Id,Controller;if(!XaceCanonical::Integer(E,TEXT("id"),Id,1)||Id!=Player)continue;auto Input=XaceCanonical::Parse(Str(Obj(E,TEXT("components")),TEXT("6")));Owned=XaceCanonical::Integer(Input,TEXT("controller_id"),Controller,1)&&Controller==ControllerId&&Str(Input,TEXT("control_type"))==TEXT("HUMAN");}
        if(!Owned||!Bind(Obj(M,TEXT("world_bindings")),*Values))return TEXT("reject");PlayerId=Player;Credential=Str(M,TEXT("reconnect_credential"));
    }
    else if(!Baseline){int64 Applied;if(!XaceCanonical::Integer(M,TEXT("tick"),Applied)||Applied!=Tick-1)return TEXT("reject");}
    M->SetArrayField(Initial?TEXT("initial_entities"):TEXT("entities"),*Values);M->SetObjectField(TEXT("sync"),Stamp.ToSharedRef());
    Generation=Gen;Sequence=Seq;NextTick=Tick;bRecovering=false;RequestedTick=-1;bSent=false;Error.Reset();return TEXT("accept");
}
bool FXaceNativeSession::Request(int64 Tick)
{if(bRecovering||Tick!=NextTick||RequestedTick==Tick)return false;RequestedTick=Tick;bSent=false;return true;}
bool FXaceNativeSession::CanSend(int64 Tick,int64 Peer,int64 Player) const
{return !bRecovering&&!bSent&&RequestedTick==Tick&&Tick==NextTick&&Peer==PeerId&&Player==PlayerId;}
