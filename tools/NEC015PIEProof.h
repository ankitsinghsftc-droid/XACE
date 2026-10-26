#pragma once
#if WITH_EDITOR
#include "Editor.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "FileHelpers.h"
#include "PlayInEditorDataTypes.h"
#include "EngineUtils.h"
#include "Components/SceneComponent.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Containers/Ticker.h"
#include "XaceNativeHost.h"
namespace NEC015PIE {
static FString Report,MapHash;static int32 Stage=0,Cycles=0;static double Deadline=0;static uint32 OwnerPid=0,RuntimePid=0;static TArray<TSharedPtr<FJsonValue>> Results;
static bool Gone(uint32 Id){auto P=FPlatformProcess::OpenProcess(Id);bool R=!P.IsValid()||!FPlatformProcess::IsProcRunning(P);if(P.IsValid())FPlatformProcess::CloseProc(P);return R;}
static bool Finish(bool Ok,const FString& Error){auto R=MakeShared<FJsonObject>();R->SetBoolField(TEXT("ok"),Ok);R->SetStringField(TEXT("error"),Error);R->SetBoolField(TEXT("actual_pie"),true);R->SetArrayField(TEXT("cycles"),Results);R->SetStringField(TEXT("map_sha256"),MapHash);R->SetBoolField(TEXT("packaged_build"),false);FString Text;FJsonSerializer::Serialize(R,TJsonWriterFactory<>::Create(&Text));FFileHelper::SaveStringToFile(Text,*Report);if(GEditor&&GEditor->PlayWorld)GEditor->RequestEndPlayMap();FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);return false;}
static void Launch(){FRequestPlaySessionParams Params;Params.bAllowOnlineSubsystem=false;Params.WorldType=EPlaySessionWorldType::PlayInEditor;Params.SessionDestination=EPlaySessionDestinationType::InProcess;GEditor->RequestPlaySession(Params);Stage=1;Deadline=FPlatformTime::Seconds()+60;}
static bool Tick(float){
 if(!GIsRunning||!GEditor)return true;
 if(Deadline>0&&FPlatformTime::Seconds()>Deadline)return Finish(false,TEXT("PIE proof deadline"));
 if(Stage==0){
  UWorld* World=UEditorLoadingAndSavingUtils::NewBlankMap(false);if(!World)return Finish(false,TEXT("Cannot create fixture map"));
  const FString Release=FPaths::ProjectDir()/TEXT("release");FString WorldText;FFileHelper::LoadFileToString(WorldText,*(Release/TEXT("package/world.json")));auto Definition=XaceCanonical::Parse(WorldText);if(!Definition)return Finish(false,TEXT("World missing"));
  auto Owner=World->SpawnActor<AActor>();Owner->SetActorLabel(TEXT("NativeHost"));auto Host=NewObject<UXaceNativeHostComponent>(Owner,TEXT("NativeHostComponent"));Owner->AddInstanceComponent(Host);Host->RegisterComponent();
  Host->ReleaseDirectory=TEXT("release");Host->ReleaseSha256=FXaceNativeHostClient::FileHash(Release/TEXT("native-release.json"));Host->LauncherSha256=FXaceNativeHostClient::FileHash(Release/TEXT("xace-player-launcher.exe"));Host->GameId=TEXT("nec012-proof");FXaceLiveInputBinding Move;Move.Action=TEXT("move_x");Move.NativeSelector=TEXT("proof.move");Host->InputBindings.Add(Move);
  int32 Index=0;for(const auto& Value:Definition->GetArrayField(TEXT("objects"))){auto Object=Value->AsObject();auto Actor=World->SpawnActor<AActor>();Actor->SetActorLabel(FString::Printf(TEXT("Existing%d"),Index++));auto Root=NewObject<USceneComponent>(Actor,TEXT("NativeRoot"));Actor->SetRootComponent(Root);Actor->AddInstanceComponent(Root);Root->RegisterComponent();FVector Position;XaceCanonical::Vector(Object->GetObjectField(TEXT("transform"))->GetObjectField(TEXT("position")),Position);Actor->SetActorLocation(Position);Host->NativeObjects.Add(Object->GetStringField(TEXT("id")),Actor);}
  for(const auto& Value:Definition->GetArrayField(TEXT("objects"))){auto Object=Value->AsObject();const TArray<TSharedPtr<FJsonValue>>* Parents=nullptr;if(Object->GetObjectField(TEXT("relationships"))->TryGetArrayField(TEXT("xace.authoring_parent.v1"),Parents)&&Parents->Num()==1)Host->NativeObjects[Object->GetStringField(TEXT("id"))]->AttachToActor(Host->NativeObjects[(*Parents)[0]->AsString()],FAttachmentTransformRules::KeepWorldTransform);}
  if(!UEditorLoadingAndSavingUtils::SaveMap(World,TEXT("/Game/NativeProof")))return Finish(false,TEXT("Map save failed"));MapHash=FXaceNativeHostClient::FileHash(FPaths::ProjectContentDir()/TEXT("NativeProof.umap"));Launch();return true;
 }
 if(Stage==1&&GEditor->PlayWorld){
  UXaceNativeHostComponent* Host=nullptr;for(TActorIterator<AActor> It(GEditor->PlayWorld);It;++It)if(auto H=It->FindComponentByClass<UXaceNativeHostComponent>()){Host=H;break;}
  if(!Host)return Finish(false,TEXT("PIE native host missing"));if(Host->State==TEXT("failed"))return Finish(false,Host->Error);if(Host->State!=TEXT("playing"))return true;
  Host->Input->SubmitNativeAction(TEXT("proof.move"),1);
  if(Host->Projection->GetCurrentTick()<12)return true;
  bool Native=true,Moved=false;for(const auto& Pair:Host->NativeObjects){int64 Id=Host->Transport->Session.Bindings.FindRef(Pair.Key);Native&=Host->Projection->GetEntityActor(Id)==Pair.Value;Moved|=Pair.Value->GetActorLocation().Y>710;}
  if(!Native||!Moved)return Finish(false,TEXT("PIE native identity or authoritative movement failed"));
  OwnerPid=Host->OwnerProcessId();RuntimePid=uint32(Host->RuntimePid);auto R=MakeShared<FJsonObject>();R->SetNumberField(TEXT("tick"),Host->Projection->GetCurrentTick());R->SetNumberField(TEXT("owner_pid"),OwnerPid);R->SetNumberField(TEXT("runtime_pid"),RuntimePid);R->SetBoolField(TEXT("native_identity"),Native);R->SetBoolField(TEXT("authoritative_input"),Moved);Results.Add(MakeShared<FJsonValueObject>(R));GEditor->RequestEndPlayMap();Stage=2;return true;
 }
 if(Stage==2&&!GEditor->PlayWorld){if(!Gone(OwnerPid)||!Gone(RuntimePid))return true;if(MapHash!=FXaceNativeHostClient::FileHash(FPaths::ProjectContentDir()/TEXT("NativeProof.umap")))return Finish(false,TEXT("PIE changed saved map"));if(++Cycles==3)return Finish(true,TEXT(""));Launch();}
 return true;
}
static void Start(){if(FParse::Value(FCommandLine::Get(),TEXT("XacePIEReport="),Report)){Deadline=FPlatformTime::Seconds()+120;FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateStatic(&Tick));}}
}
#endif
