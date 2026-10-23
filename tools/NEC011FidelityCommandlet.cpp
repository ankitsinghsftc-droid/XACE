#include "NEC011FidelityCommandlet.h"
#include "XaceTransport.h"
#include "XaceInputCollector.h"
#include "XaceDeltaApplicator.h"
#include "XaceNativeContract.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "AudioDeviceManager.h"
#include "AssetCompilingManager.h"
#include "Engine/SkeletalMesh.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/AudioComponent.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundWave.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimSingleNodeInstance.h"
#include "Animation/AnimData/IAnimationDataController.h"
#include "UObject/Package.h"
#include "UObject/UObjectIterator.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/EngineVersion.h"
UNEC011FidelityCommandlet::UNEC011FidelityCommandlet(){IsClient=true;IsEditor=true;LogToConsole=true;}
int32 UNEC011FidelityCommandlet::Main(const FString& Params){
#if WITH_EDITOR
 FString ReportPath;FParse::Value(*Params,TEXT("XaceReport="),ReportPath);
 auto Checks=MakeShared<FJsonObject>();
 UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,TEXT("NEC011Fidelity"));
 FAudioDeviceParams AudioParams;AudioParams.AssociatedWorld=World;AudioParams.Scope=EAudioDeviceScope::Shared;World->SetAudioDevice(FAudioDeviceManager::Get()->RequestAudioDevice(AudioParams));
 AActor* Owner=World->SpawnActor<AActor>();
 auto Transport=NewObject<UXaceTransportComponent>(Owner);Owner->AddInstanceComponent(Transport);Transport->bAutoConnect=false;Transport->RegisterComponent();
 auto Adapter=NewObject<UXaceDeltaApplicatorComponent>(Owner);Owner->AddInstanceComponent(Adapter);Adapter->RegisterComponent();Adapter->BindTransportNow();Adapter->bRemoveMissingSnapshotEntities=false;
 FXaceHandshakeAck Ack;Ack.bAccepted=true;FXaceEntityState Entity;Entity.EntityId=42;Entity.ActorId=TEXT("echo");Ack.InitialEntities.Add(Entity);Transport->OnHandshakeAccepted.Broadcast(Ack);
 AActor* Actor=Adapter->GetEntityActor(42);if(!Actor)return 2;
 auto Mesh=NewObject<USkeletalMeshComponent>(Actor);Actor->AddInstanceComponent(Mesh);Mesh->RegisterComponent();
 auto Resource=LoadObject<USkeletalMesh>(nullptr,TEXT("/Engine/EngineMeshes/SkeletalCube.SkeletalCube"));if(!Resource)return 3;Mesh->SetSkeletalMesh(Resource);
 auto Package=CreatePackage(TEXT("/Game/NEC011Echo"));auto Sequence=NewObject<UAnimSequence>(Package,TEXT("Echo"),RF_Public|RF_Standalone);Sequence->SetSkeleton(Resource->GetSkeleton());auto& Controller=Sequence->GetController();Controller.InitializeModel();Controller.SetFrameRate(FFrameRate(30,1),false);Controller.SetNumberOfFrames(FFrameNumber(30),false);Controller.NotifyPopulated();FAssetCompilingManager::Get().FinishAllCompilation();Sequence->WaitOnExistingCompression();Mesh->VisibilityBasedAnimTickOption=EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
 FXacePlaybackCommand Animation;Animation.EntityId=42;Animation.BindingId=TEXT("animation");Animation.PlaybackKind=TEXT("Animation");Animation.Asset.Status=TEXT("Linked");Animation.Parameters.Add(TEXT("resource_path"),Sequence->GetPathName());
 FXaceTickSnapshot Tick;Tick.Tick=1;Tick.PlaybackCommands.Add(Animation);Transport->OnTickSnapshot.Broadcast(Tick);
 Checks->SetBoolField(TEXT("animation_started"),Mesh->GetSingleNodeInstance()!=nullptr&&Mesh->IsPlaying());Mesh->TickAnimation(0.25f,false);Mesh->RefreshBoneTransforms();Checks->SetBoolField(TEXT("animation_advanced"),Mesh->GetPosition()>0.0f);
 FXacePlaybackCommand Audio;Audio.EntityId=42;Audio.BindingId=TEXT("audio");Audio.PlaybackKind=TEXT("Audio");Audio.Asset.Status=TEXT("Linked");Audio.Parameters.Add(TEXT("resource_path"),TEXT("/Engine/EngineSounds/1kSineTonePing.1kSineTonePing"));Tick.Tick=2;Tick.PlaybackCommands={Audio};Transport->OnTickSnapshot.Broadcast(Tick);
 bool AudioStarted=false;int32 MatchingAudio=0;for(TObjectIterator<UAudioComponent> It;It;++It){if(It->GetWorld()==World && It->Sound && It->Sound->GetPathName()==TEXT("/Engine/EngineSounds/1kSineTonePing.1kSineTonePing")){++MatchingAudio;AudioStarted=AudioStarted||It->IsPlaying();}}Checks->SetBoolField(TEXT("audio_started"),MatchingAudio==1&&AudioStarted);
 Animation.Parameters.Add(TEXT("xace_binding_status"),TEXT("resolved"));Animation.BindingId=TEXT("missing");Animation.Parameters[TEXT("resource_path")]=TEXT("/Game/Missing.Missing");Tick.Tick=3;Tick.PlaybackCommands={Animation};Transport->OnTickSnapshot.Broadcast(Tick);
 Audio.EntityId=999;Audio.BindingId=TEXT("failed-fallback");Audio.Parameters.Add(TEXT("xace_binding_status"),TEXT("fallback"));Tick.Tick=4;Tick.PlaybackCommands={Audio};Transport->OnTickSnapshot.Broadcast(Tick);
 Audio.EntityId=42;Audio.BindingId=TEXT("required");Audio.Parameters[TEXT("resource_path")]=TEXT("/Game/Missing.Missing");Audio.Parameters.Add(TEXT("xace_binding_required"),TEXT("true"));Audio.Parameters.Add(TEXT("allow_fallback"),TEXT("true"));Tick.Tick=5;Tick.PlaybackCommands={Audio};Transport->OnTickSnapshot.Broadcast(Tick);
 const FString BindingReport=Adapter->AssetBindingStatusReportJson();
 const auto Parsed=XaceCanonical::Parse(BindingReport);bool MissingBlocked=false,FallbackBlocked=false,RequiredBlocked=false;for(const auto& Row:Parsed->GetArrayField(TEXT("records"))){const auto Record=Row->AsObject();const auto Id=Record->GetStringField(TEXT("binding_id"));if(Id==TEXT("required"))RequiredBlocked=Record->GetStringField(TEXT("status"))==TEXT("missing")&&Record->GetBoolField(TEXT("blocks_runtime"));if(Id==TEXT("missing"))MissingBlocked=Record->GetStringField(TEXT("status"))==TEXT("missing")&&Record->GetBoolField(TEXT("blocks_runtime"));if(Id==TEXT("failed-fallback"))FallbackBlocked=Record->GetStringField(TEXT("status"))==TEXT("missing")&&Record->GetBoolField(TEXT("blocks_runtime"));}Checks->SetBoolField(TEXT("declared_resolved_cannot_hide_failure"),MissingBlocked);Checks->SetBoolField(TEXT("failed_fallback_blocks"),FallbackBlocked);Checks->SetBoolField(TEXT("required_binding_refuses_fallback"),RequiredBlocked);Checks->SetBoolField(TEXT("missing_refused"),BindingReport.Contains(TEXT("missing"))&&BindingReport.Contains(TEXT("playback_resource_missing")));
 auto OriginalSound=LoadObject<USoundBase>(nullptr,TEXT("/Engine/EngineSounds/1kSineTonePing.1kSineTonePing"));auto ReplacementSound=DuplicateObject<USoundWave>(CastChecked<USoundWave>(OriginalSound),CreatePackage(TEXT("/Game/NEC011Audio")),TEXT("Replacement"));ReplacementSound->Volume=0.5f;
 FXacePlaybackCommand ReplacementAudio;ReplacementAudio.EntityId=42;ReplacementAudio.BindingId=TEXT("audio");ReplacementAudio.PlaybackKind=TEXT("Audio");ReplacementAudio.Asset.Status=TEXT("Linked");ReplacementAudio.Parameters.Add(TEXT("resource_path"),ReplacementSound->GetPathName());Tick.Tick=6;Tick.PlaybackCommands={ReplacementAudio};Transport->OnTickSnapshot.Broadcast(Tick);
 bool ReplacementPlayed=false;for(TObjectIterator<UAudioComponent> It;It;++It)if(It->GetWorld()==World&&It->Sound==ReplacementSound&&It->IsPlaying())ReplacementPlayed=true;Checks->SetBoolField(TEXT("replacement_played"),ReplacementPlayed);
 auto Collector=NewObject<UXaceInputCollectorComponent>(Owner);
 FXaceLiveInputBinding Move;Move.Action=TEXT("move_x");Move.NativeSelector=TEXT("MoveRight");FXaceLiveInputBinding Jump;Jump.Action=TEXT("Jump");Jump.Kind=TEXT("button");Jump.NativeSelector=TEXT("JumpButton");Collector->LiveBindings={Move,Jump};
 bool Submitted=Collector->SubmitNativeAction(TEXT("MoveRight"),0.75f)&&Collector->SubmitNativeAction(TEXT("JumpButton"),1);
 TArray<FXaceInputAction> Actions;bool Collected=Collector->CollectDeclaredLiveActions(Actions);
 Checks->SetBoolField(TEXT("native_event_declared_packet_mapping"),Submitted&&Collected&&Actions.Num()==2&&Actions[0].Action==TEXT("Jump")&&Actions[0].Value==1&&Actions[1].Action==TEXT("move_x")&&Actions[1].Value==0.75f);
 TArray<TSharedPtr<FJsonValue>> Sampled;for(const auto& Action:Actions)Sampled.Add(MakeShared<FJsonValueObject>(Action.ToJson()));
 Checks->SetBoolField(TEXT("unknown_out_of_range_input_refused"),!Collector->SubmitNativeAction(TEXT("undeclared"),1)&&!Collector->SubmitNativeAction(TEXT("MoveRight"),2));
 Collector->SubmitNativeAction(TEXT("MoveRight"),0);Collector->SubmitNativeAction(TEXT("JumpButton"),0);Collected=Collector->CollectDeclaredLiveActions(Actions);Checks->SetBoolField(TEXT("native_event_release"),Collected&&Actions.Num()==2&&Actions[0].Phase==TEXT("cancelled")&&Actions[1].Phase==TEXT("cancelled"));
 Collector->LiveBindings={Move,Move};Checks->SetBoolField(TEXT("duplicate_input_mapping_refused"),!Collector->CollectDeclaredLiveActions(Actions)&&Actions.Num()==0);
 bool Ok=true;for(const auto& Item:Checks->Values)Ok=Ok&&Item.Value->AsBool();auto Report=MakeShared<FJsonObject>();Report->SetBoolField(TEXT("ok"),Ok);Report->SetStringField(TEXT("engine"),TEXT("unreal"));Report->SetStringField(TEXT("version"),FEngineVersion::Current().ToString());Report->SetObjectField(TEXT("checks"),Checks);Report->SetArrayField(TEXT("sampled_actions"),Sampled);Report->SetStringField(TEXT("binding_report"),BindingReport);Report->SetBoolField(TEXT("audible_output_certified"),false);
 FFileHelper::SaveStringToFile(XaceCanonical::Json(Report),*ReportPath,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);World->DestroyWorld(false);return Ok?0:1;
#else
 return 1; // This proof is creator/editor tooling, never shipped gameplay.
#endif
}
