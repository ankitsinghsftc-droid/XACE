#include "XaceNativeHost.h"
#include "XaceNativeApproval.h"
#include "Misc/Paths.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProperties.h"
#include "GameFramework/Actor.h"
#include "Sound/SoundBase.h"
#include "Animation/AnimationAsset.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
namespace { TMap<TWeakObjectPtr<UWorld>,TWeakObjectPtr<UXaceNativeHostComponent>> NativeWorldOwners; }
UXaceNativeHostComponent::UXaceNativeHostComponent(){PrimaryComponentTick.bCanEverTick=true;}
void UXaceNativeHostComponent::BeginPlay()
{
 Super::BeginPlay();
 if(FParse::Value(FCommandLine::Get(),TEXT("XaceNativePreflight="),PreflightReport)){
  if(FPaths::IsRelative(PreflightReport)||FPaths::FileExists(PreflightReport)){PreflightReport.Empty();Closing=true;FPlatformMisc::RequestExitWithStatus(false,2);return;}
 }
 auto& Owner=NativeWorldOwners.FindOrAdd(GetWorld());
 if(Owner.IsValid()&&Owner.Get()!=this){Fail(TEXT("Another native host owns this world"));return;}Owner=this;
 FString ApprovalError;
#if WITH_EDITOR
 if(!XaceNativeApproval::ValidateSource(ApprovalError)){Fail(ApprovalError);return;}
#else
 if(!XaceNativeApproval::ValidateCooked(ApprovalError)){Fail(ApprovalError);return;}
#endif
 if(ReleaseDirectory.IsEmpty()||!FPaths::IsRelative(ReleaseDirectory)||ReleaseDirectory.Contains(TEXT(".."))||ControllerId<=0){Fail(TEXT("Relative release directory and positive controller required"));return;}
 Release=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()/ReleaseDirectory);
 if(FXaceNativeHostClient::FileHash(Release/TEXT("native-release.json"))!=ReleaseSha256){Fail(TEXT("Native release identity mismatch"));return;}
 if(!FFileHelper::LoadFileToString(WorldJson,*(Release/TEXT("package/world.json")))){Fail(TEXT("Native World missing"));return;}
 if(GetOwner()->FindComponentByClass<UXaceTransportComponent>()||GetOwner()->FindComponentByClass<UXaceDeltaApplicatorComponent>()||GetOwner()->FindComponentByClass<UXaceInputCollectorComponent>()){Fail(TEXT("Native host requires exclusive transport components"));return;}
 Projection=NewObject<UXaceDeltaApplicatorComponent>(GetOwner());
 FString Issue;if(!Projection->BindNativeActors(NativeObjects,XaceCanonical::Parse(WorldJson),Issue)){Fail(Issue);return;}
 if(!ValidateResources(Issue)){Fail(Issue);return;}
 if(!PreflightReport.IsEmpty()){State=TEXT("preflight-ready");Closing=true;FinishPreflight(true);return;}
 Projection->bSendLiveValidationFeedback=false;Projection->RegisterComponent();GetOwner()->AddInstanceComponent(Projection);
 const FString Local=FPlatformMisc::GetEnvironmentVariable(TEXT("LOCALAPPDATA"));
 if(Local.IsEmpty()||FPaths::IsRelative(Local)){Fail(TEXT("Absolute per-user directory required"));return;}
 if(!Client.Start(Release/TEXT("xace-player-launcher.exe"),LauncherSha256,Release,ReleaseSha256,Local/TEXT("XACE/NativeHistory"),uint64(ControllerId))){Fail(Client.Error);return;}
 State=TEXT("verifying");Deadline=FPlatformTime::Seconds()+20;
}
void UXaceNativeHostComponent::TickComponent(float Delta,ELevelTick Type,FActorComponentTickFunction* Tick)
{
 Super::TickComponent(Delta,Type,Tick);if(Closing)return;
 if(SavePending&&FPlatformTime::Seconds()>SaveDeadline){Fail(TEXT("Save check timeout"));return;}
 if(Projection&&!Projection->NativeProjectionError.IsEmpty()){Fail(Projection->NativeProjectionError);return;}
 TArray<TSharedPtr<FJsonObject>> Rows;if(!Client.Poll(Rows)){Fail(Client.Error.IsEmpty()?TEXT("Native owner unavailable"):Client.Error);return;}
 for(const auto& Row:Rows){
  bool Ok=true;if(Row->TryGetBoolField(TEXT("ok"),Ok)&&!Ok){FString Message;Row->TryGetStringField(TEXT("message"),Message);FString Refusal;Row->TryGetStringField(TEXT("state"),Refusal);if(SavePending&&Refusal==TEXT("refused")){SavePending=false;SaveStatus=TEXT("refused");SaveError=Message;continue;}Fail(TEXT("Native refused: ")+Message);return;}
  FString Schema;Row->TryGetStringField(TEXT("schema"),Schema);
  if(Schema==TEXT("xace.native_host.ready.v1")){
   const TSharedPtr<FJsonObject>* Identity=nullptr;FString Actual;
   if(State!=TEXT("verifying")||!Row->TryGetObjectField(TEXT("save_identity"),Identity)||!(*Identity)->TryGetStringField(TEXT("game_id"),Actual)||Actual!=GameId||!Row->TryGetStringField(TEXT("save_root"),SaveRoot)){Fail(TEXT("Native game/save identity mismatch"));return;}
   SaveIdentityJson=XaceCanonical::Json(*Identity);
   if(!Client.Send(TEXT("play"))){Fail(Client.Error);return;}State=TEXT("starting");continue;
  }
  const TSharedPtr<FJsonObject>* Result=nullptr;if(!Row->TryGetObjectField(TEXT("result"),Result))continue;
  FString ResultState;(*Result)->TryGetStringField(TEXT("state"),ResultState);if(ResultState==TEXT("save_compatible")){bool Restored=true;if(!SavePending||!(*Result)->TryGetBoolField(TEXT("restored"),Restored)||Restored){Fail(TEXT("Unexpected save response"));return;}SavePending=false;SaveStatus=TEXT("compatible-not-restored");continue;}if(ResultState!=TEXT("ready"))continue;
  FString Actual,Endpoint,TicketPath,Ticket;double Pid=0;
  if(State!=TEXT("starting")||!(*Result)->TryGetStringField(TEXT("release"),Actual)||Actual!=ReleaseSha256||!(*Result)->TryGetStringField(TEXT("endpoint"),Endpoint)||!(*Result)->TryGetStringField(TEXT("ticket"),TicketPath)||!(*Result)->TryGetNumberField(TEXT("runtime_pid"),Pid)||!FFileHelper::LoadFileToString(Ticket,*TicketPath)){Fail(TEXT("Invalid native readiness"));return;}
  FString Host,Port;if(!Endpoint.Split(TEXT(":"),&Host,&Port)||Host!=TEXT("127.0.0.1")||!Port.IsNumeric()){Fail(TEXT("Invalid loopback endpoint"));return;}
  RuntimePid=int64(Pid);Transport=NewObject<UXaceTransportComponent>(GetOwner());Transport->bAutoConnect=false;Transport->bReconnect=false;Transport->Host=Host;Transport->Port=FCString::Atoi(*Port);
  if(!Transport->ConfigureLiveSession(Ticket,WorldJson)){Fail(TEXT("Native ticket refused"));return;}
  GetOwner()->AddInstanceComponent(Transport);Transport->RegisterComponent();
  Transport->OnHandshakeAccepted.AddDynamic(this,&UXaceNativeHostComponent::Handshake);Transport->OnConnectionChanged.AddDynamic(this,&UXaceNativeHostComponent::Connection);Transport->OnProtocolError.AddDynamic(this,&UXaceNativeHostComponent::Protocol);
  Input=NewObject<UXaceInputCollectorComponent>(GetOwner());Input->LiveBindings=InputBindings;GetOwner()->AddInstanceComponent(Input);Input->RegisterComponent();Input->BindTransportNow();Projection->BindTransportNow();Projection->OnPlaybackCommandApplied.AddDynamic(this,&UXaceNativeHostComponent::Playback);
  State=TEXT("connecting");if(!Transport->ConnectToRuntime()){Fail(TEXT("Native connection failed"));return;}
 }
 if(State!=TEXT("playing")&&FPlatformTime::Seconds()>Deadline)Fail(TEXT("Native readiness timeout"));
}
void UXaceNativeHostComponent::Handshake(const FXaceHandshakeAck& Ack){if(!Ack.bAccepted){Fail(TEXT("Native handshake rejected"));return;}State=TEXT("playing");}
void UXaceNativeHostComponent::Connection(bool Connected){if(!Connected&&State==TEXT("playing")&&!Closing)Fail(TEXT("Native authority connection lost"));}
void UXaceNativeHostComponent::Protocol(const FString& Why){if(!Closing)Fail(Why);}
void UXaceNativeHostComponent::Playback(const FXacePlaybackCommand&,bool Applied){if(!Applied&&!Closing)Fail(TEXT("Required native playback failed"));}
void UXaceNativeHostComponent::Fail(const FString& Why){Error=Why;State=TEXT("failed");UE_LOG(LogTemp,Error,TEXT("XACE native: %s"),*Why);Stop();FinishPreflight(false);}
void UXaceNativeHostComponent::Stop(){if(Closing)return;Closing=true;if(auto Owner=NativeWorldOwners.Find(GetWorld()))if(Owner->Get()==this)NativeWorldOwners.Remove(GetWorld());if(State!=TEXT("failed"))State=TEXT("stopped");if(Transport)Transport->DisconnectFromRuntime(TEXT("Native owner stopped"));Client.Close();}
void UXaceNativeHostComponent::EndPlay(const EEndPlayReason::Type Reason){Stop();Super::EndPlay(Reason);}

