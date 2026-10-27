#pragma once
#if !WITH_EDITOR
#include "XaceNativeHost.h"
#include "Engine/Engine.h"
#include "EngineUtils.h"
#include "Containers/Ticker.h"
#include "Misc/Parse.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "Components/AudioComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimSingleNodeInstance.h"
#include "Sound/SoundBase.h"
#include "UObject/UObjectIterator.h"
namespace NEC015Packaged {
static int32 SavePhase=0;static FString BadPath,BadHash;
static FString Report;static double Deadline=0;static bool Audio=false,Animation=false;static UXaceNativeHostComponent* Host=nullptr;
static bool Finish(bool Ok,const FString& Why){auto R=MakeShared<FJsonObject>();R->SetBoolField(TEXT("ok"),Ok);R->SetStringField(TEXT("error"),Why);R->SetBoolField(TEXT("packaged"),true);R->SetBoolField(TEXT("audio"),Audio);R->SetBoolField(TEXT("animation"),Animation);R->SetBoolField(TEXT("save_compatible_not_restored"),SavePhase==3);R->SetBoolField(TEXT("incompatible_save_retained"),SavePhase==3);R->SetBoolField(TEXT("incompatible_save_schema_refused"),SavePhase==3);R->SetNumberField(TEXT("owner_pid"),Host?Host->OwnerProcessId():0);R->SetNumberField(TEXT("runtime_pid"),Host?Host->RuntimePid:0);R->SetNumberField(TEXT("tick"),Host&&Host->Projection?Host->Projection->GetCurrentTick():0);FFileHelper::SaveStringToFile(XaceCanonical::Json(R),*Report,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);if(Host)Host->Stop();FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);return false;}
static bool Tick(float){
 if(FPlatformTime::Seconds()>Deadline)return Finish(false,TEXT("Packaged native deadline"));if(!GEngine)return true;
 UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.World()&&Context.World()->IsGameWorld()){World=Context.World();break;}if(!World)return true;
 if(!Host)for(TActorIterator<AActor> It(World);It;++It)if(auto Found=It->FindComponentByClass<UXaceNativeHostComponent>()){Host=Found;break;}if(!Host)return true;
 if(Host->State==TEXT("failed"))return Finish(FParse::Param(FCommandLine::Get(),TEXT("XaceExpectRefusal")),Host->Error);if(Host->State!=TEXT("playing"))return true;
 Host->Input->SubmitNativeAction(TEXT("proof.move"),1);Host->Input->SubmitNativeAction(TEXT("proof.jump"),Host->Projection->GetCurrentTick()%20>=10?1:0);
 for(TObjectIterator<UAudioComponent> It;It;++It)if(It->GetWorld()==World&&It->Sound&&It->IsPlaying())Audio=true;
 bool Native=true,Moved=false;for(const auto& Pair:Host->NativeObjects){Native&=Host->Projection->GetEntityActor(Host->Transport->Session.Bindings.FindRef(Pair.Key))==Pair.Value;Moved|=Pair.Value->GetActorLocation().Y>710;if(auto Mesh=Pair.Value->FindComponentByClass<USkeletalMeshComponent>())if(Mesh->GetSingleNodeInstance()&&Mesh->GetSingleNodeInstance()->IsPlaying())Animation=true;}
 if(Host->Projection->GetCurrentTick()<12||!Audio||!Animation)return true;
  FString GoodSlot=FString::Printf(TEXT("nec015-good-%u"),Host->OwnerProcessId()),BadSlot=FString::Printf(TEXT("nec015-bad-%u"),Host->OwnerProcessId());
  if(SavePhase==0){IFileManager::Get().MakeDirectory(*Host->SaveRoot,true);auto Envelope=MakeShared<FJsonObject>();Envelope->SetStringField(TEXT("schema"),TEXT("xace.native_save.v1"));auto Identity=XaceCanonical::Parse(Host->SaveIdentityJson);Envelope->SetObjectField(TEXT("identity"),Identity);auto Snapshot=MakeShared<FJsonObject>();Snapshot->SetNumberField(TEXT("tick"),12);Envelope->SetObjectField(TEXT("snapshot"),Snapshot);Envelope->SetStringField(TEXT("payload_sha256"),XaceCanonical::Hash(TEXT("{\"tick\":12}")));
   const FString GoodPath=Host->SaveRoot/(TEXT("slot-")+GoodSlot+TEXT(".json"));BadPath=Host->SaveRoot/(TEXT("slot-")+BadSlot+TEXT(".json"));if(FPaths::FileExists(GoodPath)||FPaths::FileExists(BadPath))return Finish(false,TEXT("Refuse existing save fixture"));FFileHelper::SaveStringToFile(XaceCanonical::Json(Envelope),*GoodPath);Identity->SetStringField(TEXT("save_schema"),TEXT("nec015.unsupported.v2"));FFileHelper::SaveStringToFile(XaceCanonical::Json(Envelope),*BadPath);BadHash=FXaceNativeHostClient::FileHash(BadPath);if(!Host->CheckSave(GoodSlot))return Finish(false,TEXT("Check-save request failed"));SavePhase=1;return true;}
  if(SavePhase==1){if(Host->SaveStatus==TEXT("checking"))return true;if(Host->SaveStatus!=TEXT("compatible-not-restored"))return Finish(false,TEXT("Compatible save refused: ")+Host->SaveError);Host->CheckSave(BadSlot);SavePhase=2;return true;}
  if(SavePhase==2){if(Host->SaveStatus==TEXT("checking"))return true;if(Host->SaveStatus!=TEXT("refused")||BadHash!=FXaceNativeHostClient::FileHash(BadPath))return Finish(false,TEXT("Incompatible save not preserved/refused"));SavePhase=3;}
 return Finish(Native&&Moved,Native&&Moved?TEXT(""):TEXT("Packaged native identity/input failed"));
}
static void Start(){if(FParse::Value(FCommandLine::Get(),TEXT("XaceNativeReport="),Report)){Deadline=FPlatformTime::Seconds()+90;FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateStatic(&Tick));}}
}
#endif
