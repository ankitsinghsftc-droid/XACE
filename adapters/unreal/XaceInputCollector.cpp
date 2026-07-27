#include "XaceInputCollector.h"

#include "Engine/World.h"
#include "GameFramework/PlayerController.h"

UXaceInputCollectorComponent::UXaceInputCollectorComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void UXaceInputCollectorComponent::BeginPlay()
{
	Super::BeginPlay();
	TickInterval = 1.0f / FMath::Max(1.0f, FallbackTickRateHz);
	SubscribeTransport();
}

void UXaceInputCollectorComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	UnsubscribeTransport();
	Super::EndPlay(EndPlayReason);
}

void UXaceInputCollectorComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (!EnsureTransport() || !Transport->IsConnected())
	{
		return;
	}

	SampleFrame();
	FramesAccumulated++;
	TickAccumulator += DeltaTime;
	while (TickAccumulator >= TickInterval)
	{
		TickAccumulator -= TickInterval;
		FlushTick();
	}
}

void UXaceInputCollectorComponent::FlushNow()
{
	if (!EnsureTransport())
	{
		return;
	}
	SubscribeTransport();
	FlushTick();
}

void UXaceInputCollectorComponent::BindTransportNow()
{
	SubscribeTransport();
}

void UXaceInputCollectorComponent::OnRuntimeTickSnapshot(const FXaceTickSnapshot& Snapshot)
{
	LatestRuntimeTick = FMath::Max(LatestRuntimeTick, Snapshot.Tick);
}

void UXaceInputCollectorComponent::OnRuntimeHandshake(const FXaceHandshakeAck& Ack)
{
	if (Ack.TickRate > 0)
	{
		TickInterval = 1.0f / float(Ack.TickRate);
	}
}

void UXaceInputCollectorComponent::SampleFrame()
{
	APlayerController* Controller = GetWorld() != nullptr ? GetWorld()->GetFirstPlayerController() : nullptr;
	if (Controller == nullptr)
	{
		return;
	}

	MoveX += SafeAxis(Controller, MoveXAxis);
	MoveY += SafeAxis(Controller, MoveYAxis);
	LookX += SafeAxis(Controller, LookXAxis);
	LookY += SafeAxis(Controller, LookYAxis);
	bJump |= SafeKey(Controller, JumpKey);
	bPrimaryFire |= SafeKey(Controller, PrimaryFireKey);
	bSecondaryFire |= SafeKey(Controller, SecondaryFireKey);
	bInteract |= SafeKey(Controller, InteractKey);
	bSprint |= SafeKey(Controller, SprintKey);
	bCrouch |= SafeKey(Controller, CrouchKey);
	bPause |= SafeKey(Controller, EKeys::Escape);
}

void UXaceInputCollectorComponent::FlushTick()
{
	if (Transport == nullptr)
	{
		ResetAccumulated();
		return;
	}

	const float Divisor = float(FMath::Max(1, FramesAccumulated));
	TArray<FXaceInputAction> Actions;
	AddAxis2D(Actions, TEXT("move"), MoveX / Divisor, MoveY / Divisor, bSendIdleMovement);
	AddAxis2D(Actions, TEXT("look"), LookX / Divisor, LookY / Divisor, false);
	AddButton(Actions, TEXT("jump"), bJump);
	AddButton(Actions, TEXT("primary_fire"), bPrimaryFire);
	AddButton(Actions, TEXT("secondary_fire"), bSecondaryFire);
	AddButton(Actions, TEXT("interact"), bInteract);
	AddButton(Actions, TEXT("sprint"), bSprint);
	AddButton(Actions, TEXT("crouch"), bCrouch);
	AddButton(Actions, TEXT("pause"), bPause);
	Actions.Sort([](const FXaceInputAction& Left, const FXaceInputAction& Right) {
		return Left.Action < Right.Action;
	});

	FXaceInputPacket Packet;
	Packet.PeerId = FMath::Max<int64>(1, PeerId);
	Packet.PlayerId = PlayerId;
	Packet.Tick = FMath::Max(LatestRuntimeTick + 1, LastSentTick + 1);
	Packet.SequenceId = Transport->NextSequenceId();
	Packet.Actions = Actions;
	Packet.TimestampMs = int64(FPlatformTime::Seconds() * 1000.0);
	Packet.DeviceId = DeviceId.IsEmpty() ? TEXT("unreal") : DeviceId.Left(64);
	Packet.bPredicted = bPredicted;

	if (Transport->SendInputPacket(Packet))
	{
		LastSentTick = Packet.Tick;
		OnInputPacketBuilt.Broadcast(Packet);
	}
	ResetAccumulated();
}

