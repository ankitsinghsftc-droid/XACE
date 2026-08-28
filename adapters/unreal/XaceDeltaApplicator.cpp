#include "XaceDeltaApplicator.h"

#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/TextRenderComponent.h"
#include "Components/AudioComponent.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Kismet/GameplayStatics.h"
#include "Animation/AnimationAsset.h"
#include "Particles/ParticleSystem.h"
#include "Particles/ParticleSystemComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sound/SoundBase.h"

void UXaceEntityMarkerComponent::SetComponents(const TMap<int32, FString>& InComponents)
{
	ComponentJsonByType = InComponents;
}

bool UXaceEntityMarkerComponent::TryGetComponentJson(int32 TypeId, FString& OutJson) const
{
	if (const FString* Found = ComponentJsonByType.Find(TypeId))
	{
		OutJson = *Found;
		return true;
	}
	return false;
}

void UXaceEntityMarkerComponent::ClearPlaybackCommands()
{
	RecentPlaybackCommands.Reset();
}

void UXaceEntityMarkerComponent::RecordPlaybackCommand(const FXacePlaybackCommand& Command)
{
	RecentPlaybackCommands.Add(Command);
	while (RecentPlaybackCommands.Num() > 32)
	{
		RecentPlaybackCommands.RemoveAt(0);
	}
}

UXaceDeltaApplicatorComponent::UXaceDeltaApplicatorComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
}

void UXaceDeltaApplicatorComponent::BeginPlay()
{
	Super::BeginPlay();
	SubscribeTransport();
}

void UXaceDeltaApplicatorComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	UnsubscribeTransport();
	Super::EndPlay(EndPlayReason);
}

void UXaceDeltaApplicatorComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	SubscribeTransport();
	GeneratedFrame++;
	if (bCollectFeedback)
	{
		CollectFeedback();
		FlushFeedback();
	}
}

void UXaceDeltaApplicatorComponent::RegisterActorClass(const FString& ActorId, TSubclassOf<AActor> ActorClass)
{
	if (!ActorId.TrimStartAndEnd().IsEmpty() && ActorClass != nullptr)
	{
		ActorRegistry.Add(ActorId.TrimStartAndEnd(), ActorClass);
	}
}

AActor* UXaceDeltaApplicatorComponent::GetEntityActor(int64 EntityId) const
{
	if (AActor* const* Found = EntityActors.Find(EntityId))
	{
		return *Found;
	}
	return nullptr;
}

FString UXaceDeltaApplicatorComponent::AssetBindingStatusReportJson() const
{
	TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetStringField(TEXT("schema"), TEXT("xace.adapter.semantic_binding_status_report.v1"));
	Report->SetStringField(TEXT("engine"), TEXT("unreal"));
	TArray<TSharedPtr<FJsonValue>> Statuses;
	Statuses.Add(MakeShared<FJsonValueString>(TEXT("resolved")));
	Statuses.Add(MakeShared<FJsonValueString>(TEXT("unresolved")));
	Statuses.Add(MakeShared<FJsonValueString>(TEXT("unsupported")));
	Statuses.Add(MakeShared<FJsonValueString>(TEXT("missing")));
	Statuses.Add(MakeShared<FJsonValueString>(TEXT("fallback")));
	Report->SetArrayField(TEXT("statuses"), Statuses);
	TArray<TSharedPtr<FJsonValue>> Records;
	for (const auto& Pair : AssetBindingStatusReport)
	{
		TSharedPtr<FJsonObject> RecordObject;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Pair.Value);
		if (FJsonSerializer::Deserialize(Reader, RecordObject) && RecordObject.IsValid())
		{
			Records.Add(MakeShared<FJsonValueObject>(RecordObject));
		}
	}
	Report->SetArrayField(TEXT("records"), Records);
	return JsonToString(Report);
}

void UXaceDeltaApplicatorComponent::BindTransportNow()
{
	SubscribeTransport();
}

bool UXaceDeltaApplicatorComponent::EnsureTransport()
{
	if (Transport == nullptr && GetOwner() != nullptr)
	{
		Transport = GetOwner()->FindComponentByClass<UXaceTransportComponent>();
	}
	return Transport != nullptr;
}

