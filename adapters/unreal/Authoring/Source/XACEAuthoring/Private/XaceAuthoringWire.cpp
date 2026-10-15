#include "XaceAuthoring.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonReader.h"
#include "Misc/FileHelper.h"
THIRD_PARTY_INCLUDES_START
#include <openssl/sha.h>
THIRD_PARTY_INCLUDES_END
namespace
{
FString Quote(const FString& Text)
{
    FString Out=TEXT("\"");
    for(TCHAR C:Text)
    {
        switch(C) {
        case '"': Out+=TEXT("\\\"");break; case '\\': Out+=TEXT("\\\\");break;
        case '\b':Out+=TEXT("\\b");break;case '\f':Out+=TEXT("\\f");break;
        case '\n':Out+=TEXT("\\n");break;case '\r':Out+=TEXT("\\r");break;case '\t':Out+=TEXT("\\t");break;
        default:if(C<32 || C>126)Out+=FString::Printf(TEXT("\\u%04x"),uint32(C));else Out.AppendChar(C);
        }
    }
    return Out+TEXT("\"");
}
bool Encode(const TSharedPtr<FJsonValue>& V,FString& Out,int32 Depth,int32& Nodes)
{
    if(!V || Depth>24 || ++Nodes>1000000 || Out.Len()>16777216)return false;
    switch(V->Type) {
    case EJson::Null:Out+=TEXT("null");return true;
    case EJson::Boolean:Out+=V->AsBool()?TEXT("true"):TEXT("false");return true;
    case EJson::String:if(V->AsString().Len()>4096)return false;Out+=Quote(V->AsString());return true;
    case EJson::Array: {
        Out+=TEXT("[");bool First=true;for(const auto& Item:V->AsArray()){if(!First)Out+=TEXT(",");First=false;if(!Encode(Item,Out,Depth+1,Nodes))return false;}Out+=TEXT("]");return true; }
    case EJson::Object: {
        TArray<FString> Keys;V->AsObject()->Values.GetKeys(Keys);Keys.Sort();Out+=TEXT("{");bool First=true;
        for(const FString& Key:Keys){if(Key.Len()>256)return false;for(TCHAR C:Key)if(C>127)return false;if(!First)Out+=TEXT(",");First=false;Out+=Quote(Key)+TEXT(":");if(!Encode(V->AsObject()->Values[Key],Out,Depth+1,Nodes))return false;}Out+=TEXT("}");return true; }
    default:return false;
    }
}
FString Decimal(double V)
{
    if(!FMath::IsFinite(V))return TEXT("invalid");
    if(V==0)return TEXT("0");
    FString S=FString::Printf(TEXT("%.17f"),V);
    while(S.EndsWith(TEXT("0")))S.LeftChopInline(1);
    if(S.EndsWith(TEXT(".")))S.LeftChopInline(1);
    return S;
}
}
namespace XaceAuthoringWire
{
Object New(){return MakeShared<FJsonObject>();}
FString String(const Object& V,const FString& K){FString Out;if(V)V->TryGetStringField(K,Out);return Out;}
Object Child(const Object& V,const FString& K){const Object* Out=nullptr;return V && V->TryGetObjectField(K,Out)?*Out:nullptr;}
FString Json(const Object& V){FString Out;int32 Nodes=0;return V && Encode(MakeShared<FJsonValueObject>(V),Out,0,Nodes) && Out.Len()<=16777216?Out:FString();}
Object Parse(const FString& S){if(S.Len()>16777216)return nullptr;Object O;auto Reader=TJsonReaderFactory<>::Create(S);return FJsonSerializer::Deserialize(Reader,O) && Json(O)==S?O:nullptr;}
FString Hash(const FString& S){FTCHARToUTF8 B(*S);uint8 D[SHA256_DIGEST_LENGTH];SHA256(reinterpret_cast<const uint8*>(B.Get()),B.Length(),D);return BytesToHex(D,SHA256_DIGEST_LENGTH).ToLower();}
FString FileHash(const FString& P){TArray<uint8>B;if(!FFileHelper::LoadFileToArray(B,*P))return TEXT("");uint8 D[SHA256_DIGEST_LENGTH];SHA256(B.GetData(),B.Num(),D);return BytesToHex(D,SHA256_DIGEST_LENGTH).ToLower();}
bool Id(const FString& V){if(V.Len()!=32)return false;for(TCHAR C:V)if(!((C>='0'&&C<='9')||(C>='a'&&C<='f')))return false;return true;}
Object Vector(const FVector& V){auto O=New();O->SetStringField(TEXT("x"),Decimal(V.X));O->SetStringField(TEXT("y"),Decimal(V.Y));O->SetStringField(TEXT("z"),Decimal(V.Z));return O;}
Object Rotation(const FQuat& V){auto O=New();O->SetStringField(TEXT("x"),Decimal(V.X));O->SetStringField(TEXT("y"),Decimal(V.Y));O->SetStringField(TEXT("z"),Decimal(V.Z));O->SetStringField(TEXT("w"),Decimal(V.W));return O;}
}