void UXaceInputCollectorComponent::ResetAccumulated()
{
	MoveX = MoveY = LookX = LookY = 0.0f;
	bJump = bPrimaryFire = bSecondaryFire = bInteract = bSprint = bCrouch = bPause = false;
	FramesAccumulated = 0;
}

void UXaceInputCollectorComponent::AddAxis2D(TArray<FXaceInputAction>& Actions, const FString& Name, float X, float Y, bool bIncludeIdle) const
{
	X = FMath::IsFinite(X) ? FMath::Clamp(X, -1.0f, 1.0f) : 0.0f;
	Y = FMath::IsFinite(Y) ? FMath::Clamp(Y, -1.0f, 1.0f) : 0.0f;
	const bool bActive = FMath::Abs(X) > Deadzone || FMath::Abs(Y) > Deadzone;
	if (!bActive && !bIncludeIdle)
	{
		return;
	}

	FXaceInputAction Action;
	Action.Action = Name;
	Action.Value = bActive ? X : 0.0f;
	Action.SecondaryValue = bActive ? Y : 0.0f;
	Action.Kind = TEXT("axis_2d");
	Action.Phase = bActive ? TEXT("changed") : TEXT("cancelled");
	Actions.Add(Action);
}

void UXaceInputCollectorComponent::AddButton(TArray<FXaceInputAction>& Actions, const FString& Name, bool bPressed)
{
	if (!bPressed)
	{
		return;
	}
	FXaceInputAction Action;
	Action.Action = Name;
	Action.Value = 1.0f;
	Action.Kind = TEXT("button");
	Action.Phase = TEXT("performed");
	Actions.Add(Action);
}

float UXaceInputCollectorComponent::SafeAxis(APlayerController* Controller, FName AxisName) const
{
	if (Controller == nullptr || AxisName.IsNone())
	{
		return 0.0f;
	}
	return FMath::Clamp(Controller->GetInputAxisValue(AxisName), -1.0f, 1.0f);
}

bool UXaceInputCollectorComponent::SafeKey(APlayerController* Controller, const FKey& Key) const
{
	return Controller != nullptr && Key.IsValid() && Controller->IsInputKeyDown(Key);
}

bool UXaceInputCollectorComponent::EnsureTransport()
{
	if (Transport == nullptr && GetOwner() != nullptr)
	{
		Transport = GetOwner()->FindComponentByClass<UXaceTransportComponent>();
	}
	return Transport != nullptr;
}

void UXaceInputCollectorComponent::SubscribeTransport()
{
	if (bTransportSubscribed || !EnsureTransport())
	{
		return;
	}
	Transport->OnTickSnapshot.AddDynamic(this, &UXaceInputCollectorComponent::OnRuntimeTickSnapshot);
	Transport->OnHandshakeAccepted.AddDynamic(this, &UXaceInputCollectorComponent::OnRuntimeHandshake);
	bTransportSubscribed = true;
}

void UXaceInputCollectorComponent::UnsubscribeTransport()
{
	if (!bTransportSubscribed || Transport == nullptr)
	{
		return;
	}
	Transport->OnTickSnapshot.RemoveDynamic(this, &UXaceInputCollectorComponent::OnRuntimeTickSnapshot);
	Transport->OnHandshakeAccepted.RemoveDynamic(this, &UXaceInputCollectorComponent::OnRuntimeHandshake);
	bTransportSubscribed = false;
}