void UXaceDeltaApplicatorComponent::SubscribeTransport()
{
	if (bTransportSubscribed || !EnsureTransport())
	{
		return;
	}
	Transport->OnHandshakeAccepted.AddDynamic(this, &UXaceDeltaApplicatorComponent::OnHandshakeAccepted);
	Transport->OnTickSnapshot.AddDynamic(this, &UXaceDeltaApplicatorComponent::OnTickSnapshot);
	Transport->OnAdapterSideEffectRollback.AddDynamic(this, &UXaceDeltaApplicatorComponent::OnAdapterSideEffectRollback);
	bTransportSubscribed = true;
}

void UXaceDeltaApplicatorComponent::UnsubscribeTransport()
{
	if (!bTransportSubscribed || Transport == nullptr)
	{
		return;
	}
	Transport->OnHandshakeAccepted.RemoveDynamic(this, &UXaceDeltaApplicatorComponent::OnHandshakeAccepted);
	Transport->OnTickSnapshot.RemoveDynamic(this, &UXaceDeltaApplicatorComponent::OnTickSnapshot);
	Transport->OnAdapterSideEffectRollback.RemoveDynamic(this, &UXaceDeltaApplicatorComponent::OnAdapterSideEffectRollback);
	bTransportSubscribed = false;
}

void UXaceDeltaApplicatorComponent::OnHandshakeAccepted(const FXaceHandshakeAck& Ack)
{
	ApplyEntityList(0, Ack.InitialEntities, true, TArray<int64>());
}

void UXaceDeltaApplicatorComponent::OnTickSnapshot(const FXaceTickSnapshot& Snapshot)
{
	CurrentTick = Snapshot.Tick;
	ApplyEntityList(Snapshot.Tick, Snapshot.Entities, bRemoveMissingSnapshotEntities, Snapshot.DestroyedIds);
	ApplyPlaybackCommands(Snapshot.PlaybackCommands);
	QueueLiveValidationFeedback(Snapshot.Tick, TEXT("tick_snapshot"), Snapshot.Entities.Num() + Snapshot.DestroyedIds.Num());
	FlushFeedback();
}
void UXaceDeltaApplicatorComponent::OnAdapterSideEffectRollback(const FXaceAdapterSideEffectRollback& Rollback)
{
	CurrentTick = Rollback.RestoreTick;
	if (Rollback.bClearFeedbackQueue)
	{
		PendingFeedback.Reset();
	}
	ClearPlaybackSideEffects();
	if (Rollback.bResetAssetBindings)
	{
		AssetBindingState.Reset();
		AssetBindingStatusReport.Reset();
	}
	ApplyEntityList(Rollback.RestoreTick, Rollback.RestoredSnapshot.Entities, true, Rollback.RestoredSnapshot.DestroyedIds);
	OnSideEffectsRolledBack.Broadcast(Rollback);
}

void UXaceDeltaApplicatorComponent::ClearPlaybackSideEffects()
{
	for (UActorComponent* Component : PlaybackSpawnedComponents)
	{
		if (Component != nullptr)
		{
			Component->DestroyComponent();
		}
	}
	PlaybackSpawnedComponents.Reset();

	for (const auto& Pair : EntityActors)
	{
		AActor* Actor = Pair.Value;
		if (Actor == nullptr)
		{
			continue;
		}
		if (UAudioComponent* Audio = Actor->FindComponentByClass<UAudioComponent>())
		{
			Audio->Stop();
		}
		if (USkeletalMeshComponent* Mesh = Actor->FindComponentByClass<USkeletalMeshComponent>())
		{
			Mesh->Stop();
		}
		if (UXaceEntityMarkerComponent* Marker = Actor->FindComponentByClass<UXaceEntityMarkerComponent>())
		{
			Marker->ClearPlaybackCommands();
		}
	}
}

void UXaceDeltaApplicatorComponent::ApplyEntityList(int64 Tick, const TArray<FXaceEntityState>& Entities, bool bRemoveMissing, const TArray<int64>& DestroyedIds)
{
	for (int64 EntityId : DestroyedIds)
	{
		DestroyEntity(EntityId);
	}

	TSet<int64> Seen;
	for (const FXaceEntityState& Entity : Entities)
	{
		if (Entity.EntityId == 0)
		{
			continue;
		}
		Seen.Add(Entity.EntityId);
		UpsertEntity(Entity);
	}

	if (bRemoveMissing)
	{
		TArray<int64> RemoveIds;
		for (const auto& Pair : EntityActors)
		{
			if (!Seen.Contains(Pair.Key))
			{
				RemoveIds.Add(Pair.Key);
			}
		}
		for (int64 EntityId : RemoveIds)
		{
			DestroyEntity(EntityId);
		}
	}

	OnSnapshotApplied.Broadcast(Tick, EntityActors.Num());
}

