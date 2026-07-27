#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "XaceTransport.h"

#include <initializer_list>

#include "XaceDeltaApplicator.generated.h"

UCLASS(ClassGroup=(XACE), meta=(BlueprintSpawnableComponent))
class UXaceEntityMarkerComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UPROPERTY(BlueprintReadOnly, Category="XACE|Entity") int64 EntityId = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Entity") FString ActorId;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Entity") int32 ControllerId = 0;
	UPROPERTY(BlueprintReadOnly, Category="XACE|Playback") TArray<FXacePlaybackCommand> RecentPlaybackCommands;

	void SetComponents(const TMap<int32, FString>& InComponents);
	bool TryGetComponentJson(int32 TypeId, FString& OutJson) const;
	void RecordPlaybackCommand(const FXacePlaybackCommand& Command);

private:
	TMap<int32, FString> ComponentJsonByType;
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FXaceSnapshotApplied, int64, Tick, int32, EntityCount);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceFeedbackQueued, const FString&, FeedbackJson);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FXacePlaybackCommandApplied, const FXacePlaybackCommand&, Command, bool, bApplied);

UCLASS(ClassGroup=(XACE), meta=(BlueprintSpawnableComponent))
class UXaceDeltaApplicatorComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UXaceDeltaApplicatorComponent();

	UPROPERTY(BlueprintAssignable) FXaceSnapshotApplied OnSnapshotApplied;
	UPROPERTY(BlueprintAssignable) FXaceFeedbackQueued OnFeedbackQueued;
	UPROPERTY(BlueprintAssignable) FXacePlaybackCommandApplied OnPlaybackCommandApplied;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Scene") TSubclassOf<AActor> FallbackActorClass;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Scene") bool bCreateDebugActors = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Scene") bool bRemoveMissingSnapshotEntities = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Feedback") bool bCollectFeedback = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Feedback") bool bSendFeedbackToRuntime = true;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE|Feedback") bool bSendLiveValidationFeedback = true;

	UFUNCTION(BlueprintCallable, Category="XACE") void RegisterActorClass(const FString& ActorId, TSubclassOf<AActor> ActorClass);
	UFUNCTION(BlueprintCallable, Category="XACE") AActor* GetEntityActor(int64 EntityId) const;
	UFUNCTION(BlueprintCallable, Category="XACE") int32 GetEntityCount() const { return EntityActors.Num(); }
	UFUNCTION(BlueprintCallable, Category="XACE") int64 GetCurrentTick() const { return CurrentTick; }
	UFUNCTION(BlueprintCallable, Category="XACE") void BindTransportNow();

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	static constexpr int32 TransformComponentType = 1;
	static constexpr int32 IdentityComponentType = 2;
	static constexpr int32 InputComponentType = 6;
	static constexpr int32 HealthComponentType = 100;

	UPROPERTY() UXaceTransportComponent* Transport = nullptr;
	UPROPERTY() TMap<int64, AActor*> EntityActors;
	UPROPERTY() TMap<FString, TSubclassOf<AActor>> ActorRegistry;

	int64 CurrentTick = 0;
	int64 GeneratedFrame = 0;
	bool bTransportSubscribed = false;
	TArray<TSharedPtr<FJsonObject>> PendingFeedback;

	bool EnsureTransport();
	void SubscribeTransport();
	void UnsubscribeTransport();
	UFUNCTION() void OnHandshakeAccepted(const FXaceHandshakeAck& Ack);
	UFUNCTION() void OnTickSnapshot(const FXaceTickSnapshot& Snapshot);
	void ApplyEntityList(int64 Tick, const TArray<FXaceEntityState>& Entities, bool bRemoveMissing, const TArray<int64>& DestroyedIds);
	void ApplyPlaybackCommands(const TArray<FXacePlaybackCommand>& Commands);
	bool TryApplyPlaybackCommand(AActor* Actor, const FXacePlaybackCommand& Command) const;
	void QueueLiveValidationFeedback(int64 Tick, const FString& MessageType, int32 OperationCount);
	void UpsertEntity(const FXaceEntityState& State);
	void DestroyEntity(int64 EntityId);
	AActor* SpawnActorForEntity(const FXaceEntityState& State);
	void ApplyComponents(AActor* Actor, UXaceEntityMarkerComponent* Marker, const TMap<int32, FString>& Components);
	void CollectFeedback();
	void FlushFeedback();
	void EnqueueFeedback(const FString& FeedbackType, int64 EntityId, const TSharedRef<FJsonObject>& Payload);

	static FString ResolveActorId(const FXaceEntityState& State);
	static FString ResolveActorId(const FString& Fallback, const TMap<int32, FString>& Components);
	static void ApplyTransform(AActor* Actor, const FString& Json);
	static TSharedPtr<FJsonObject> ParseObject(const FString& Json);
	static TSharedPtr<FJsonObject> GetObject(const TSharedPtr<FJsonObject>& Object, const FString& Field);
	static FString GetString(const TSharedPtr<FJsonObject>& Object, const FString& Field, const FString& Fallback);
	static bool HasAnyField(const TSharedPtr<FJsonObject>& Object, std::initializer_list<const TCHAR*> Fields);
	static FString GetCommandParameter(const FXacePlaybackCommand& Command, const FString& Key, const FString& Fallback);
	static FString CommandResourcePath(const FXacePlaybackCommand& Command);
	static float GetNumber(const TSharedPtr<FJsonObject>& Object, const FString& Field, float Fallback);
	static FString VectorJson(const FVector& Value);
	static FString RotatorJson(const FQuat& Value);
	static FString JsonToString(const TSharedRef<FJsonObject>& Object);
};
