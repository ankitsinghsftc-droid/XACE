#pragma once
#if !WITH_EDITOR
#include "XaceNativeHost.h"
#include "Engine/Engine.h"
#include "EngineUtils.h"
#include "Containers/Ticker.h"
#include "Misc/Parse.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Components/AudioComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimSingleNodeInstance.h"
#include "Sound/SoundBase.h"
#include "UObject/UObjectIterator.h"
namespace NEC015Packaged {
static FString Report;static double Deadline=0;static bool Audio=false,Animation=false;static UXaceNativeHostComponent* Host=nullptr;
static bool Finish(bool Ok,const FString& Why){auto R=MakeShared<FJsonObject>();R->SetBoolField(TEXT("ok"),Ok);R->SetStringField(TEXT("error"),Why);R->SetBoolField(TEXT("packaged"),true);R->SetBoolField(TEXT("audio"),Audio);R->SetBoolField(TEXT("animation"),Animation);R->SetNumberField(TEXT("owner_pid"),Host?Host->OwnerProcessId():0);R->SetNumberField(TEXT("runtime_pid"),Host?Host->RuntimePid:0);R->SetNumberField(TEXT("tick"),Host&&Host->Projection?Host->Projection->GetCurrentTick():0);FFileHelper::SaveStringToFile(XaceCanonical::Json(R),*Report,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);if(Host)Host->Stop();FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);return false;}
static bool Tick(float){
 if(FPlatformTime::Seconds()>Deadline)return Finish(false,TEXT("Packaged native deadline"));if(!GEngine)return true;
 UWorld* World=nullptr;for(const auto& Context:GEngine->GetWorldContexts())if(Context.World()&&Context.World()->IsGameWorld()){World=Context.World();break;}if(!World)return true;
 if(!Host)for(TActorIterator<AActor> It(World);It;++It)if(auto Found=It->FindComponentByClass<UXaceNativeHostComponent>()){Host=Found;break;}if(!Host)return true;
 if(Host->State==TEXT("failed"))return Finish(FParse::Param(FCommandLine::Get(),TEXT("XaceExpectRefusal")),Host->Error);if(Host->State!=TEXT("playing"))return true;
 Host->Input->SubmitNativeAction(TEXT("proof.move"),1);Host->Input->SubmitNativeAction(TEXT("proof.jump"),Host->Projection->GetCurrentTick()%20>=10?1:0);
 for(TObjectIterator<UAudioComponent> It;It;++It)if(It->GetWorld()==World&&It->Sound&&It->IsPlaying())Audio=true;
 bool Native=true,Moved=false;for(const auto& Pair:Host->NativeObjects){Native&=Host->Projection->GetEntityActor(Host->Transport->Session.Bindings.FindRef(Pair.Key))==Pair.Value;Moved|=Pair.Value->GetActorLocation().Y>710;if(auto Mesh=Pair.Value->FindComponentByClass<USkeletalMeshComponent>())if(Mesh->GetSingleNodeInstance()&&Mesh->GetSingleNodeInstance()->IsPlaying())Animation=true;}
 if(Host->Projection->GetCurrentTick()>=12&&Audio&&Animation)return Finish(Native&&Moved,Native&&Moved?TEXT(""):TEXT("Packaged native identity/input failed"));return true;
}
static void Start(){if(FParse::Value(FCommandLine::Get(),TEXT("XaceNativeReport="),Report)){Deadline=FPlatformTime::Seconds()+90;FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateStatic(&Tick));}}
}
#endif