void UXaceDeltaApplicatorComponent::QueueLiveValidationFeedback(int64 Tick, const FString& MessageType, int32 OperationCount)
{
	if (!bSendLiveValidationFeedback)
	{
		return;
	}
	TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
	Payload->SetNumberField(TEXT("engine_delta_apply_ms"), 0.0);
	Payload->SetNumberField(TEXT("draw_calls"), 0);
	Payload->SetNumberField(TEXT("physics_contacts"), 0);
	Payload->SetNumberField(TEXT("engine_entity_count"), EntityActors.Num());
	Payload->SetNumberField(TEXT("generated_frame"), Tick);
	Payload->SetBoolField(TEXT("xace_live_validation"), true);
	Payload->SetStringField(TEXT("adapter_engine"), TEXT("unreal"));
	Payload->SetStringField(TEXT("message_type"), MessageType);
	Payload->SetNumberField(TEXT("operation_count"), FMath::Max(0, OperationCount));
	Payload->SetNumberField(TEXT("runtime_tick"), Tick);
	EnqueueFeedback(TEXT("PerformanceMetrics"), 0, Payload);
}

void UXaceDeltaApplicatorComponent::ApplyPlaybackCommands(const TArray<FXacePlaybackCommand>& Commands)
{
	for (const FXacePlaybackCommand& Command : Commands)
	{
		AActor* Actor = GetEntityActor(Command.EntityId);
		if (Actor == nullptr)
		{
			RecordAssetBindingStatus(Command, false, TEXT("entity_missing"));
			OnPlaybackCommandApplied.Broadcast(Command, false);
			continue;
		}
		if (UXaceEntityMarkerComponent* Marker = Actor->FindComponentByClass<UXaceEntityMarkerComponent>())
		{
			Marker->RecordPlaybackCommand(Command);
		}
		if (!Command.BindingId.TrimStartAndEnd().IsEmpty())
		{
			AssetBindingState.Add(Command.BindingId.TrimStartAndEnd(), Command.Asset);
		}
		const bool bApplied = TryApplyPlaybackCommand(Actor, Command);
		const FString Reason = bApplied && ShouldUseFallback(Command) ? TEXT("fallback_applied") : (bApplied ? TEXT("applied") : TEXT("playback_resource_missing"));
		RecordAssetBindingStatus(Command, bApplied, Reason);
		OnPlaybackCommandApplied.Broadcast(Command, bApplied);
	}
}

void UXaceDeltaApplicatorComponent::RecordAssetBindingStatus(const FXacePlaybackCommand& Command, bool bApplied, const FString& Reason)
{
	FString BindingId = Command.BindingId.TrimStartAndEnd();
	if (BindingId.IsEmpty())
	{
		BindingId = TEXT("<unbound>");
	}
	const FString Status = SemanticBindingStatus(Command, bApplied);
	TSharedRef<FJsonObject> Record = MakeShared<FJsonObject>();
	Record->SetStringField(TEXT("schema"), TEXT("xace.adapter.semantic_binding_status_record.v1"));
	Record->SetStringField(TEXT("engine"), TEXT("unreal"));
	Record->SetStringField(TEXT("binding_id"), BindingId);
	Record->SetStringField(TEXT("status"), Status);
	Record->SetStringField(TEXT("asset_id"), Command.Asset.Id);
	Record->SetStringField(TEXT("playback_kind"), Command.PlaybackKind);
	Record->SetStringField(TEXT("reason"), Reason);
	const bool bBlocks = Status == TEXT("unresolved") || Status == TEXT("unsupported") || Status == TEXT("missing");
	Record->SetBoolField(TEXT("blocks_runtime"), bBlocks);
	Record->SetBoolField(TEXT("blocks_handoff"), bBlocks);
	AssetBindingStatusReport.Add(BindingId, JsonToString(Record));
}

