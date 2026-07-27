#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "InputCoreTypes.h"
#include "XaceTransport.h"
#include "XaceInputCollector.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceInputPacketBuilt, const FXaceInputPacket&, Packet);

UCLASS(ClassGroup=(XACE), meta=(BlueprintSpawnableComponent))
class UXaceInputCollectorComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UXaceInputCollectorComponent();

	UPROPERTY(BlueprintAssignable) FXaceInputPacketBuilt OnInputPacketBuilt;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Identity") int64 PeerId = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Identity") int64 PlayerId = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Identity") FString DeviceId = TEXT("unreal");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Tick") float FallbackTickRateHz = 60.0f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Tick") bool bPredicted = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") bool bSendIdleMovement = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") float Deadzone = 0.01f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FName MoveXAxis = TEXT("MoveRight");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FName MoveYAxis = TEXT("MoveForward");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FName LookXAxis = TEXT("Turn");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FName LookYAxis = TEXT("LookUp");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FKey JumpKey = EKeys::SpaceBar;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FKey PrimaryFireKey = EKeys::LeftMouseButton;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FKey SecondaryFireKey = EKeys::RightMouseButton;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FKey InteractKey = EKeys::E;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FKey SprintKey = EKeys::LeftShift;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FKey CrouchKey = EKeys::LeftControl;

	UFUNCTION(BlueprintCallable, Category="XACE") void FlushNow();
	UFUNCTION(BlueprintCallable, Category="XACE") void BindTransportNow();
	UFUNCTION(BlueprintCallable, Category="XACE") int64 GetLatestRuntimeTick() const { return LatestRuntimeTick; }

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	UXaceTransportComponent* Transport = nullptr;
	bool bTransportSubscribed = false;
	int64 LatestRuntimeTick = 0;
	int64 LastSentTick = 0;
	float TickInterval = 1.0f / 60.0f;
	float TickAccumulator = 0.0f;
	int32 FramesAccumulated = 0;

	float MoveX = 0.0f;
	float MoveY = 0.0f;
	float LookX = 0.0f;
	float LookY = 0.0f;
	bool bJump = false;
	bool bPrimaryFire = false;
	bool bSecondaryFire = false;
	bool bInteract = false;
	bool bSprint = false;
	bool bCrouch = false;
	bool bPause = false;

	bool EnsureTransport();
	void SubscribeTransport();
	void UnsubscribeTransport();
	UFUNCTION() void OnRuntimeTickSnapshot(const FXaceTickSnapshot& Snapshot);
	UFUNCTION() void OnRuntimeHandshake(const FXaceHandshakeAck& Ack);
	void SampleFrame();
	void FlushTick();
	void ResetAccumulated();
	void AddAxis2D(TArray<FXaceInputAction>& Actions, const FString& Name, float X, float Y, bool bIncludeIdle) const;
	static void AddButton(TArray<FXaceInputAction>& Actions, const FString& Name, bool bPressed);
	float SafeAxis(APlayerController* Controller, FName AxisName) const;
	bool SafeKey(APlayerController* Controller, const FKey& Key) const;
};