bool UXaceNativeHostComponent::CheckSave(const FString& Slot){if(State!=TEXT("playing")||SavePending)return false;if(!Client.Send(TEXT("check-save"),Slot)){SaveError=Client.Error;return false;}SavePending=true;SaveDeadline=FPlatformTime::Seconds()+20;SaveStatus=TEXT("checking");SaveError.Empty();return true;}

bool UXaceNativeHostComponent::ValidateResources(FString& Issue)
{
 FString Text;if(!FFileHelper::LoadFileToString(Text,*(Release/TEXT("package/game.cgs.json")))){Issue=TEXT("Native game definition missing");return false;}auto Game=XaceCanonical::Parse(Text);const TSharedPtr<FJsonObject>* Bindings=nullptr;const TArray<TSharedPtr<FJsonValue>>* Rows=nullptr;
 if(!Game.IsValid()){Issue=TEXT("Invalid native game definition");return false;}if(!Game->TryGetObjectField(TEXT("semantic_bindings"),Bindings))return true;if(!(*Bindings)->TryGetArrayField(TEXT("bindings"),Rows)){Issue=TEXT("Invalid native binding list");return false;}
 for(const auto& Value:*Rows){auto Row=Value->AsObject();const TSharedPtr<FJsonObject>* Params=nullptr;if(!Row.IsValid()||!Row->TryGetObjectField(TEXT("parameters"),Params))continue;FString Required;(*Params)->TryGetStringField(TEXT("xace_binding_required"),Required);if(Required!=TEXT("true"))continue;
  FString Kind,Path;Row->TryGetStringField(TEXT("playback_kind"),Kind);(*Params)->TryGetStringField(TEXT("resource_path"),Path);if(!(Path.StartsWith(TEXT("/Game/"))||Path.StartsWith(TEXT("/Engine/")))||Path.Contains(TEXT(".."))){Issue=TEXT("Required native resource path invalid");return false;}
  if(Kind==TEXT("Audio")){auto Sound=LoadObject<USoundBase>(nullptr,*Path);if(!Sound||Sound->GetDuration()<=0){Issue=TEXT("Required native audio missing");return false;}}
  else if(Kind==TEXT("Animation")){auto Animation=LoadObject<UAnimationAsset>(nullptr,*Path);if(!Animation){Issue=TEXT("Required native animation missing");return false;}for(const auto& Pair:NativeObjects){auto Mesh=Pair.Value->FindComponentByClass<USkeletalMeshComponent>();if(!Mesh||!Mesh->GetSkeletalMeshAsset()||Mesh->GetSkeletalMeshAsset()->GetSkeleton()!=Animation->GetSkeleton()){Issue=TEXT("Required native animation skeleton mismatch");return false;}}}
  else {Issue=TEXT("Required native playback profile unsupported");return false;}
 }
 return true;
}

void UXaceNativeHostComponent::FinishPreflight(bool Ok){if(PreflightReport.IsEmpty())return;auto R=MakeShared<FJsonObject>();R->SetStringField(TEXT("schema"),TEXT("xace.unreal.native_preflight.v1"));R->SetBoolField(TEXT("ok"),Ok);R->SetStringField(TEXT("error"),Error);R->SetBoolField(TEXT("authority_started"),Client.ProcessId!=0);R->SetBoolField(TEXT("cooked"),FPlatformProperties::RequiresCookedData());FFileHelper::SaveStringToFile(XaceCanonical::Json(R),*PreflightReport,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);}
