#include "XaceNativeHost.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
#include "HAL/PlatformMisc.h"
#include "GameFramework/Actor.h"
UXaceNativeHostComponent::UXaceNativeHostComponent(){PrimaryComponentTick.bCanEverTick=true;}
void UXaceNativeHostComponent::BeginPlay()
{
 Super::BeginPlay();
 // Integration is deliberately opt-in and still requires creator preflight before release.
 if(ReleaseDirectory.IsEmpty()||!FPaths::IsRelative(ReleaseDirectory)||ReleaseDirectory.Contains(TEXT(".."))||ControllerId<=0){Fail(TEXT("Relative release directory and positive controller required"));return;}
 Release=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()/ReleaseDirectory);
 if(FXaceNativeHostClient::FileHash(Release/TEXT("native-release.json"))!=ReleaseSha256){Fail(TEXT("Native release identity mismatch"));return;}
 if(!FFileHelper::LoadFileToString(WorldJson,*(Release/TEXT("package/world.json")))){Fail(TEXT("Native World missing"));return;}
 if(GetOwner()->FindComponentByClass<UXaceTransportComponent>()||GetOwner()->FindComponentByClass<UXaceDeltaApplicatorComponent>()||GetOwner()->FindComponentByClass<UXaceInputCollectorComponent>()){Fail(TEXT("Native host requires exclusive transport components"));return;}
 Projection=NewObject<UXaceDeltaApplicatorComponent>(GetOwner());
 FString Issue;if(!Projection->BindNativeActors(NativeObjects,XaceCanonical::Parse(WorldJson),Issue)){Fail(Issue);return;}
 Projection->bSendLiveValidationFeedback=false;Projection->RegisterComponent();GetOwner()->AddInstanceComponent(Projection);
 const FString Local=FPlatformMisc::GetEnvironmentVariable(TEXT("LOCALAPPDATA"));
 if(Local.IsEmpty()||FPaths::IsRelative(Local)){Fail(TEXT("Absolute per-user directory required"));return;}
 if(!Client.Start(Release/TEXT("xace-player-launcher.exe"),LauncherSha256,Release,ReleaseSha256,Local/TEXT("XACE/NativeHistory"),uint64(ControllerId))){Fail(Client.Error);return;}
 State=TEXT("verifying");Deadline=FPlatformTime::Seconds()+20;
}
void UXaceNativeHostComponent::TickComponent(float Delta,ELevelTick Type,FActorComponentTickFunction* Tick)
{
 Super::TickComponent(Delta,Type,Tick);if(Closing)return;
 if(Projection&&!Projection->NativeProjectionError.IsEmpty()){Fail(Projection->NativeProjectionError);return;}
 TArray<TSharedPtr<FJsonObject>> Rows;if(!Client.Poll(Rows)){Fail(Client.Error.IsEmpty()?TEXT("Native owner unavailable"):Client.Error);return;}
 for(const auto& Row:Rows){
  bool Ok=true;if(Row->TryGetBoolField(TEXT("ok"),Ok)&&!Ok){FString Message;Row->TryGetStringField(TEXT("message"),Message);Fail(TEXT("Native refused: ")+Message);return;}
  FString Schema;Row->TryGetStringField(TEXT("schema"),Schema);
  if(Schema==TEXT("xace.native_host.ready.v1")){
   const TSharedPtr<FJsonObject>* Identity=nullptr;FString Actual;
   if(State!=TEXT("verifying")||!Row->TryGetObjectField(TEXT("save_identity"),Identity)||!(*Identity)->TryGetStringField(TEXT("game_id"),Actual)||Actual!=GameId||!Row->TryGetStringField(TEXT("save_root"),SaveRoot)){Fail(TEXT("Native game/save identity mismatch"));return;}
   if(!Client.Send(TEXT("play"))){Fail(Client.Error);return;}State=TEXT("starting");continue;
  }
  const TSharedPtr<FJsonObject>* Result=nullptr;if(!Row->TryGetObjectField(TEXT("result"),Result))continue;
  FString ResultState;(*Result)->TryGetStringField(TEXT("state"),ResultState);if(ResultState!=TEXT("ready"))continue;
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
void UXaceNativeHostComponent::Fail(const FString& Why){Error=Why;State=TEXT("failed");UE_LOG(LogTemp,Error,TEXT("XACE native: %s"),*Why);Stop();}
void UXaceNativeHostComponent::Stop(){if(Closing)return;Closing=true;if(State!=TEXT("failed"))State=TEXT("stopped");if(Transport)Transport->DisconnectFromRuntime(TEXT("Native owner stopped"));Client.Close();}
void UXaceNativeHostComponent::EndPlay(const EEndPlayReason::Type Reason){Stop();Super::EndPlay(Reason);}