bool UXaceDeltaApplicatorComponent::TryApplyPlaybackCommand(AActor* Actor, const FXacePlaybackCommand& Command)
{
	if (Actor == nullptr)
	{
		return false;
	}

	const FString Kind = Command.PlaybackKind.ToLower();
	const FString ResourcePath = CommandResourcePath(Command);
	bool bApplied = false;
	if (Kind == TEXT("audio"))
	{
		if (!ResourcePath.IsEmpty())
		{
			if (USoundBase* Sound = LoadObject<USoundBase>(nullptr, *ResourcePath))
			{
				if (UAudioComponent* Audio = UGameplayStatics::SpawnSoundAtLocation(Actor->GetWorld(), Sound, Actor->GetActorLocation()))
				{
					PlaybackSpawnedComponents.Add(Audio);
					bApplied = true;
				}
			}
		}
	}
	else if (Kind == TEXT("animation"))
	{
		if (!ResourcePath.IsEmpty())
		{
			USkeletalMeshComponent* Mesh = Actor->FindComponentByClass<USkeletalMeshComponent>();
			UAnimationAsset* Animation = LoadObject<UAnimationAsset>(nullptr, *ResourcePath);
			if (Mesh != nullptr && Animation != nullptr)
			{
				Mesh->PlayAnimation(Animation, false);
				bApplied = true;
			}
		}
	}
	else if (Kind == TEXT("vfx"))
	{
		if (!ResourcePath.IsEmpty())
		{
			if (UParticleSystem* Particle = LoadObject<UParticleSystem>(nullptr, *ResourcePath))
			{
				UGameplayStatics::SpawnEmitterAtLocation(Actor->GetWorld(), Particle, Actor->GetActorTransform());
				bApplied = true;
			}
		}
	}
	if (bApplied)
	{
		return true;
	}
	return ShouldUseFallback(Command) && ApplyFallbackPlaybackCommand(Actor, Command);
}

bool UXaceDeltaApplicatorComponent::ApplyFallbackPlaybackCommand(AActor* Actor, const FXacePlaybackCommand& Command)
{
	if (Actor == nullptr)
	{
		return false;
	}
	USceneComponent* Root = Actor->GetRootComponent();
	if (Root == nullptr)
	{
		Root = NewObject<USceneComponent>(Actor, TEXT("XaceFallbackRoot"));
		if (Root == nullptr)
		{
			return false;
		}
		Root->RegisterComponent();
		Actor->SetRootComponent(Root);
		Actor->AddInstanceComponent(Root);
	}
	const FName CapsuleName(*FString::Printf(TEXT("XaceFallbackVisual_%d"), PlaybackSpawnedComponents.Num()));
	UCapsuleComponent* Capsule = NewObject<UCapsuleComponent>(Actor, CapsuleName);
	if (Capsule == nullptr)
	{
		return false;
	}
	Capsule->InitCapsuleSize(18.0f, 18.0f);
	Capsule->SetRelativeLocation(FVector(0.0f, 0.0f, 120.0f));
	Capsule->SetHiddenInGame(false);
	Capsule->SetVisibility(true);
	Capsule->ComponentTags.Add(FName(TEXT("xace_runtime_fallback")));
	Capsule->ComponentTags.Add(FName(*FallbackKind(Command)));
	Capsule->SetupAttachment(Root);
	Capsule->RegisterComponent();
	Actor->AddInstanceComponent(Capsule);
	PlaybackSpawnedComponents.Add(Capsule);

	const FName LabelName(*FString::Printf(TEXT("XaceFallbackLabel_%d"), PlaybackSpawnedComponents.Num()));
	UTextRenderComponent* Label = NewObject<UTextRenderComponent>(Actor, LabelName);
	if (Label != nullptr)
	{
		Label->SetText(FText::FromString(FallbackLabel(Command)));
		Label->SetHorizontalAlignment(EHTA_Center);
		Label->SetWorldSize(18.0f);
		Label->SetRelativeLocation(FVector(0.0f, 0.0f, 150.0f));
		Label->ComponentTags.Add(FName(TEXT("xace_runtime_fallback")));
		Label->SetupAttachment(Root);
		Label->RegisterComponent();
		Actor->AddInstanceComponent(Label);
		PlaybackSpawnedComponents.Add(Label);
	}
	return true;
}

void UXaceDeltaApplicatorComponent::UpsertEntity(const FXaceEntityState& State)
{
	AActor* Actor = GetEntityActor(State.EntityId);
	if (Actor == nullptr)
	{
		Actor = SpawnActorForEntity(State);
		if (Actor == nullptr)
		{
			return;
		}
		EntityActors.Add(State.EntityId, Actor);
	}

	UXaceEntityMarkerComponent* Marker = Actor->FindComponentByClass<UXaceEntityMarkerComponent>();
	if (Marker == nullptr)
	{
		Marker = NewObject<UXaceEntityMarkerComponent>(Actor);
		Marker->RegisterComponent();
		Actor->AddInstanceComponent(Marker);
	}
	Marker->EntityId = State.EntityId;
	Marker->ActorId = ResolveActorId(State);
	Marker->SetComponents(State.Components);
	ApplyComponents(Actor, Marker, State.Components);
}

