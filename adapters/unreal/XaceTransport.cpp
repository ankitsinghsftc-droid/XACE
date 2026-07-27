#include "XaceTransport.h"

#include "Common/TcpSocketBuilder.h"
#include "HAL/PlatformTime.h"
#include "Interfaces/IPv4/IPv4Address.h"
#include "Misc/EngineVersion.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SocketSubsystem.h"
#include "Sockets.h"

namespace
{
	constexpr uint32 XaceProtocolVersion = 1;
	constexpr int32 XaceMaxFrameBytes = 4 * 1024 * 1024;

	uint32 ReadLe32(const uint8* Bytes)
	{
		return uint32(Bytes[0]) | (uint32(Bytes[1]) << 8) | (uint32(Bytes[2]) << 16) | (uint32(Bytes[3]) << 24);
	}

	void WriteLe32(uint8* Bytes, uint32 Value)
	{
		Bytes[0] = uint8(Value & 0xff);
		Bytes[1] = uint8((Value >> 8) & 0xff);
		Bytes[2] = uint8((Value >> 16) & 0xff);
		Bytes[3] = uint8((Value >> 24) & 0xff);
	}

	int64 JsonInt(const TSharedPtr<FJsonObject>& Object, const FString& Field, int64 DefaultValue = 0)
	{
		double Number = 0.0;
		if (!Object.IsValid() || !Object->TryGetNumberField(Field, Number))
		{
			return DefaultValue;
		}
		return int64(FMath::Max(0.0, Number));
	}

	FString JsonString(const TSharedPtr<FJsonObject>& Object, const FString& Field, const FString& DefaultValue = TEXT(""))
	{
		FString Out;
		return Object.IsValid() && Object->TryGetStringField(Field, Out) ? Out : DefaultValue;
	}
}

TSharedRef<FJsonObject> FXaceInputAction::ToJson() const
{
	TSharedRef<FJsonObject> Object = MakeShared<FJsonObject>();
	Object->SetStringField(TEXT("action"), Action.Left(64));
	Object->SetNumberField(TEXT("value"), FMath::Clamp(FMath::IsFinite(Value) ? Value : 0.0f, -1.0f, 1.0f));
	Object->SetNumberField(TEXT("secondary_value"), FMath::Clamp(FMath::IsFinite(SecondaryValue) ? SecondaryValue : 0.0f, -1.0f, 1.0f));
	Object->SetStringField(TEXT("kind"), Kind.IsEmpty() ? TEXT("custom") : Kind.Left(32));
	Object->SetStringField(TEXT("phase"), Phase.IsEmpty() ? TEXT("performed") : Phase.Left(32));
	return Object;
}

TSharedRef<FJsonObject> FXaceInputPacket::ToJson() const
{
	TSharedRef<FJsonObject> Object = MakeShared<FJsonObject>();
	Object->SetStringField(TEXT("msg_type"), TEXT("input_packet"));
	Object->SetNumberField(TEXT("peer_id"), FMath::Max<int64>(1, PeerId));
	Object->SetNumberField(TEXT("tick"), Tick);
	Object->SetNumberField(TEXT("player_id"), PlayerId);
	Object->SetNumberField(TEXT("sequence_id"), FMath::Max<int64>(1, SequenceId));
	Object->SetNumberField(TEXT("timestamp_ms"), TimestampMs);
	Object->SetStringField(TEXT("device_id"), DeviceId.Left(64));
	Object->SetBoolField(TEXT("predicted"), bPredicted);

	TArray<TSharedPtr<FJsonValue>> ActionValues;
	TArray<FXaceInputAction> SortedActions = Actions;
	SortedActions.Sort([](const FXaceInputAction& Left, const FXaceInputAction& Right) {
		return Left.Action < Right.Action;
	});
	for (const FXaceInputAction& Action : SortedActions)
	{
		TSharedPtr<FJsonObject> ActionObject = Action.ToJson();
		ActionValues.Add(MakeShared<FJsonValueObject>(ActionObject));
	}
	Object->SetArrayField(TEXT("actions"), ActionValues);
	return Object;
}

