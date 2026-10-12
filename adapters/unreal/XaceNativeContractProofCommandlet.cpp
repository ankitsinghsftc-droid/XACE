#include "XaceNativeContractProofCommandlet.h"
#include "XaceNativeContract.h"
#include "XaceDeltaApplicator.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Components/StaticMeshComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/EngineVersion.h"
#include "XaceInputCollector.h"
#include "HAL/PlatformProcess.h"
#include "XaceMixedSessionProof.h"

namespace
{
int32 LiveProof(const FString& Params)
{
    FString TicketPath,WorldPath,CgsPath,ReportPath,Raw,Ticket,WorldJson;
    int32 Port=0;FParse::Value(*Params,TEXT("XaceTicket="),TicketPath);FParse::Value(*Params,TEXT("XaceWorld="),WorldPath);FParse::Value(*Params,TEXT("XaceCgs="),CgsPath);FParse::Value(*Params,TEXT("XaceReport="),ReportPath);FParse::Value(*Params,TEXT("XacePort="),Port);
    if(!FFileHelper::LoadFileToString(Ticket,*TicketPath)||!FFileHelper::LoadFileToString(WorldJson,*WorldPath)||!FFileHelper::LoadFileToString(Raw,*CgsPath))return 1;
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,TEXT("XaceNativeLiveProofWorld"));
    AActor* Owner=World->SpawnActor<AActor>();auto Transport=NewObject<UXaceTransportComponent>(Owner);Owner->AddInstanceComponent(Transport);Transport->RegisterComponent();Transport->bAutoConnect=false;Transport->bReconnect=true;Transport->InitialReconnectDelaySeconds=0.1f;
    auto Applicator=NewObject<UXaceDeltaApplicatorComponent>(Owner);Owner->AddInstanceComponent(Applicator);Applicator->RegisterComponent();Applicator->BindTransportNow();
    auto Collector=NewObject<UXaceInputCollectorComponent>(Owner);Owner->AddInstanceComponent(Collector);Collector->RegisterComponent();Collector->BindTransportNow();
    if(!Transport->ConfigureLiveSession(Ticket,WorldJson))return 1;
    Transport->ConfigureConnection(TEXT("127.0.0.1"),Port,XaceCanonical::Parse(Raw)->GetObjectField(TEXT("metadata"))->GetStringField(TEXT("cgs_hash")));
    TArray<TSharedPtr<FJsonValue>> Ticks;TSet<int64> Owners;bool Reconnected=false;
    Transport->OnJsonMessage.AddLambda([&](const TSharedPtr<FJsonObject>& Message)
    {
        const FString Kind=Message->GetStringField(TEXT("msg_type"));
        if(Kind==TEXT("handshake_ack"))Owners.Add(Transport->Session.PlayerId);
        if(Kind==TEXT("tick_snapshot"))
        {
            Ticks.Add(MakeShared<FJsonValueNumber>(Message->GetNumberField(TEXT("tick"))));
            if(Ticks.Num()==3&&!Reconnected){Reconnected=true;Transport->DisconnectFromRuntime(TEXT("XP-016 reconnect proof"));}
        }
    });
    Transport->ConnectToRuntime();const double Deadline=FPlatformTime::Seconds()+30;
    while(FPlatformTime::Seconds()<Deadline && (Ticks.Num()<8 || Transport->Session.Generation<2))
    {Transport->PumpOnce(0.01f);FPlatformProcess::Sleep(0.01f);}
    bool Ok=Ticks.Num()>=8&&Owners.Num()==1&&Transport->Session.Generation==2&&Transport->GetStats().ProtocolErrors==0&&Applicator->GetEntityActor(Transport->Session.PlayerId)!=nullptr;
    auto Report=MakeShared<FJsonObject>();Report->SetStringField(TEXT("schema"),TEXT("xace.native_live_proof.v1"));Report->SetStringField(TEXT("engine"),TEXT("unreal"));Report->SetBoolField(TEXT("ok"),Ok);Report->SetArrayField(TEXT("ticks"),Ticks);Report->SetNumberField(TEXT("generation"),Transport->Session.Generation);Report->SetNumberField(TEXT("bound_objects"),Transport->Session.Bindings.Num());Report->SetStringField(TEXT("last_error"),Transport->GetLastError());
    FFileHelper::SaveStringToFile(XaceCanonical::Json(Report),*ReportPath,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);Transport->DisconnectFromRuntime(TEXT("proof completed"));World->DestroyWorld(false);return Ok?0:1;
}
}