void UXaceDeltaApplicatorComponent::DestroyEntity(int64 EntityId)
{
	AActor* Actor = GetEntityActor(EntityId);
	if (Actor != nullptr)
	{
		Actor->Destroy();
	}
	EntityActors.Remove(EntityId);
}

AActor* UXaceDeltaApplicatorComponent::SpawnActorForEntity(const FXaceEntityState& State)
{
	UWorld* World = GetWorld();
	if (World == nullptr)
	{
		return nullptr;
	}

	const FString ActorId = ResolveActorId(State);
	TSubclassOf<AActor> ClassToSpawn = AActor::StaticClass();
	if (const TSubclassOf<AActor>* Registered = ActorRegistry.Find(ActorId))
	{
		ClassToSpawn = *Registered;
	}
	else if (FallbackActorClass != nullptr)
	{
		ClassToSpawn = FallbackActorClass;
	}

	AActor* Actor = World->SpawnActor<AActor>(ClassToSpawn, FTransform::Identity);
	if (Actor == nullptr)
	{
		return nullptr;
	}
	const FString DebugName = FString::Printf(TEXT("XACE_%llu_%s"), State.EntityId, *ActorId);
#if WITH_EDITOR
	Actor->SetActorLabel(DebugName);
#endif
	Actor->Tags.AddUnique(FName(*DebugName));

	if (bCreateDebugActors && Actor->GetRootComponent() == nullptr)
	{
		USceneComponent* Root = NewObject<USceneComponent>(Actor, TEXT("XaceRoot"));
		Root->RegisterComponent();
		Actor->SetRootComponent(Root);

		UCapsuleComponent* Capsule = NewObject<UCapsuleComponent>(Actor, TEXT("XaceDebugCapsule"));
		Capsule->InitCapsuleSize(35.0f, 90.0f);
		Capsule->SetupAttachment(Root);
		Capsule->RegisterComponent();

		UTextRenderComponent* Label = NewObject<UTextRenderComponent>(Actor, TEXT("XaceLabel"));
		Label->SetHorizontalAlignment(EHTA_Center);
		Label->SetWorldSize(18.0f);
		Label->SetRelativeLocation(FVector(0.0f, 0.0f, 120.0f));
		Label->SetupAttachment(Root);
		Label->RegisterComponent();
	}
	return Actor;
}

void UXaceDeltaApplicatorComponent::ApplyComponents(AActor* Actor, UXaceEntityMarkerComponent* Marker, const TMap<int32, FString>& Components)
{
	if (Actor == nullptr || Marker == nullptr)
	{
		return;
	}

	if (const FString* TransformJson = Components.Find(TransformComponentType))
	{
		ApplyTransform(Actor, *TransformJson);
	}
	if (const FString* InputJson = Components.Find(InputComponentType))
	{
		Marker->ControllerId = int32(GetNumber(ParseObject(*InputJson), TEXT("controller_id"), float(Marker->ControllerId)));
	}

	const FString ActorId = ResolveActorId(Marker->ActorId, Components);
	if (UTextRenderComponent* Label = Actor->FindComponentByClass<UTextRenderComponent>())
	{
		FString Text = ActorId.IsEmpty() ? FString::Printf(TEXT("%llu"), Marker->EntityId) : ActorId;
		if (const FString* HealthJson = Components.Find(HealthComponentType))
		{
			const TSharedPtr<FJsonObject> Health = ParseObject(*HealthJson);
			const float Current = GetNumber(Health, TEXT("current"), 0.0f);
			const float Max = GetNumber(Health, TEXT("max"), 0.0f);
			Text += Max > 0.0f ? FString::Printf(TEXT(" %.0f/%.0f"), Current, Max) : FString::Printf(TEXT(" %.0f"), Current);
		}
		Label->SetText(FText::FromString(Text));
	}
}

