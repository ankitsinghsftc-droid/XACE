#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "XaceDeltaApplicator.h"
#include "XaceInputCollector.h"
#include "XaceTransport.h"
#include "XaceLiveValidationCommandlet.generated.h"

UCLASS()
class UXaceLiveValidationCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UXaceLiveValidationCommandlet();

	virtual int32 Main(const FString& Params) override;

private:
	bool bConnected = false;
	bool bHandshakeAccepted = false;
	int32 AppliedSnapshots = 0;
	int32 AppliedEntities = 0;
	int32 FeedbackReady = 0;
	int32 InputPacketsBuilt = 0;
	int32 ProtocolErrors = 0;
	FString LastError;

	UFUNCTION() void HandleConnectionChanged(bool bInConnected);
	UFUNCTION() void HandleHandshakeAccepted(const FXaceHandshakeAck& Ack);
	UFUNCTION() void HandleHandshakeRejected(const FString& Reason);
	UFUNCTION() void HandleSnapshotApplied(int64 Tick, int32 EntityCount);
	UFUNCTION() void HandleFeedbackQueued(const FString& FeedbackJson);
	UFUNCTION() void HandleInputPacketBuilt(const FXaceInputPacket& Packet);
	UFUNCTION() void HandleProtocolError(const FString& Message);
};