UXaceNativeContractProofCommandlet::UXaceNativeContractProofCommandlet()
{IsClient=false;IsServer=false;IsEditor=true;LogToConsole=true;}
int32 UXaceNativeContractProofCommandlet::Main(const FString& Params)
{
    if(Params.Contains(TEXT("XaceMixed=")))return MixedSessionProof(Params);
    if(FParse::Param(*Params,TEXT("XaceLive")))return LiveProof(Params);
    FString FixturePath,ReportPath,Raw;
    FParse::Value(*Params,TEXT("XaceFixture="),FixturePath);FParse::Value(*Params,TEXT("XaceReport="),ReportPath);
    if(!FFileHelper::LoadFileToString(Raw,*FixturePath))return 1;
    auto Fixture=XaceCanonical::Parse(Raw);if(!Fixture.IsValid())return 1;
    FString Ticket=Fixture->GetStringField(TEXT("ticket_json")),WorldJson=Fixture->GetStringField(TEXT("world_json"));
    bool Ok=true;TArray<TSharedPtr<FJsonValue>> Results;
    for(const auto& Value:Fixture->GetArrayField(TEXT("cases")))
    {
        auto Test=Value->AsObject();FXaceNativeSession State;bool Prefix=State.Configure(Ticket,WorldJson);
        for(const auto& Message:Test->GetArrayField(TEXT("messages")))Prefix=State.Verify(XaceCanonical::Parse(XaceCanonical::Json(Message->AsObject())))==TEXT("accept")&&Prefix;
        FString Result=State.Verify(XaceCanonical::Parse(XaceCanonical::Json(Test->GetObjectField(TEXT("message")))));
        bool Pass=Prefix&&Result==Test->GetStringField(TEXT("expected"));Ok=Pass&&Ok;
        auto Record=MakeShared<FJsonObject>();Record->SetStringField(TEXT("name"),Test->GetStringField(TEXT("name")));Record->SetStringField(TEXT("result"),Result);Record->SetBoolField(TEXT("ok"),Pass);Results.Add(MakeShared<FJsonValueObject>(Record));
    }
    const auto Init=UWorld::InitializationValues().AllowAudioPlayback(false).RequiresHitProxies(false).CreatePhysicsScene(false).CreateNavigation(false).CreateAISystem(false).ShouldSimulatePhysics(false);
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,TEXT("XaceNativeContractProofWorld"),nullptr,true,ERHIFeatureLevel::Num,&Init);
    AActor* Owner=World->SpawnActor<AActor>();auto Transport=NewObject<UXaceTransportComponent>(Owner);Owner->AddInstanceComponent(Transport);Transport->RegisterComponent();Transport->bAutoConnect=false;
    auto Applicator=NewObject<UXaceDeltaApplicatorComponent>(Owner);Owner->AddInstanceComponent(Applicator);Applicator->RegisterComponent();Applicator->BindTransportNow();
    if(!Transport->ConfigureLiveSession(Ticket,WorldJson))return 1;
    auto Baseline=XaceCanonical::Parse(XaceCanonical::Json(Fixture->GetObjectField(TEXT("baseline"))));
    if(Transport->Session.Verify(Baseline)!=TEXT("accept"))return 1;
    FXaceHandshakeAck Ack;Ack.bAccepted=true;
    for(const auto& Value:Baseline->GetArrayField(TEXT("initial_entities")))
    {
        auto E=Value->AsObject();FXaceEntityState State;XaceCanonical::Integer(E,TEXT("id"),State.EntityId,1);State.ActorId=E->GetStringField(TEXT("actor_id"));
        for(const auto& Pair:E->GetObjectField(TEXT("components"))->Values)State.Components.Add(FCString::Atoi(*Pair.Key),Pair.Value->AsString());Ack.InitialEntities.Add(State);
    }
    Transport->OnHandshakeAccepted.Broadcast(Ack);
    auto Marker=Applicator->GetEntityActor(42);auto Solid=Applicator->GetEntityActor(77);if(!Marker||!Solid)return 1;
    FVector Position=Marker->GetActorLocation(),Normal=Marker->GetActorQuat().RotateVector(FVector(-1,0,0));
    UStaticMeshComponent* Visual=Solid->FindComponentByClass<UStaticMeshComponent>();
    bool Geometry=Position.Equals(FVector(-300,600,200),0.01)&&Normal.Equals(FVector(0,1,0),0.0001)&&Visual&&Visual->GetRelativeScale3D().Equals(FVector(6,2,4))&&Marker->FindComponentByClass<UXaceEntityMarkerComponent>()->CanonicalObjectId==TEXT("marker");
    for(auto Actor:{Marker,Solid}){TArray<UPrimitiveComponent*> Components;Actor->GetComponents(Components);for(auto C:Components)Geometry=C->GetCollisionEnabled()==ECollisionEnabled::NoCollision&&!C->IsSimulatingPhysics()&&Geometry;}
    Geometry=Geometry&&Marker->FindComponentByClass<UXaceEntityMarkerComponent>()->WorldObjects.Num()==2;
    auto& State=Transport->Session;bool Input=!State.CanSend(7,2,42)&&State.Request(7)&&State.CanSend(7,2,42);State.Sent();Input=Input&&!State.CanSend(7,2,42)&&!State.Request(7);
    Ok=Ok&&Geometry&&Input;auto Report=MakeShared<FJsonObject>();Report->SetStringField(TEXT("schema"),TEXT("xace.native_contract_proof.v1"));Report->SetStringField(TEXT("engine"),TEXT("unreal"));Report->SetStringField(TEXT("version"),FEngineVersion::Current().ToString());Report->SetBoolField(TEXT("ok"),Ok);Report->SetArrayField(TEXT("cases"),Results);Report->SetBoolField(TEXT("geometry"),Geometry);Report->SetBoolField(TEXT("input_fence"),Input);
    FFileHelper::SaveStringToFile(XaceCanonical::Json(Report),*ReportPath,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    World->DestroyWorld(false);return Ok?0:1;
}