UXaceTransportComponent::UXaceTransportComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	Capabilities = { TEXT("length_prefixed_json"), TEXT("tick_snapshot_v1"), TEXT("input_packet_v1"), TEXT("feedback_payload_v1"), TEXT("unreal") };
}

void UXaceTransportComponent::BeginPlay()
{
	Super::BeginPlay();
	ReconnectDelay = FMath::Max(0.1f, InitialReconnectDelaySeconds);
	if (bAutoConnect)
	{
		ConnectToRuntime();
	}
}

void UXaceTransportComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	bStopping = true;
	DisconnectFromRuntime(TEXT("component ended"));
	Super::EndPlay(EndPlayReason);
}

void UXaceTransportComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	PumpOnce(DeltaTime);
}

void UXaceTransportComponent::ConfigureConnection(const FString& InHost, int32 InPort, const FString& InCgsHash)
{
	Host = InHost.TrimStartAndEnd().IsEmpty() ? TEXT("127.0.0.1") : InHost.TrimStartAndEnd();
	Port = FMath::Clamp(InPort, 1, 65535);
	CgsHash = InCgsHash.TrimStartAndEnd();
}

void UXaceTransportComponent::PumpOnce(float DeltaTime)
{
	if (IsConnected())
	{
		PollSocket();
		FlushOutbound();
		return;
	}
	if (!bStopping && bReconnect)
	{
		ReconnectTimer += DeltaTime;
		if (ReconnectTimer >= ReconnectDelay)
		{
			ReconnectTimer = 0.0f;
			ReconnectDelay = FMath::Min(FMath::Max(0.1f, ReconnectDelay * 2.0f), MaxReconnectDelaySeconds);
			ConnectToRuntime();
		}
	}
}

bool UXaceTransportComponent::ConnectToRuntime()
{
	if (IsConnected())
	{
		return true;
	}

	CloseSocket();
	bStopping = false;

	FIPv4Address Address;
	if (!FIPv4Address::Parse(Host, Address))
	{
		Fail(TEXT("invalid runtime host: ") + Host);
		return false;
	}

	TSharedRef<FInternetAddr> Endpoint = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->CreateInternetAddr();
	Endpoint->SetIp(Address.Value);
	Endpoint->SetPort(FMath::Clamp(Port, 1, 65535));

	Socket = FTcpSocketBuilder(TEXT("XACE Runtime"))
		.AsReusable()
		.WithReceiveBufferSize(256 * 1024)
		.WithSendBufferSize(256 * 1024);

	if (Socket == nullptr || !Socket->Connect(*Endpoint))
	{
		Fail(FString::Printf(TEXT("connect failed to %s:%d"), *Host, Port));
		CloseSocket();
		return false;
	}
	Socket->SetNoDelay(true);

	bConnected = true;
	bHandshakeComplete = false;
	Socket->SetNonBlocking(true);
	ReconnectDelay = FMath::Max(0.1f, InitialReconnectDelaySeconds);
	ReconnectTimer = 0.0f;
	SendHandshake();
	OnConnectionChanged.Broadcast(true);
	return true;
}

void UXaceTransportComponent::DisconnectFromRuntime(const FString& Reason)
{
	CloseSocket();
	if (!Reason.IsEmpty())
	{
		UE_LOG(LogTemp, Log, TEXT("XACE Unreal transport disconnected: %s"), *Reason);
	}
	OnConnectionChanged.Broadcast(false);
}

bool UXaceTransportComponent::SendInputPacket(const FXaceInputPacket& Packet)
{
	FXaceInputPacket Copy = Packet;
	if (Copy.SequenceId == 0)
	{
		Copy.SequenceId = NextSequenceId();
	}
	return SendJsonObject(Copy.ToJson());
}