void UXaceDeltaApplicatorComponent::CollectFeedback()
{
	for (const auto& Pair : EntityActors)
	{
		AActor* Actor = Pair.Value;
		if (Actor == nullptr)
		{
			continue;
		}
		if (UPrimitiveComponent* Primitive = Actor->FindComponentByClass<UPrimitiveComponent>())
		{
			if (Primitive->IsSimulatingPhysics() && Primitive->RigidBodyIsAwake() == false)
			{
				TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
				Payload->SetNumberField(TEXT("entity_id"), Pair.Key);
				Payload->SetNumberField(TEXT("generated_frame"), GeneratedFrame);
				Payload->SetStringField(TEXT("final_position_json"), VectorJson(Actor->GetActorLocation()));
				Payload->SetStringField(TEXT("final_rotation_json"), RotatorJson(Actor->GetActorQuat()));
				EnqueueFeedback(TEXT("PhysicsSettled"), Pair.Key, Payload);
			}
		}
	}
}

void UXaceDeltaApplicatorComponent::FlushFeedback()
{
	if (PendingFeedback.IsEmpty())
	{
		return;
	}
	for (const TSharedPtr<FJsonObject>& Feedback : PendingFeedback)
	{
		if (Feedback.IsValid())
		{
			OnFeedbackQueued.Broadcast(JsonToString(Feedback.ToSharedRef()));
		}
	}
	if (bSendFeedbackToRuntime && Transport != nullptr)
	{
		Transport->SendFeedbackPayload(CurrentTick, PendingFeedback);
	}
	PendingFeedback.Reset();
}

void UXaceDeltaApplicatorComponent::EnqueueFeedback(const FString& FeedbackType, int64 EntityId, const TSharedRef<FJsonObject>& Payload)
{
	TSharedRef<FJsonObject> Feedback = MakeShared<FJsonObject>();
	Feedback->SetStringField(TEXT("feedback_type"), FeedbackType);
	Feedback->SetNumberField(TEXT("entity_id"), EntityId);
	Feedback->SetNumberField(TEXT("generated_frame"), GeneratedFrame);
	Feedback->SetStringField(TEXT("payload_json"), JsonToString(Payload));
	PendingFeedback.Add(Feedback);
}

FString UXaceDeltaApplicatorComponent::ResolveActorId(const FXaceEntityState& State)
{
	if (!State.ActorId.TrimStartAndEnd().IsEmpty())
	{
		return State.ActorId.TrimStartAndEnd();
	}
	return ResolveActorId(TEXT(""), State.Components);
}

FString UXaceDeltaApplicatorComponent::ResolveActorId(const FString& Fallback, const TMap<int32, FString>& Components)
{
	if (const FString* IdentityJson = Components.Find(IdentityComponentType))
	{
		const TSharedPtr<FJsonObject> Identity = ParseObject(*IdentityJson);
		const FString Name = GetString(Identity, TEXT("entity_name"), TEXT(""));
		if (!Name.TrimStartAndEnd().IsEmpty())
		{
			return Name.TrimStartAndEnd();
		}
		const FString Type = GetString(Identity, TEXT("entity_type"), TEXT(""));
		if (!Type.TrimStartAndEnd().IsEmpty())
		{
			return Type.TrimStartAndEnd();
		}
	}
	return Fallback;
}

void UXaceDeltaApplicatorComponent::ApplyTransform(AActor* Actor, const FString& Json)
{
	const TSharedPtr<FJsonObject> Data = ParseObject(Json);
	const TSharedPtr<FJsonObject> Position = GetObject(Data, TEXT("position"));
	const TSharedPtr<FJsonObject> Rotation = GetObject(Data, TEXT("rotation"));
	const TSharedPtr<FJsonObject> Scale = GetObject(Data, TEXT("scale"));
	if (Position.IsValid())
	{
		Actor->SetActorLocation(FVector(GetNumber(Position, TEXT("x"), 0.0f), GetNumber(Position, TEXT("y"), 0.0f), GetNumber(Position, TEXT("z"), 0.0f)));
	}
	else if (HasAnyField(Data, { TEXT("position_x"), TEXT("position_y"), TEXT("position_z") }))
	{
		const FVector Current = Actor->GetActorLocation();
		Actor->SetActorLocation(FVector(
			GetNumber(Data, TEXT("position_x"), Current.X),
			GetNumber(Data, TEXT("position_y"), Current.Y),
			GetNumber(Data, TEXT("position_z"), Current.Z)));
	}
	if (Rotation.IsValid())
	{
		Actor->SetActorRotation(FQuat(GetNumber(Rotation, TEXT("x"), 0.0f), GetNumber(Rotation, TEXT("y"), 0.0f), GetNumber(Rotation, TEXT("z"), 0.0f), GetNumber(Rotation, TEXT("w"), 1.0f)));
	}
	else if (HasAnyField(Data, { TEXT("rotation_x"), TEXT("rotation_y"), TEXT("rotation_z"), TEXT("rotation_w") }))
	{
		const FQuat Current = Actor->GetActorQuat();
		Actor->SetActorRotation(FQuat(
			GetNumber(Data, TEXT("rotation_x"), Current.X),
			GetNumber(Data, TEXT("rotation_y"), Current.Y),
			GetNumber(Data, TEXT("rotation_z"), Current.Z),
			GetNumber(Data, TEXT("rotation_w"), Current.W)));
	}
	if (Scale.IsValid())
	{
		Actor->SetActorScale3D(FVector(GetNumber(Scale, TEXT("x"), 1.0f), GetNumber(Scale, TEXT("y"), 1.0f), GetNumber(Scale, TEXT("z"), 1.0f)));
	}
	else if (HasAnyField(Data, { TEXT("scale_x"), TEXT("scale_y"), TEXT("scale_z") }))
	{
		const FVector Current = Actor->GetActorScale3D();
		Actor->SetActorScale3D(FVector(
			GetNumber(Data, TEXT("scale_x"), Current.X),
			GetNumber(Data, TEXT("scale_y"), Current.Y),
			GetNumber(Data, TEXT("scale_z"), Current.Z)));
	}
}

