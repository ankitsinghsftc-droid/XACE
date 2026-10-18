#include "XaceNativeSetupCommandlet.h"
#include "XaceAuthoring.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
using namespace XaceAuthoringWire;
UXaceNativeSetupCommandlet::UXaceNativeSetupCommandlet(){IsClient=false;IsEditor=true;IsServer=false;LogToConsole=true;}
int32 UXaceNativeSetupCommandlet::Main(const FString& Params)
{
    FString Text;FFileHelper::LoadFileToString(Text,*(FPaths::ProjectDir()/TEXT(".xace/spec.json")));auto Spec=Parse(Text);
    FXaceUnrealAuthoring Service;Service.bTrustedProject=true;Object Result;
    const bool Reload=FParse::Param(*Params,TEXT("ColdReopen"));
    if(Reload){auto World=Service.LoadApprovedMap(TEXT("/Game/XACEGenerated/World"));auto Inventory=World?Service.Capture(World,TEXT("/Game/XACEGenerated/World")):nullptr;
        Result=New();if(Inventory)Result->SetObjectField(TEXT("inventory"),Inventory);
        FString Filename=Service.MapFilename(TEXT("/Game/XACEGenerated/World"));FString Before=FileHash(Filename);
        Result->SetBoolField(TEXT("existing_refused"),!Service.CreateSetup(Spec,Hash(Text)));Result->SetBoolField(TEXT("unchanged"),Before==FileHash(Filename));
    }else Result=Service.CreateSetup(Spec,Hash(Text));
    auto Report=New();Report->SetStringField(TEXT("error"),Service.Error);if(Result)Report->SetObjectField(TEXT("result"),Result);
    bool Saved=FFileHelper::SaveStringToFile(Json(Report),*(FPaths::ProjectDir()/TEXT(".xace/")+(Reload?TEXT("result-reload.json"):TEXT("result-create.json"))),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    return Saved && Result && Child(Result,TEXT("inventory"))?0:1;
}