bool UXaceTransportComponent::SendJsonObject(const TSharedRef<FJsonObject>& Message)
{
	const FString Json = JsonToString(Message);
	if (Json.IsEmpty())
	{
		return false;
	}
	OutboundJson.Enqueue(Json);
	Stats.QueuedMessages++;
	return IsConnected();
}

bool UXaceTransportComponent::SendFeedbackPayload(int64 Tick, const TArray<TSharedPtr<FJsonObject>>& Messages)
{
	TSharedRef<FJsonObject> Batch = MakeShared<FJsonObject>();
	Batch->SetStringField(TEXT("msg_type"), TEXT("feedback_payload"));
	Batch->SetNumberField(TEXT("tick"), Tick);

	TArray<TSharedPtr<FJsonValue>> Values;
	for (const TSharedPtr<FJsonObject>& Message : Messages)
	{
		if (Message.IsValid())
		{
			Values.Add(MakeShared<FJsonValueObject>(Message));
		}
	}
	Batch->SetArrayField(TEXT("messages"), Values);
	return SendJsonObject(Batch);
}

void UXaceTransportComponent::PollSocket()
{
	uint32 PendingBytes = 0;
	while (Socket != nullptr && Socket->HasPendingData(PendingBytes))
	{
		TArray<uint8> Chunk;
		Chunk.SetNumUninitialized(FMath::Min<int32>(PendingBytes, 64 * 1024));
		int32 BytesRead = 0;
		if (!Socket->Recv(Chunk.GetData(), Chunk.Num(), BytesRead) || BytesRead <= 0)
		{
			Fail(TEXT("runtime socket read failed"));
			CloseSocket();
			return;
		}
		Chunk.SetNum(BytesRead);
		ReceiveBuffer.Append(Chunk);
		Stats.BytesReceived += int64(BytesRead);

		TArray<TSharedPtr<FJsonObject>> Messages;
		FString Error;
		if (!DecodeFrames(ReceiveBuffer, Messages, Error))
		{
			Fail(Error);
			CloseSocket();
			return;
		}
		for (const TSharedPtr<FJsonObject>& Message : Messages)
		{
			Stats.FramesReceived++;
			DispatchMessage(Message);
		}
	}
}

void UXaceTransportComponent::FlushOutbound()
{
	FString Json;
	while (IsConnected() && OutboundJson.Dequeue(Json))
	{
		if (!WriteFrame(Json))
		{
			CloseSocket();
			return;
		}
		Stats.FramesSent++;
		Stats.QueuedMessages = FMath::Max(0, Stats.QueuedMessages - 1);
	}
}

void UXaceTransportComponent::SendHandshake()
{
	TSharedRef<FJsonObject> Hello = MakeShared<FJsonObject>();
	Hello->SetStringField(TEXT("msg_type"), TEXT("handshake"));
	Hello->SetNumberField(TEXT("protocol_version"), XaceProtocolVersion);
	Hello->SetStringField(TEXT("engine_name"), PortableText(EngineName, 96, TEXT("Unreal")));
	Hello->SetStringField(TEXT("engine_version"), PortableText(FEngineVersion::Current().ToString(), 64, TEXT("Unreal")));
	Hello->SetStringField(TEXT("adapter_version"), PortableText(AdapterVersion, 64, TEXT("0.1.0")));
	Hello->SetStringField(TEXT("cgs_hash"), PortableText(CgsHash, 128, TEXT("")));

	TArray<TSharedPtr<FJsonValue>> CapabilityValues;
	TArray<FString> SortedCapabilities = Capabilities;
	SortedCapabilities.Sort();
	for (const FString& Capability : SortedCapabilities)
	{
		const FString Clean = PortableText(Capability, 64, TEXT(""));
		if (!Clean.IsEmpty())
		{
			CapabilityValues.Add(MakeShared<FJsonValueString>(Clean));
		}
	}
	Hello->SetArrayField(TEXT("capabilities"), CapabilityValues);
	WriteFrame(JsonToString(Hello));
	Stats.FramesSent++;
}