TSharedPtr<FJsonObject> UXaceDeltaApplicatorComponent::ParseObject(const FString& Json)
{
	TSharedPtr<FJsonObject> Object;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	FJsonSerializer::Deserialize(Reader, Object);
	return Object;
}

TSharedPtr<FJsonObject> UXaceDeltaApplicatorComponent::GetObject(const TSharedPtr<FJsonObject>& Object, const FString& Field)
{
	const TSharedPtr<FJsonObject>* Found = nullptr;
	return Object.IsValid() && Object->TryGetObjectField(Field, Found) && Found != nullptr ? *Found : nullptr;
}

FString UXaceDeltaApplicatorComponent::GetString(const TSharedPtr<FJsonObject>& Object, const FString& Field, const FString& Fallback)
{
	FString Out;
	return Object.IsValid() && Object->TryGetStringField(Field, Out) ? Out : Fallback;
}

bool UXaceDeltaApplicatorComponent::HasAnyField(const TSharedPtr<FJsonObject>& Object, std::initializer_list<const TCHAR*> Fields)
{
	if (!Object.IsValid())
	{
		return false;
	}
	for (const TCHAR* Field : Fields)
	{
		if (Field != nullptr && Object->HasField(Field))
		{
			return true;
		}
	}
	return false;
}

FString UXaceDeltaApplicatorComponent::GetCommandParameter(const FXacePlaybackCommand& Command, const FString& Key, const FString& Fallback)
{
	if (const FString* Found = Command.Parameters.Find(Key))
	{
		return *Found;
	}
	return Fallback;
}

FString UXaceDeltaApplicatorComponent::SemanticBindingStatus(const FXacePlaybackCommand& Command, bool bApplied)
{
	const FString Declared = DeclaredBindingStatus(Command);
	if (!Declared.IsEmpty())
	{
		return Declared;
	}
	if (ShouldUseFallback(Command))
	{
		return TEXT("fallback");
	}
	if (bApplied)
	{
		return TEXT("resolved");
	}
	const FString Kind = Command.PlaybackKind.ToLower();
	if (Kind != TEXT("audio") && Kind != TEXT("animation") && Kind != TEXT("vfx"))
	{
		return TEXT("unsupported");
	}
	return CommandResourcePath(Command).IsEmpty() ? TEXT("unresolved") : TEXT("missing");
}

FString UXaceDeltaApplicatorComponent::DeclaredBindingStatus(const FXacePlaybackCommand& Command)
{
	const FString Declared = GetCommandParameter(Command, TEXT("xace_binding_status"), TEXT("")).ToLower();
	if (Declared == TEXT("resolved") || Declared == TEXT("unresolved") || Declared == TEXT("unsupported") || Declared == TEXT("missing") || Declared == TEXT("fallback"))
	{
		return Declared;
	}
	return TEXT("");
}

