#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Containers/Queue.h"
#include "Dom/JsonObject.h"
#include "XaceTransport.generated.h"

USTRUCT(BlueprintType)
struct FXaceInputAction
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FString Action;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") float Value = 0.0f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") float SecondaryValue = 0.0f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FString Kind = TEXT("custom");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") FString Phase = TEXT("performed");

	TSharedRef<FJsonObject> ToJson() const;
};

USTRUCT(BlueprintType)
struct FXaceInputPacket
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Identity") int64 PeerId = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Tick") int64 Tick = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Identity") int64 PlayerId = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") int64 SequenceId = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") TArray<FXaceInputAction> Actions;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") int64 TimestampMs = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Identity") FString DeviceId = TEXT("unreal");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Input") bool bPredicted = false;

	TSharedRef<FJsonObject> ToJson() const;
};

USTRUCT(BlueprintType)
struct FXaceEntityState
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Entity") int64 EntityId = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Entity") FString ActorId;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Entity") TMap<int32, FString> Components;
};

USTRUCT(BlueprintType)
struct FXaceAssetReference
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Asset") FString Id;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Asset") FString AssetType;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Asset") FString Status;
};

USTRUCT(BlueprintType)
struct FXacePlaybackCommand
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") FString BindingId;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") FString EventName;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") FString PlaybackKind;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") int64 EntityId = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") FXaceAssetReference Asset;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") FString SemanticAction;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") TMap<FString, FString> Parameters;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") int32 Priority = 0;
};

USTRUCT(BlueprintType)
struct FXaceHandshakeAck
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") bool bAccepted = false;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") FString RejectReason;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") FString SessionId;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") int32 TickRate = 60;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") FString CgsHash;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") FString SchemaVersion;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Handshake") TArray<FXaceEntityState> InitialEntities;
};

USTRUCT(BlueprintType)
struct FXaceTickSnapshot
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Tick") int64 Tick = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Tick") int64 TimestampMs = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Tick") TArray<FXaceEntityState> Entities;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Tick") TArray<int64> SpawnedIds;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Tick") TArray<int64> DestroyedIds;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") TArray<FXacePlaybackCommand> PlaybackCommands;
};

USTRUCT(BlueprintType)
struct FXaceAdapterSideEffectRollback
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FString RollbackId;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FString Reason;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FString FailedStage;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") int64 Tick = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") int64 RestoreTick = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FString RestoredCgsHash;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FString FailedCgsHash;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FString RestoredWorldHash;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") FXaceTickSnapshot RestoredSnapshot;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") TArray<FXacePlaybackCommand> RevokedPlaybackCommands;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") bool bClearFeedbackQueue = true;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") bool bClearPendingEdits = true;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Rollback") bool bResetAssetBindings = true;
};
USTRUCT(BlueprintType)
struct FXaceTransportStats
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly, Category="XACE|Stats") int64 FramesSent = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Stats") int64 FramesReceived = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Stats") int64 BytesSent = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Stats") int64 BytesReceived = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Stats") int64 ProtocolErrors = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Stats") int32 QueuedMessages = 0;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceConnectionChanged, bool, bConnected);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceHandshakeAccepted, const FXaceHandshakeAck&, Ack);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceHandshakeRejected, const FString&, Reason);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceTickSnapshotReceived, const FXaceTickSnapshot&, Snapshot);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceAdapterSideEffectRollbackReceived, const FXaceAdapterSideEffectRollback&, Rollback);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceProtocolError, const FString&, Message);

DECLARE_MULTICAST_DELEGATE_OneParam(FXaceJsonMessageReceived, const TSharedPtr<FJsonObject>&);