void UXaceTransportComponent::DispatchMessage(const TSharedPtr<FJsonObject>& Message)
{
	if (!Message.IsValid())
	{
		Fail(TEXT("received null JSON message"));
		return;
	}

	const FString MsgType = JsonString(Message, TEXT("msg_type"));
	if (MsgType == TEXT("handshake_ack"))
	{
		DispatchHandshakeAck(Message);
	}
	else if (MsgType == TEXT("tick_snapshot"))
	{
		const FXaceTickSnapshot Snapshot = ParseTickSnapshot(Message);
		OnTickSnapshot.Broadcast(Snapshot);
		OnJsonMessage.Broadcast(Message);
	}
	else if (MsgType == TEXT("disconnect"))
	{
		DisconnectFromRuntime(JsonString(Message, TEXT("reason"), TEXT("runtime disconnect")));
	}
	else if (MsgType == TEXT("error"))
	{
		Fail(JsonString(Message, TEXT("message"), TEXT("runtime error")));
		OnJsonMessage.Broadcast(Message);
	}
	else
	{
		OnJsonMessage.Broadcast(Message);
	}
}

void UXaceTransportComponent::DispatchHandshakeAck(const TSharedPtr<FJsonObject>& Message)
{
	const FXaceHandshakeAck Ack = ParseHandshakeAck(Message);
	if (Ack.bAccepted)
	{
		bHandshakeComplete = true;
		OnHandshakeAccepted.Broadcast(Ack);
		OnJsonMessage.Broadcast(Message);
	}
	else
	{
		bHandshakeComplete = false;
		const FString Reason = Ack.RejectReason.IsEmpty() ? TEXT("handshake rejected") : Ack.RejectReason;
		OnHandshakeRejected.Broadcast(Reason);
		DisconnectFromRuntime(Reason);
	}
}

bool UXaceTransportComponent::WriteFrame(const FString& Json)
{
	FTCHARToUTF8 Converter(*Json);
	const int32 PayloadLen = Converter.Length();
	if (PayloadLen <= 0 || PayloadLen > XaceMaxFrameBytes)
	{
		Fail(FString::Printf(TEXT("invalid outbound frame length: %d"), PayloadLen));
		return false;
	}

	TArray<uint8> Frame;
	Frame.SetNumUninitialized(PayloadLen + 4);
	WriteLe32(Frame.GetData(), uint32(PayloadLen));
	FMemory::Memcpy(Frame.GetData() + 4, Converter.Get(), PayloadLen);

	int32 BytesSent = 0;
	if (Socket == nullptr || !Socket->Send(Frame.GetData(), Frame.Num(), BytesSent) || BytesSent != Frame.Num())
	{
		Fail(TEXT("socket send failed"));
		return false;
	}
	Stats.BytesSent += int64(BytesSent);
	return true;
}

void UXaceTransportComponent::Fail(const FString& Message)
{
	LastError = Message;
	Stats.ProtocolErrors++;
	UE_LOG(LogTemp, Warning, TEXT("XACE Unreal transport: %s"), *Message);
	OnProtocolError.Broadcast(Message);
}

void UXaceTransportComponent::CloseSocket()
{
	if (Socket != nullptr)
	{
		Socket->Close();
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(Socket);
		Socket = nullptr;
	}
	bConnected = false;
	bHandshakeComplete = false;
	ReceiveBuffer.Reset();
}

