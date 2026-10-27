#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "XaceNativeHostClient.h"
#include "XaceTransport.h"
#include "XaceDeltaApplicator.h"
#include "XaceInputCollector.h"
#include "XaceNativeHost.generated.h"

UCLASS(ClassGroup=(XACE),meta=(BlueprintSpawnableComponent))
class UXaceNativeHostComponent : public UActorComponent
{
 GENERATED_BODY()
public:
 UXaceNativeHostComponent();
 UPROPERTY(EditAnywhere,Category="XACE|Native") FString ReleaseDirectory;
 UPROPERTY(EditAnywhere,Category="XACE|Native") FString ReleaseSha256;
 UPROPERTY(EditAnywhere,Category="XACE|Native") FString LauncherSha256;
 UPROPERTY(EditAnywhere,Category="XACE|Native") FString GameId;
 UPROPERTY(EditAnywhere,Category="XACE|Native") int32 ControllerId=1;
 UPROPERTY(EditAnywhere,Category="XACE|Native") TMap<FString,AActor*> NativeObjects;
 UPROPERTY(EditAnywhere,Category="XACE|Native") TArray<FXaceLiveInputBinding> InputBindings;
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") FString State=TEXT("stopped");
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") FString Error;
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") FString SaveRoot;
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") FString SaveIdentityJson;
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") FString SaveStatus=TEXT("unchecked");
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") FString SaveError;
 UFUNCTION(BlueprintCallable,Category="XACE|Native") bool CheckSave(const FString& Slot);
 UPROPERTY(BlueprintReadOnly,Category="XACE|Native") int64 RuntimePid=0;
 UPROPERTY() UXaceTransportComponent* Transport=nullptr;
 UPROPERTY() UXaceDeltaApplicatorComponent* Projection=nullptr;
 UPROPERTY() UXaceInputCollectorComponent* Input=nullptr;
 UFUNCTION(BlueprintCallable,Category="XACE|Native") void Stop();
 uint32 OwnerProcessId() const { return Client.ProcessId; }
protected:
 virtual void BeginPlay() override;
 virtual void EndPlay(const EEndPlayReason::Type Reason) override;
 virtual void TickComponent(float Delta,ELevelTick Type,FActorComponentTickFunction* Tick) override;
private:
 FXaceNativeHostClient Client;
 FString Release;
 FString WorldJson;
 FString PreflightReport;
 void FinishPreflight(bool Ok);
 double Deadline=0;
 bool Closing=false;
 bool SavePending=false;
 double SaveDeadline=0;
 bool ValidateResources(FString& Issue);
 void Fail(const FString& Why);
 UFUNCTION() void Handshake(const FXaceHandshakeAck& Ack);
 UFUNCTION() void Connection(bool Connected);
 UFUNCTION() void Protocol(const FString& Why);
 UFUNCTION() void Playback(const FXacePlaybackCommand& Command,bool Applied);
};