UCLASS(ClassGroup=(XACE), meta=(BlueprintSpawnableComponent))
class UXaceTransportComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UXaceTransportComponent();

	UPROPERTY(BlueprintAssignable) FXaceConnectionChanged OnConnectionChanged;
	UPROPERTY(BlueprintAssignable) FXaceHandshakeAccepted OnHandshakeAccepted;
	UPROPERTY(BlueprintAssignable) FXaceHandshakeRejected OnHandshakeRejected;
	UPROPERTY(BlueprintAssignable) FXaceTickSnapshotReceived OnTickSnapshot;
	UPROPERTY(BlueprintAssignable) FXaceAdapterSideEffectRollbackReceived OnAdapterSideEffectRollback;
	UPROPERTY(BlueprintAssignable) FXaceProtocolError OnProtocolError;

	FXaceJsonMessageReceived OnJsonMessage;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Connection") FString Host = TEXT("127.0.0.1");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Connection") int32 Port = 7777;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Connection") bool bAutoConnect = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Connection") bool bReconnect = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Connection") float InitialReconnectDelaySeconds = 1.0f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Connection") float MaxReconnectDelaySeconds = 30.0f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Handshake") FString EngineName = TEXT("Unreal");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Handshake") FString AdapterVersion = TEXT("0.1.0");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Handshake") FString CgsHash;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Handshake") TArray<FString> Capabilities;

	UFUNCTION(BlueprintCallable, Category="XACE") bool ConnectToRuntime();
	UFUNCTION(BlueprintCallable, Category="XACE") void DisconnectFromRuntime(const FString& Reason);
	UFUNCTION(BlueprintCallable, Category="XACE") void ConfigureConnection(const FString& InHost, int32 InPort, const FString& InCgsHash);
	UFUNCTION(BlueprintCallable, Category="XACE") void PumpOnce(float DeltaTime);
	UFUNCTION(BlueprintCallable, Category="XACE") bool SendInputPacket(const FXaceInputPacket& Packet);
	UFUNCTION(BlueprintCallable, Category="XACE") bool IsConnected() const { return Socket != nullptr && bConnected; }
	UFUNCTION(BlueprintCallable, Category="XACE") bool IsHandshakeComplete() const { return bHandshakeComplete; }
	UFUNCTION(BlueprintCallable, Category="XACE") int64 NextSequenceId() { return SequenceId++; }
	UFUNCTION(BlueprintCallable, Category="XACE") FXaceTransportStats GetStats() const { return Stats; }
	UFUNCTION(BlueprintCallable, Category="XACE") FString GetLastError() const { return LastError; }

	bool SendJsonObject(const TSharedRef<FJsonObject>& Message);
	bool SendFeedbackPayload(int64 Tick, const TArray<TSharedPtr<FJsonObject>>& Messages);

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	class FSocket* Socket = nullptr;
	TArray<uint8> ReceiveBuffer;
	TQueue<FString> OutboundJson;
	bool bConnected = false;
	bool bHandshakeComplete = false;
	bool bStopping = false;
	float ReconnectDelay = 1.0f;
	float ReconnectTimer = 0.0f;
	int64 SequenceId = 1;
	FXaceTransportStats Stats;
	FString LastError;

	void PollSocket();
	void FlushOutbound();
	void SendHandshake();
	void DispatchMessage(const TSharedPtr<FJsonObject>& Message);
	void DispatchHandshakeAck(const TSharedPtr<FJsonObject>& Message);
	bool WriteFrame(const FString& Json);
	void Fail(const FString& Message);
	void CloseSocket();

	static bool DecodeFrames(TArray<uint8>& Buffer, TArray<TSharedPtr<FJsonObject>>& OutMessages, FString& OutError);
	static FXaceEntityState ParseEntityState(const TSharedPtr<FJsonObject>& Object);
	static FXaceAssetReference ParseAssetReference(const TSharedPtr<FJsonObject>& Object);
	static FXacePlaybackCommand ParsePlaybackCommand(const TSharedPtr<FJsonObject>& Object);
	static FXaceTickSnapshot ParseTickSnapshot(const TSharedPtr<FJsonObject>& Object);
	static FXaceAdapterSideEffectRollback ParseAdapterSideEffectRollback(const TSharedPtr<FJsonObject>& Object);
	static FXaceHandshakeAck ParseHandshakeAck(const TSharedPtr<FJsonObject>& Object);
	static FString JsonToString(const TSharedRef<FJsonObject>& Object);
	static FString PortableText(const FString& Value, int32 MaxBytes, const FString& Fallback);
};