bool UXaceTransportComponent::DecodeFrames(TArray<uint8>& Buffer, TArray<TSharedPtr<FJsonObject>>& OutMessages, FString& OutError)
{
	int32 Offset = 0;
	while (Buffer.Num() - Offset >= 4)
	{
		const uint32 PayloadLen = ReadLe32(Buffer.GetData() + Offset);
		if (PayloadLen == 0 || PayloadLen > XaceMaxFrameBytes)
		{
			OutError = FString::Printf(TEXT("invalid inbound frame length: %u"), PayloadLen);
			return false;
		}
		if (Buffer.Num() - Offset - 4 < int32(PayloadLen))
		{
			break;
		}

		FUTF8ToTCHAR Converted(reinterpret_cast<const ANSICHAR*>(Buffer.GetData() + Offset + 4), int32(PayloadLen));
		const FString Json(Converted.Length(), Converted.Get());
		TSharedPtr<FJsonObject> Object;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
		if (!FJsonSerializer::Deserialize(Reader, Object) || !Object.IsValid())
		{
			OutError = TEXT("inbound frame payload is not a JSON object");
			return false;
		}
		OutMessages.Add(Object);
		Offset += 4 + int32(PayloadLen);
	}

	if (Offset > 0)
	{
		Buffer.RemoveAt(0, Offset, EAllowShrinking::No);
	}
	return true;
}

FXaceEntityState UXaceTransportComponent::ParseEntityState(const TSharedPtr<FJsonObject>& Object)
{
	FXaceEntityState State;
	if (!Object.IsValid())
	{
		return State;
	}
	State.EntityId = JsonInt(Object, TEXT("id"));
	State.ActorId = JsonString(Object, TEXT("actor_id"));

	const TSharedPtr<FJsonObject>* Components = nullptr;
	if (Object->TryGetObjectField(TEXT("components"), Components) && Components != nullptr && Components->IsValid())
	{
		for (const auto& Pair : (*Components)->Values)
		{
			int32 TypeId = FCString::Atoi(*Pair.Key);
			if (TypeId > 0)
			{
				State.Components.Add(TypeId, Pair.Value.IsValid() ? Pair.Value->AsString() : FString());
			}
		}
	}
	return State;
}

FXaceAssetReference UXaceTransportComponent::ParseAssetReference(const TSharedPtr<FJsonObject>& Object)
{
	FXaceAssetReference Asset;
	if (!Object.IsValid())
	{
		return Asset;
	}
	Object->TryGetStringField(TEXT("id"), Asset.Id);
	Object->TryGetStringField(TEXT("asset_type"), Asset.AssetType);
	Object->TryGetStringField(TEXT("status"), Asset.Status);
	return Asset;
}

FXacePlaybackCommand UXaceTransportComponent::ParsePlaybackCommand(const TSharedPtr<FJsonObject>& Object)
{
	FXacePlaybackCommand Command;
	if (!Object.IsValid())
	{
		return Command;
	}
	Object->TryGetStringField(TEXT("binding_id"), Command.BindingId);
	Object->TryGetStringField(TEXT("event_name"), Command.EventName);
	Object->TryGetStringField(TEXT("playback_kind"), Command.PlaybackKind);
	double EntityId = 0.0;
	if (Object->TryGetNumberField(TEXT("entity_id"), EntityId))
	{
		Command.EntityId = int64(FMath::Max(0.0, EntityId));
	}
	Object->TryGetStringField(TEXT("semantic_action"), Command.SemanticAction);
	double Priority = 0.0;
	if (Object->TryGetNumberField(TEXT("priority"), Priority))
	{
		Command.Priority = int32(Priority);
	}
	const TSharedPtr<FJsonObject>* AssetObject = nullptr;
	if (Object->TryGetObjectField(TEXT("asset"), AssetObject) && AssetObject != nullptr)
	{
		Command.Asset = ParseAssetReference(*AssetObject);
	}
	const TSharedPtr<FJsonObject>* ParametersObject = nullptr;
	if (Object->TryGetObjectField(TEXT("parameters"), ParametersObject) && ParametersObject != nullptr && ParametersObject->IsValid())
	{
		for (const auto& Pair : (*ParametersObject)->Values)
		{
			if (Pair.Value.IsValid())
			{
				Command.Parameters.Add(Pair.Key, Pair.Value->AsString());
			}
		}
	}
	return Command;
}

