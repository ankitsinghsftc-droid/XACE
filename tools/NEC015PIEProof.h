#pragma once
#if WITH_EDITOR
#include "Editor.h"
#include "Settings/LevelEditorPlaySettings.h"
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
#include "XaceNativeApproval.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/AudioComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimSingleNodeInstance.h"
#include "Animation/AnimData/IAnimationDataController.h"
#include "AssetCompilingManager.h"
#include "UObject/SavePackage.h"
#include "Misc/PackageName.h"
#include "Sound/SoundBase.h"
#include "UObject/UObjectIterator.h"
namespace NEC015PIE {
static bool DirtyMapRefused=false,DirtyAssetRefused=false;static bool TwoPIE=false;static TArray<uint32> InstancePids;
static FString Report,MapHash,BadPath,BadHash;static int32 SavePhase=0;static bool AudioSeen=false,AnimationSeen=false;static int32 Stage=0,Cycles=0;static double Deadline=0;static uint32 OwnerPid=0,RuntimePid=0;static TArray<TSharedPtr<FJsonValue>> Results;
static bool Gone(uint32 Id){auto P=FPlatformProcess::OpenProcess(Id);bool R=!P.IsValid()||!FPlatformProcess::IsProcRunning(P);if(P.IsValid())FPlatformProcess::CloseProc(P);return R;}
static bool Finish(bool Ok,const FString& Error){auto R=MakeShared<FJsonObject>();R->SetBoolField(TEXT("ok"),Ok);R->SetStringField(TEXT("error"),Error);R->SetBoolField(TEXT("actual_pie"),true);R->SetBoolField(TEXT("dirty_map_refused"),DirtyMapRefused);R->SetBoolField(TEXT("dirty_asset_refused"),DirtyAssetRefused);R->SetBoolField(TEXT("two_instances"),TwoPIE);R->SetArrayField(TEXT("cycles"),Results);R->SetStringField(TEXT("map_sha256"),MapHash);R->SetBoolField(TEXT("packaged_build"),false);FString Text;FJsonSerializer::Serialize(R,TJsonWriterFactory<>::Create(&Text));FFileHelper::SaveStringToFile(Text,*Report);if(GEditor&&GEditor->PlayWorld)GEditor->RequestEndPlayMap();FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);return false;}
static void Launch(){SavePhase=0;AudioSeen=false;AnimationSeen=false;FRequestPlaySessionParams Params;Params.bAllowOnlineSubsystem=false;Params.WorldType=EPlaySessionWorldType::PlayInEditor;Params.SessionDestination=EPlaySessionDestinationType::InProcess;if(TwoPIE){auto Settings=GetMutableDefault<ULevelEditorPlaySettings>();Settings->SetPlayNetMode(PIE_Standalone);Settings->SetRunUnderOneProcess(true);Settings->SetPlayNumberOfClients(2);}
GEditor->RequestPlaySession(Params);Stage=1;Deadline=FPlatformTime::Seconds()+60;}
static bool Tick(float){
 if(!GIsRunning||!GEditor)return true;
 if(Deadline>0&&FPlatformTime::Seconds()>Deadline)return Finish(false,TEXT("PIE proof deadline"));
 if(Stage==0){
  UWorld* World=UEditorLoadingAndSavingUtils::NewBlankMap(false);if(!World)return Finish(false,TEXT("Cannot create fixture map"));
  const FString Release=FPaths::ProjectDir()/TEXT("release");FString WorldText;FFileHelper::LoadFileToString(WorldText,*(Release/TEXT("package/world.json")));auto Definition=XaceCanonical::Parse(WorldText);if(!Definition)return Finish(false,TEXT("World missing"));
  auto Owner=World->SpawnActor<AActor>();Owner->SetActorLabel(TEXT("NativeHost"));auto Host=NewObject<UXaceNativeHostComponent>(Owner,TEXT("NativeHostComponent"));Owner->AddInstanceComponent(Host);Host->RegisterComponent();
  Host->ReleaseDirectory=TEXT("release");Host->ReleaseSha256=FXaceNativeHostClient::FileHash(Release/TEXT("native-release.json"));Host->LauncherSha256=FXaceNativeHostClient::FileHash(Release/TEXT("xace-player-launcher.exe"));Host->GameId=TEXT("nec012-proof");FXaceLiveInputBinding Move;Move.Action=TEXT("move_x");Move.NativeSelector=TEXT("proof.move");Host->InputBindings.Add(Move);FXaceLiveInputBinding Jump;Jump.Action=TEXT("jump");Jump.Kind=TEXT("button");Jump.NativeSelector=TEXT("proof.jump");Host->InputBindings.Add(Jump);
  auto Skeletal=LoadObject<USkeletalMesh>(nullptr,TEXT("/Engine/EngineMeshes/SkeletalCube.SkeletalCube"));if(!Skeletal)return Finish(false,TEXT("Fixture skeleton missing"));
  auto AnimationPackage=CreatePackage(TEXT("/Game/NativeAnimation"));auto Sequence=NewObject<UAnimSequence>(AnimationPackage,TEXT("NativeAnimation"),RF_Public|RF_Standalone);Sequence->SetSkeleton(Skeletal->GetSkeleton());auto& Controller=Sequence->GetController();Controller.InitializeModel();Controller.SetFrameRate(FFrameRate(30,1),false);Controller.SetNumberOfFrames(FFrameNumber(30),false);Controller.NotifyPopulated();FAssetCompilingManager::Get().FinishAllCompilation();Sequence->WaitOnExistingCompression();
  FSavePackageArgs SaveArgs;SaveArgs.TopLevelFlags=RF_Public|RF_Standalone;SaveArgs.SaveFlags=SAVE_NoError;if(!UPackage::SavePackage(AnimationPackage,Sequence,*FPackageName::LongPackageNameToFilename(TEXT("/Game/NativeAnimation"),FPackageName::GetAssetPackageExtension()),SaveArgs))return Finish(false,TEXT("Fixture animation save failed"));
  int32 Index=0;for(const auto& Value:Definition->GetArrayField(TEXT("objects"))){auto Object=Value->AsObject();auto Actor=World->SpawnActor<AActor>();Actor->SetActorLabel(FString::Printf(TEXT("Existing%d"),Index++));auto Root=NewObject<USceneComponent>(Actor,TEXT("NativeRoot"));Actor->SetRootComponent(Root);Actor->AddInstanceComponent(Root);Root->RegisterComponent();FVector Position;XaceCanonical::Vector(Object->GetObjectField(TEXT("transform"))->GetObjectField(TEXT("position")),Position);Actor->SetActorLocation(Position);auto Mesh=NewObject<USkeletalMeshComponent>(Actor,TEXT("NativeMesh"));Actor->AddInstanceComponent(Mesh);Mesh->SetupAttachment(Root);Mesh->SetSkeletalMesh(Skeletal);Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);Mesh->SetSimulatePhysics(false);Mesh->VisibilityBasedAnimTickOption=EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;Mesh->RegisterComponent();Host->NativeObjects.Add(Object->GetStringField(TEXT("id")),Actor);}
  for(const auto& Value:Definition->GetArrayField(TEXT("objects"))){auto Object=Value->AsObject();const TArray<TSharedPtr<FJsonValue>>* Parents=nullptr;if(Object->GetObjectField(TEXT("relationships"))->TryGetArrayField(TEXT("xace.authoring_parent.v1"),Parents)&&Parents->Num()==1)Host->NativeObjects[Object->GetStringField(TEXT("id"))]->AttachToActor(Host->NativeObjects[(*Parents)[0]->AsString()],FAttachmentTransformRules::KeepWorldTransform);}
  if(!UEditorLoadingAndSavingUtils::SaveMap(World,TEXT("/Game/NativeProof")))return Finish(false,TEXT("Map save failed"));MapHash=FXaceNativeHostClient::FileHash(FPaths::ProjectContentDir()/TEXT("NativeProof.umap"));FString ApprovalError;if(!XaceNativeApproval::RecordSavedSource(ApprovalError))return Finish(false,ApprovalError);
 World->GetOutermost()->SetDirtyFlag(true);DirtyMapRefused=!XaceNativeApproval::ValidateSource(ApprovalError)&&ApprovalError.Contains(TEXT("Save and review native map"));World->GetOutermost()->SetDirtyFlag(false);
 AnimationPackage->SetDirtyFlag(true);DirtyAssetRefused=!XaceNativeApproval::ValidateSource(ApprovalError)&&ApprovalError.Contains(TEXT("Save and review native asset"));AnimationPackage->SetDirtyFlag(false);
 if(!DirtyMapRefused||!DirtyAssetRefused||!XaceNativeApproval::ValidateSource(ApprovalError))return Finish(false,TEXT("Dirty-source refusal or saved-source recovery failed"));Launch();return true;
 }
 if(Stage==1&&TwoPIE){
  TArray<UXaceNativeHostComponent*> Hosts;
  for(const auto& Context:GEngine->GetWorldContexts())if(Context.WorldType==EWorldType::PIE&&Context.World())for(TActorIterator<AActor> It(Context.World());It;++It)if(auto H=It->FindComponentByClass<UXaceNativeHostComponent>())Hosts.Add(H);
  if(Hosts.Num()!=2)return true;
  for(auto H:Hosts){if(H->State==TEXT("failed"))return Finish(false,H->Error);if(H->State!=TEXT("playing"))return true;H->Input->SubmitNativeAction(TEXT("proof.move"),1);if(H->Projection->GetCurrentTick()<12)return true;}
  if(Hosts[0]->OwnerProcessId()==Hosts[1]->OwnerProcessId()||Hosts[0]->RuntimePid==Hosts[1]->RuntimePid)return Finish(false,TEXT("PIE authority processes shared"));
  auto Extra=Hosts[0]->GetWorld()->SpawnActor<AActor>();auto Duplicate=NewObject<UXaceNativeHostComponent>(Extra);Extra->AddInstanceComponent(Duplicate);Duplicate->RegisterComponent();
  if(Duplicate->State!=TEXT("failed")||Duplicate->OwnerProcessId()!=0||Duplicate->Error!=TEXT("Another native host owns this world"))return Finish(false,TEXT("Duplicate world owner not refused"));
  for(auto H:Hosts){auto R=MakeShared<FJsonObject>();R->SetNumberField(TEXT("owner_pid"),H->OwnerProcessId());R->SetNumberField(TEXT("runtime_pid"),H->RuntimePid);R->SetNumberField(TEXT("tick"),H->Projection->GetCurrentTick());R->SetBoolField(TEXT("duplicate_refused"),true);Results.Add(MakeShared<FJsonValueObject>(R));InstancePids.Add(H->OwnerProcessId());InstancePids.Add(uint32(H->RuntimePid));}
  GEditor->RequestEndPlayMap();Stage=3;return true;
 }
 if(Stage==3&&!GEditor->PlayWorld){for(auto P:InstancePids)if(!Gone(P))return true;return Finish(true,TEXT(""));}
 if(Stage==1&&GEditor->PlayWorld){
  UXaceNativeHostComponent* Host=nullptr;for(TActorIterator<AActor> It(GEditor->PlayWorld);It;++It)if(auto H=It->FindComponentByClass<UXaceNativeHostComponent>()){Host=H;break;}
  if(!Host)return Finish(false,TEXT("PIE native host missing"));if(Host->State==TEXT("failed"))return Finish(false,Host->Error);if(Host->State!=TEXT("playing"))return true;
  Host->Input->SubmitNativeAction(TEXT("proof.move"),1);Host->Input->SubmitNativeAction(TEXT("proof.jump"),Host->Projection->GetCurrentTick()%20>=10?1:0);
  for(TObjectIterator<UAudioComponent> It;It;++It)if(It->GetWorld()==GEditor->PlayWorld&&It->Sound&&It->Sound->GetPathName()==TEXT("/Engine/EngineSounds/1kSineTonePing.1kSineTonePing")&&It->IsPlaying())AudioSeen=true;
  for(const auto& Pair:Host->NativeObjects)if(auto Mesh=Pair.Value->FindComponentByClass<USkeletalMeshComponent>())if(Mesh->GetSingleNodeInstance()&&Mesh->GetSingleNodeInstance()->IsPlaying())AnimationSeen=true;
  if(Host->Projection->GetCurrentTick()<12||!AudioSeen||!AnimationSeen)return true;
  FString GoodSlot=FString::Printf(TEXT("nec015-good-%d"),Cycles),BadSlot=FString::Printf(TEXT("nec015-bad-%d"),Cycles);
  if(SavePhase==0){IFileManager::Get().MakeDirectory(*Host->SaveRoot,true);auto Envelope=MakeShared<FJsonObject>();Envelope->SetStringField(TEXT("schema"),TEXT("xace.native_save.v1"));auto Identity=XaceCanonical::Parse(Host->SaveIdentityJson);Envelope->SetObjectField(TEXT("identity"),Identity);auto Snapshot=MakeShared<FJsonObject>();Snapshot->SetNumberField(TEXT("tick"),12);Envelope->SetObjectField(TEXT("snapshot"),Snapshot);Envelope->SetStringField(TEXT("payload_sha256"),XaceCanonical::Hash(TEXT("{\"tick\":12}")));
   const FString GoodPath=Host->SaveRoot/(TEXT("slot-")+GoodSlot+TEXT(".json"));BadPath=Host->SaveRoot/(TEXT("slot-")+BadSlot+TEXT(".json"));if(FPaths::FileExists(GoodPath)||FPaths::FileExists(BadPath))return Finish(false,TEXT("Refuse existing save fixture"));FFileHelper::SaveStringToFile(XaceCanonical::Json(Envelope),*GoodPath);Identity->SetStringField(TEXT("game_id"),TEXT("wrong-game"));FFileHelper::SaveStringToFile(XaceCanonical::Json(Envelope),*BadPath);BadHash=FXaceNativeHostClient::FileHash(BadPath);if(!Host->CheckSave(GoodSlot))return Finish(false,TEXT("Check-save request failed"));SavePhase=1;return true;}
  if(SavePhase==1){if(Host->SaveStatus==TEXT("checking"))return true;if(Host->SaveStatus!=TEXT("compatible-not-restored"))return Finish(false,TEXT("Compatible save refused: ")+Host->SaveError);Host->CheckSave(BadSlot);SavePhase=2;return true;}
  if(SavePhase==2){if(Host->SaveStatus==TEXT("checking"))return true;if(Host->SaveStatus!=TEXT("refused")||BadHash!=FXaceNativeHostClient::FileHash(BadPath))return Finish(false,TEXT("Incompatible save not preserved/refused"));SavePhase=3;}
  bool Native=true,Moved=false;for(const auto& Pair:Host->NativeObjects){int64 Id=Host->Transport->Session.Bindings.FindRef(Pair.Key);Native&=Host->Projection->GetEntityActor(Id)==Pair.Value;Moved|=Pair.Value->GetActorLocation().Y>710;}
  if(!Native||!Moved)return Finish(false,TEXT("PIE native identity or authoritative movement failed"));
  OwnerPid=Host->OwnerProcessId();RuntimePid=uint32(Host->RuntimePid);auto R=MakeShared<FJsonObject>();R->SetNumberField(TEXT("tick"),Host->Projection->GetCurrentTick());R->SetNumberField(TEXT("owner_pid"),OwnerPid);R->SetNumberField(TEXT("runtime_pid"),RuntimePid);R->SetBoolField(TEXT("native_identity"),Native);R->SetBoolField(TEXT("audio"),AudioSeen);R->SetBoolField(TEXT("animation"),AnimationSeen);R->SetBoolField(TEXT("save_checks"),SavePhase==3);R->SetBoolField(TEXT("authoritative_input"),Moved);Results.Add(MakeShared<FJsonValueObject>(R));GEditor->RequestEndPlayMap();Stage=2;return true;
 }
 if(Stage==2&&!GEditor->PlayWorld){if(!Gone(OwnerPid)||!Gone(RuntimePid))return true;if(MapHash!=FXaceNativeHostClient::FileHash(FPaths::ProjectContentDir()/TEXT("NativeProof.umap")))return Finish(false,TEXT("PIE changed saved map"));if(++Cycles==3)return Finish(true,TEXT(""));Launch();}
 return true;
}
static void Start(){if(FParse::Value(FCommandLine::Get(),TEXT("XacePIEReport="),Report)){TwoPIE=FParse::Param(FCommandLine::Get(),TEXT("XaceTwoPIE"));Deadline=FPlatformTime::Seconds()+120;FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateStatic(&Tick));}}
}
#endif
