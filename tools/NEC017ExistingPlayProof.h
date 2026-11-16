#pragma once
// Fixture observer only. Binds the imported map; never substitutes a generated map.
#include "Containers/Ticker.h"
#include "EngineUtils.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMeshActor.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "XaceNativeHost.h"
#include "HAL/PlatformProperties.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "XaceNativeApproval.h"
#if WITH_EDITOR
#include "Editor.h"
#include "FileHelpers.h"
#include "PlayInEditorDataTypes.h"
#endif
namespace NEC017Existing {
static FString Report; static double Deadline=0; static int32 Stage=0; static uint32 RuntimePid=0,OwnerPid=0;
static bool StaticRootRefused=false,FinalOk=true;static FString FinalError;
static TSharedPtr<FJsonObject> Result; static TMap<FString,FVector> Initial; static FString Moving;
static bool Gone(uint32 Id){auto Handle=FPlatformProcess::OpenProcess(Id);bool R=!Handle.IsValid()||!FPlatformProcess::IsProcRunning(Handle);if(Handle.IsValid())FPlatformProcess::CloseProc(Handle);return R;}
static bool Finish(bool Ok,const FString& Error){
 if(!Result)Result=MakeShared<FJsonObject>();
 #if WITH_EDITOR
 if(GEditor&&GEditor->PlayWorld){FinalOk=Ok;FinalError=Error;GEditor->RequestEndPlayMap();Stage=2;Deadline=FPlatformTime::Seconds()+30;return true;}
#endif
 if(!Result)Result=MakeShared<FJsonObject>();Result->SetBoolField(TEXT("static_root_refused"),StaticRootRefused);Result->SetBoolField(TEXT("ok"),Ok);Result->SetStringField(TEXT("error"),Error);
 Result->SetNumberField(TEXT("runtime_pid"),RuntimePid);Result->SetNumberField(TEXT("owner_pid"),OwnerPid);
 Result->SetBoolField(TEXT("packaged"),FPlatformProperties::RequiresCookedData());
 FFileHelper::SaveStringToFile(XaceCanonical::Json(Result),*Report,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
 FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);return false;
}
static bool Tick(float){
 if(!GIsRunning||!GEngine)return true;
 if(Deadline&&FPlatformTime::Seconds()>Deadline)return Finish(false,TEXT("Imported native Play timeout"));
#if WITH_EDITOR
 if(Stage==0){
  if(!GEditor)return true;
  auto World=UEditorLoadingAndSavingUtils::LoadMap(FPaths::ProjectContentDir()/TEXT("World.umap"));if(!World)return Finish(false,TEXT("Original imported map missing"));
  FString Raw;if(!FFileHelper::LoadFileToString(Raw,*(FPaths::ProjectDir()/TEXT("release/package/world.json"))))return Finish(false,TEXT("World contract missing"));auto Definition=XaceCanonical::Parse(Raw);if(!Definition)return Finish(false,TEXT("World contract invalid"));
  TMap<FString,AActor*> Actors;
  for(TActorIterator<AActor> It(World);It;++It)for(auto Tag:It->Tags){FString Text=Tag.ToString();if(Text.StartsWith(TEXT("XACE_AUTHORING_V1:"))){auto Meta=XaceCanonical::Parse(Text.Mid(18));if(Meta){FString Id=TEXT("native_")+Meta->GetStringField(TEXT("namespace_id"))+TEXT("_")+Meta->GetStringField(TEXT("authoring_id"));if(Actors.Contains(Id))return Finish(false,TEXT("Duplicate authoring identity"));Actors.Add(Id,*It);}}}
  auto Owner=World->SpawnActor<AActor>();Owner->SetActorLabel(TEXT("NEC017 NativeHost"));auto Host=NewObject<UXaceNativeHostComponent>(Owner,TEXT("NativeHostComponent"));Owner->AddInstanceComponent(Host);Host->RegisterComponent();
  Host->ReleaseDirectory=TEXT("release");Host->GameId=TEXT("nec017-existing-unreal");Host->ReleaseSha256=FXaceNativeHostClient::FileHash(FPaths::ProjectDir()/TEXT("release/native-release.json"));Host->LauncherSha256=FXaceNativeHostClient::FileHash(FPaths::ProjectDir()/TEXT("release/xace-player-launcher.exe"));
  FXaceLiveInputBinding Binding;Binding.Action=TEXT("move_x");Binding.NativeSelector=TEXT("proof.move");Host->InputBindings.Add(Binding);
  for(auto Value:Definition->GetArrayField(TEXT("objects"))){auto Object=Value->AsObject();FString Id=Object->GetStringField(TEXT("id"));auto Actor=Actors.FindRef(Id);if(!Actor)return Finish(false,TEXT("Original identity not found: ")+Id);Host->NativeObjects.Add(Id,Actor);Initial.Add(Id,Actor->GetActorLocation());if(Actor->GetActorLabel()==TEXT("Crate0"))Moving=Id;}
  if(Host->NativeObjects.Num()!=50||Moving.IsEmpty())return Finish(false,TEXT("Imported selection differs"));
  auto RefusalProbe=NewObject<UXaceDeltaApplicatorComponent>(Owner);FString Refusal;StaticRootRefused=!RefusalProbe->BindNativeActors(Host->NativeObjects,Definition,Refusal)&&Refusal==TEXT("Native projection requires movable native root")&&RefusalProbe->GetEntityCount()==0;for(auto Pair:Host->NativeObjects)StaticRootRefused&=Pair.Value->GetActorLocation().Equals(Initial[Pair.Key],0.001);if(!StaticRootRefused)return Finish(false,TEXT("Static-root admission was not safely refused"));RefusalProbe->DestroyComponent();
  // Explicit test-owner native authoring choice, before save and source approval.
  for(auto Pair:Host->NativeObjects)Pair.Value->GetRootComponent()->SetMobility(EComponentMobility::Movable);
  if(!UEditorLoadingAndSavingUtils::SaveMap(World,TEXT("/Game/World")))return Finish(false,TEXT("Explicit runtime host integration save failed"));
  auto Expected=MakeShared<FJsonObject>();Expected->SetStringField(TEXT("moving"),Moving);auto Positions=MakeShared<FJsonObject>();for(auto Pair:Initial){auto P=MakeShared<FJsonObject>();P->SetNumberField(TEXT("x"),Pair.Value.X);P->SetNumberField(TEXT("y"),Pair.Value.Y);P->SetNumberField(TEXT("z"),Pair.Value.Z);Positions->SetObjectField(Pair.Key,P);}Expected->SetObjectField(TEXT("positions"),Positions);if(!FFileHelper::SaveStringToFile(XaceCanonical::Json(Expected),*(FPaths::ProjectDir()/TEXT("NEC017.expected.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))return Finish(false,TEXT("Expected state save failed"));
  FString Issue;if(!XaceNativeApproval::RecordSavedSource(Issue))return Finish(false,Issue);
  FRequestPlaySessionParams Params;Params.bAllowOnlineSubsystem=false;Params.WorldType=EPlaySessionWorldType::PlayInEditor;Params.SessionDestination=EPlaySessionDestinationType::InProcess;GEditor->RequestPlaySession(Params);Stage=1;Deadline=FPlatformTime::Seconds()+90;return true;
 }
#endif
 UWorld* World=nullptr;for(auto& Context:GEngine->GetWorldContexts())if(Context.World()&&(Context.WorldType==EWorldType::PIE||Context.WorldType==EWorldType::Game)){World=Context.World();break;}
 if(Stage==2){
#if WITH_EDITOR
  if(GEditor&&GEditor->PlayWorld)return true;
#endif
  if(!Gone(RuntimePid)||!Gone(OwnerPid))return true;Result->SetBoolField(TEXT("process_cleanup"),true);return Finish(FinalOk,FinalError);
 }
 if(!World)return true;UXaceNativeHostComponent* Host=nullptr;for(TActorIterator<AActor> It(World);It;++It)if(auto Component=It->FindComponentByClass<UXaceNativeHostComponent>()){Host=Component;break;}
 if(!Host)return true;if(Host->State==TEXT("failed"))return Finish(false,Host->Error);if(Host->State!=TEXT("playing"))return true;
 Host->Input->SubmitNativeAction(TEXT("proof.move"),1);if(Host->Projection->GetCurrentTick()<30)return true;
 bool Native=Host->NativeObjects.Num()==50&&Host->Projection->GetEntityCount()==50,Positions=true,Resources=true,Static=true;int32 Moved=0;
 for(auto Pair:Host->NativeObjects){auto Actor=Pair.Value;int64 Id=Host->Transport->Session.Bindings.FindRef(Pair.Key);Native&=Host->Projection->GetEntityActor(Id)==Actor;auto Marker=Actor->FindComponentByClass<UXaceEntityMarkerComponent>();FString Raw;FVector Expected;Positions&=Marker&&Marker->TryGetComponentJson(1,Raw)&&XaceCanonical::Vector(XaceCanonical::Parse(Raw)->GetObjectField(TEXT("position")),Expected)&&Expected.Equals(Actor->GetActorLocation(),0.01);
  auto Mesh=Actor->FindComponentByClass<UStaticMeshComponent>();Resources&=Mesh&&Mesh->GetStaticMesh()&&Mesh->GetMaterial(0);if(Initial.Contains(Pair.Key)){if(Pair.Key==Moving){if(Actor->GetActorLocation().Y>Initial[Pair.Key].Y+10)++Moved;}else Static&=Actor->GetActorLocation().Equals(Initial[Pair.Key],0.01);}
 }
 RuntimePid=uint32(Host->RuntimePid);OwnerPid=Host->OwnerProcessId();Result=MakeShared<FJsonObject>();Result->SetNumberField(TEXT("objects"),Host->Projection->GetEntityCount());Result->SetNumberField(TEXT("tick"),Host->Projection->GetCurrentTick());Result->SetBoolField(TEXT("native_identity"),Native);Result->SetBoolField(TEXT("exact_projection"),Positions);Result->SetBoolField(TEXT("mesh_material_retained"),Resources);Result->SetBoolField(TEXT("static_objects_unchanged"),Static);Result->SetBoolField(TEXT("authoritative_input"),Moved==1);
 if(!(Native&&Positions&&Resources&&Static&&Moved==1))return Finish(false,TEXT("Native identity/projection/resource/input mismatch"));
#if WITH_EDITOR
 GEditor->RequestEndPlayMap();
#else
 Host->Stop();
#endif
 Stage=2;return true;
}
static void Start(){if(!FParse::Value(FCommandLine::Get(),TEXT("NEC017ExistingReport="),Report))return;Deadline=FPlatformTime::Seconds()+150;
#if !WITH_EDITOR
 FString Raw;TSharedPtr<FJsonObject> Expected;if(!FFileHelper::LoadFileToString(Raw,*(FPaths::ProjectDir()/TEXT("NEC017.expected.json")))||!(Expected=XaceCanonical::Parse(Raw))) {Finish(false,TEXT("Pinned expected state missing"));return;}Moving=Expected->GetStringField(TEXT("moving"));for(auto Pair:Expected->GetObjectField(TEXT("positions"))->Values){auto P=Pair.Value->AsObject();Initial.Add(Pair.Key,FVector(P->GetNumberField(TEXT("x")),P->GetNumberField(TEXT("y")),P->GetNumberField(TEXT("z"))));}Stage=1;
#endif
 FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateStatic(&Tick));}
}