bool UXaceDeltaApplicatorComponent::ShouldUseFallback(const FXacePlaybackCommand& Command)
{
	if (DeclaredBindingStatus(Command) == TEXT("fallback"))
	{
		return true;
	}
	if (TruthyCommandParameter(Command, TEXT("xace_runtime_fallback")) || TruthyCommandParameter(Command, TEXT("xace_fallback_visible")) || TruthyCommandParameter(Command, TEXT("allow_fallback")))
	{
		return true;
	}
	const FString Status = Command.Asset.Status.ToLower().TrimStartAndEnd();
	return Status == TEXT("missing") || Status == TEXT("placeholder");
}

bool UXaceDeltaApplicatorComponent::TruthyCommandParameter(const FXacePlaybackCommand& Command, const FString& Key)
{
	const FString Value = GetCommandParameter(Command, Key, TEXT("")).ToLower().TrimStartAndEnd();
	return Value == TEXT("true") || Value == TEXT("1") || Value == TEXT("yes") || Value == TEXT("fallback");
}

FString UXaceDeltaApplicatorComponent::FallbackKind(const FXacePlaybackCommand& Command)
{
	const FString Explicit = GetCommandParameter(Command, TEXT("xace_fallback_kind"), TEXT("")).ToLower().TrimStartAndEnd();
	if (!Explicit.IsEmpty())
	{
		return Explicit;
	}
	const FString Kind = Command.PlaybackKind.ToLower().TrimStartAndEnd();
	const FString AssetType = Command.Asset.AssetType.ToLower().TrimStartAndEnd();
	if (Kind == TEXT("animation") || AssetType.Contains(TEXT("animation")))
	{
		return TEXT("visible_animation_marker");
	}
	if (Kind == TEXT("audio") || AssetType.Contains(TEXT("audio")))
	{
		return TEXT("visible_audio_pulse");
	}
	if (Kind == TEXT("vfx") || AssetType == TEXT("particle"))
	{
		return TEXT("visible_vfx_marker");
	}
	if (Kind == TEXT("mesh") || AssetType == TEXT("mesh"))
	{
		return TEXT("visible_mesh_proxy");
	}
	if (Kind == TEXT("prefab") || AssetType == TEXT("prefab"))
	{
		return TEXT("visible_prefab_proxy");
	}
	return TEXT("visible_asset_proxy");
}

FString UXaceDeltaApplicatorComponent::FallbackLabel(const FXacePlaybackCommand& Command)
{
	const FString Explicit = GetCommandParameter(Command, TEXT("xace_fallback_label"), TEXT("")).TrimStartAndEnd();
	if (!Explicit.IsEmpty())
	{
		return Explicit;
	}
	return FString::Printf(TEXT("XACE fallback\n%s\n%s"), *FallbackKind(Command).Replace(TEXT("visible_"), TEXT("")), *Command.Asset.Id);
}

FString UXaceDeltaApplicatorComponent::CommandResourcePath(const FXacePlaybackCommand& Command)
{
	FString Path = GetCommandParameter(Command, TEXT("resource_path"), TEXT(""));
	if (Path.IsEmpty())
	{
		Path = GetCommandParameter(Command, TEXT("asset_path"), TEXT(""));
	}
	if (Path.IsEmpty())
	{
		Path = GetCommandParameter(Command, TEXT("path"), TEXT(""));
	}
	if (Path.IsEmpty() && (Command.Asset.Id.StartsWith(TEXT("/Game/")) || Command.Asset.Id.StartsWith(TEXT("Blueprint'")) || Command.Asset.Id.StartsWith(TEXT("SoundWave'"))))
	{
		Path = Command.Asset.Id;
	}
	return Path.TrimStartAndEnd();
}

float UXaceDeltaApplicatorComponent::GetNumber(const TSharedPtr<FJsonObject>& Object, const FString& Field, float Fallback)
{
	double Out = 0.0;
	return Object.IsValid() && Object->TryGetNumberField(Field, Out) ? float(Out) : Fallback;
}

FString UXaceDeltaApplicatorComponent::VectorJson(const FVector& Value)
{
	return FString::Printf(TEXT("{\"x\":%.9g,\"y\":%.9g,\"z\":%.9g}"), Value.X, Value.Y, Value.Z);
}

FString UXaceDeltaApplicatorComponent::RotatorJson(const FQuat& Value)
{
	return FString::Printf(TEXT("{\"x\":%.9g,\"y\":%.9g,\"z\":%.9g,\"w\":%.9g}"), Value.X, Value.Y, Value.Z, Value.W);
}

FString UXaceDeltaApplicatorComponent::JsonToString(const TSharedRef<FJsonObject>& Object)
{
	FString Out;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Object, Writer);
	return Out;
}