FXaceTickSnapshot UXaceTransportComponent::ParseTickSnapshot(const TSharedPtr<FJsonObject>& Object)
{
	FXaceTickSnapshot Snapshot;
	Snapshot.Tick = JsonInt(Object, TEXT("tick"));
	Snapshot.TimestampMs = JsonInt(Object, TEXT("timestamp_ms"));

	const TArray<TSharedPtr<FJsonValue>>* Entities = nullptr;
	if (Object->TryGetArrayField(TEXT("entities"), Entities) && Entities != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Entities)
		{
			Snapshot.Entities.Add(ParseEntityState(Value->AsObject()));
		}
	}

	const TArray<TSharedPtr<FJsonValue>>* Destroyed = nullptr;
	if (Object->TryGetArrayField(TEXT("destroyed_ids"), Destroyed) && Destroyed != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Destroyed)
		{
			Snapshot.DestroyedIds.Add(int64(FMath::Max(0.0, Value->AsNumber())));
		}
	}
	const TArray<TSharedPtr<FJsonValue>>* Spawned = nullptr;
	if (Object->TryGetArrayField(TEXT("spawned_ids"), Spawned) && Spawned != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Spawned)
		{
			Snapshot.SpawnedIds.Add(int64(FMath::Max(0.0, Value->AsNumber())));
		}
	}
	const TArray<TSharedPtr<FJsonValue>>* PlaybackCommands = nullptr;
	if (Object->TryGetArrayField(TEXT("playback_commands"), PlaybackCommands) && PlaybackCommands != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *PlaybackCommands)
		{
			Snapshot.PlaybackCommands.Add(ParsePlaybackCommand(Value->AsObject()));
		}
	}
	return Snapshot;
}

FXaceHandshakeAck UXaceTransportComponent::ParseHandshakeAck(const TSharedPtr<FJsonObject>& Object)
{
	FXaceHandshakeAck Ack;
	Ack.bAccepted = Object->GetBoolField(TEXT("accepted"));
	Ack.RejectReason = JsonString(Object, TEXT("reject_reason"));
	Ack.SessionId = JsonString(Object, TEXT("session_id"));
	Ack.TickRate = int32(JsonInt(Object, TEXT("tick_rate"), 60));
	Ack.CgsHash = JsonString(Object, TEXT("cgs_hash"));
	Ack.SchemaVersion = JsonString(Object, TEXT("schema_version"));

	const TArray<TSharedPtr<FJsonValue>>* InitialEntities = nullptr;
	if (Object->TryGetArrayField(TEXT("initial_entities"), InitialEntities) && InitialEntities != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *InitialEntities)
		{
			Ack.InitialEntities.Add(ParseEntityState(Value->AsObject()));
		}
	}
	return Ack;
}

FString UXaceTransportComponent::JsonToString(const TSharedRef<FJsonObject>& Object)
{
	FString Out;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Object, Writer);
	return Out;
}

FString UXaceTransportComponent::PortableText(const FString& Value, int32 MaxBytes, const FString& Fallback)
{
	FString Out;
	for (const TCHAR Ch : Value.TrimStartAndEnd())
	{
		if (FChar::IsAlnum(Ch) || Ch == TEXT('_') || Ch == TEXT('-') || Ch == TEXT('.') || Ch == TEXT('/') || Ch == TEXT(' '))
		{
			Out.AppendChar(Ch);
		}
	}
	while (FTCHARToUTF8(*Out).Length() > MaxBytes && !Out.IsEmpty())
	{
		Out.LeftChopInline(1);
	}
	return Out.IsEmpty() ? Fallback : Out;
}
