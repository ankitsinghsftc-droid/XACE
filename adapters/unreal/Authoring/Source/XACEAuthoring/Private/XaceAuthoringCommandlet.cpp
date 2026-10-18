#include "XaceAuthoringCommandlet.h"
#include "XaceAuthoring.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
using namespace XaceAuthoringWire;
UXaceAuthoringCommandlet::UXaceAuthoringCommandlet(){IsClient=false;IsEditor=true;IsServer=false;LogToConsole=true;}
int32 UXaceAuthoringCommandlet::Main(const FString& Params)
{
    FString Path;if(!FParse::Value(*Params,TEXT("XaceAuthoringCommand="),Path))return 2;
    Path=FPaths::ConvertRelativePathToFull(Path);FPaths::NormalizeFilename(Path);
    FString Root=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()/TEXT(".xace/native-authoring-calls/"));FPaths::NormalizeFilename(Root);
    if(!Path.StartsWith(Root)||Path.Contains(TEXT(".."))||FPaths::GetCleanFilename(Path)!=TEXT("command.json"))return 2;
    FString Output=FPaths::GetPath(Path)/TEXT("result.json");if(FPaths::FileExists(Output))return 2;
    FString Text;FFileHelper::LoadFileToString(Text,*(FPaths::ProjectDir()/TEXT(".xace/native-authoring-host.json")));auto Config=Parse(Text);
    FString ExpectedRoot=FPaths::ConvertRelativePathToFull(String(Config,TEXT("root")));FPaths::NormalizeDirectoryName(ExpectedRoot);FString ProjectRoot=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());FPaths::NormalizeDirectoryName(ProjectRoot);
    const TArray<TSharedPtr<FJsonValue>>* Documents=nullptr;
    if(!Config||String(Config,TEXT("engine"))!=TEXT("unreal")||ExpectedRoot!=ProjectRoot||!Config->TryGetArrayField(TEXT("documents"),Documents)||Documents->Num()!=1)return 2;
    const FString Map=(*Documents)[0]->AsString();FFileHelper::LoadFileToString(Text,*Path);auto Command=Parse(Text);const FString Action=String(Command,TEXT("action"));
    FXaceUnrealAuthoring Service;Service.bTrustedProject=true;Object Result;
    if(Action==TEXT("capture")||Action==TEXT("prepare")){auto World=Service.LoadApprovedMap(Map);if(World)Result=Action==TEXT("capture")?Service.Capture(World,Map):Service.Prepare(World,Map,Json(Child(Command,TEXT("request"))),String(Command,TEXT("transaction_id")));}
    else {auto Prepared=Child(Command,TEXT("prepared"));FString Directory=String(Prepared,TEXT("directory"));if(Action==TEXT("commit"))Result=Service.Commit(Map,Directory,String(Prepared,TEXT("approval_digest")));if(Action==TEXT("recover"))Result=Service.Recover(Map,Directory,FileHash(Directory/TEXT("receipt.json")));}
    auto Report=New();const bool Ok=Result.IsValid()&&Service.Error.IsEmpty();Report->SetBoolField(TEXT("ok"),Ok);Report->SetStringField(TEXT("error"),Service.Error);if(Result)Report->SetObjectField(TEXT("result"),Result);
    return FFileHelper::SaveStringToFile(Json(Report),*Output,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)&&Ok?0:1;
}
