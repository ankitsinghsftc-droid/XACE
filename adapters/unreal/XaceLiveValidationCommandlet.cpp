#include "XaceLiveValidationCommandlet.h"

#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
	bool ReadStringParam(const FString& Params, const TCHAR* Key, FString& OutValue)
	{
		const FString Dashed = FString::Printf(TEXT("-%s="), Key);
		const FString Plain = FString::Printf(TEXT("%s="), Key);
		return FParse::Value(*Params, *Dashed, OutValue) || FParse::Value(*Params, *Plain, OutValue);
	}

	int32 ReadIntParam(const FString& Params, const TCHAR* Key, int32 Fallback)
	{
		FString Raw;
		return ReadStringParam(Params, Key, Raw) ? FCString::Atoi(*Raw) : Fallback;
	}

	float ReadFloatParam(const FString& Params, const TCHAR* Key, float Fallback)
	{
		FString Raw;
		return ReadStringParam(Params, Key, Raw) ? FCString::Atof(*Raw) : Fallback;
	}

	FString JsonToString(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	bool WriteReport(const FString& OutputPath, const TSharedRef<FJsonObject>& Report, FString& OutError)
	{
		const FString Path = OutputPath.TrimStartAndEnd();
		if (Path.IsEmpty())
		{
			return true;
		}
		const FString Directory = FPaths::GetPath(Path);
		if (!Directory.IsEmpty())
		{
			IFileManager::Get().MakeDirectory(*Directory, true);
		}
		if (!FFileHelper::SaveStringToFile(JsonToString(Report) + TEXT("\n"), *Path))
		{
			OutError = FString::Printf(TEXT("failed to write validation report: %s"), *Path);
			return false;
		}
		return true;
	}

	template <typename TComponent>
	TComponent* AddValidationComponent(AActor* Owner, const FName Name)
	{
		if (Owner == nullptr)
		{
			return nullptr;
		}
		TComponent* Component = NewObject<TComponent>(Owner, Name);
		if (Component == nullptr)
		{
			return nullptr;
		}
		Owner->AddInstanceComponent(Component);
		Component->RegisterComponent();
		return Component;
	}
}

UXaceLiveValidationCommandlet::UXaceLiveValidationCommandlet()
{
	IsClient = false;
	IsEditor = true;
	LogToConsole = true;
	ShowErrorCount = false;
}

int32 UXaceLiveValidationCommandlet::Main(const FString& Params)
{
	bConnected = false;
	bHandshakeAccepted = false;
	AppliedSnapshots = 0;
	AppliedEntities = 0;
	FeedbackReady = 0;
	InputPacketsBuilt = 0;
	ProtocolErrors = 0;
	LastError.Reset();

	FString Host = TEXT("127.0.0.1");
	FString CgsHash;
	FString OutputPath = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("XaceLiveValidation.json"));
	ReadStringParam(Params, TEXT("XaceHost"), Host);
	ReadStringParam(Params, TEXT("XaceCgsHash"), CgsHash);
	ReadStringParam(Params, TEXT("XaceOutput"), OutputPath);
	const int32 Port = FMath::Clamp(ReadIntParam(Params, TEXT("XacePort"), 7777), 1, 65535);
	const float Seconds = FMath::Clamp(ReadFloatParam(Params, TEXT("XaceSeconds"), 12.0f), 1.0f, 120.0f);

	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("XaceLiveValidationWorld"));
	if (World == nullptr || GEngine == nullptr)
	{
		LastError = TEXT("Unable to create Unreal validation world.");
		TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
		Report->SetBoolField(TEXT("ok"), false);
		Report->SetStringField(TEXT("error"), LastError);
		FString WriteError;
		WriteReport(OutputPath, Report, WriteError);
		return 1;
	}

	GEngine->CreateNewWorldContext(EWorldType::Game).SetCurrentWorld(World);

	AActor* HostActor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity);
	UXaceTransportComponent* Transport = AddValidationComponent<UXaceTransportComponent>(HostActor, TEXT("XaceTransport"));
	UXaceDeltaApplicatorComponent* Applicator = AddValidationComponent<UXaceDeltaApplicatorComponent>(HostActor, TEXT("XaceDeltaApplicator"));
	UXaceInputCollectorComponent* InputCollector = AddValidationComponent<UXaceInputCollectorComponent>(HostActor, TEXT("XaceInputCollector"));

	if (HostActor == nullptr || Transport == nullptr || Applicator == nullptr || InputCollector == nullptr)
	{
		LastError = TEXT("Unable to create Unreal validation adapter components.");
	}
	else
	{
		Transport->bAutoConnect = false;
		Transport->bReconnect = false;
		Transport->EngineName = TEXT("UnrealLiveValidation");
		Transport->ConfigureConnection(Host, Port, CgsHash);
		Transport->Capabilities.AddUnique(TEXT("live_validation"));
		Transport->OnConnectionChanged.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleConnectionChanged);
		Transport->OnHandshakeAccepted.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleHandshakeAccepted);
		Transport->OnHandshakeRejected.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleHandshakeRejected);
		Transport->OnProtocolError.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleProtocolError);

		Applicator->bCollectFeedback = true;
		Applicator->bSendFeedbackToRuntime = true;
		Applicator->bSendLiveValidationFeedback = true;
		Applicator->BindTransportNow();
		Applicator->OnSnapshotApplied.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleSnapshotApplied);
		Applicator->OnFeedbackQueued.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleFeedbackQueued);

		InputCollector->bSendIdleMovement = true;
		InputCollector->DeviceId = TEXT("unreal_live_validation");
		InputCollector->BindTransportNow();
		InputCollector->OnInputPacketBuilt.AddDynamic(this, &UXaceLiveValidationCommandlet::HandleInputPacketBuilt);

		if (!Transport->ConnectToRuntime())
		{
			LastError = Transport->GetLastError();
		}
	}

	const double Deadline = FPlatformTime::Seconds() + double(Seconds);
	while (LastError.IsEmpty() && FPlatformTime::Seconds() < Deadline)
	{
		constexpr float DeltaSeconds = 1.0f / 60.0f;
		Transport->PumpOnce(DeltaSeconds);
		Applicator->BindTransportNow();
		InputCollector->BindTransportNow();
		if (Transport->IsConnected())
		{
			InputCollector->FlushNow();
		}
		Transport->PumpOnce(DeltaSeconds);
		World->Tick(ELevelTick::LEVELTICK_All, DeltaSeconds);
		Transport->PumpOnce(DeltaSeconds);

		const FXaceTransportStats Stats = Transport->GetStats();
		if (bConnected
			&& bHandshakeAccepted
			&& AppliedSnapshots > 0
			&& AppliedEntities > 0
			&& FeedbackReady > 0
			&& InputPacketsBuilt > 0
			&& Stats.FramesReceived > 0
			&& Stats.FramesSent > 2
			&& Stats.ProtocolErrors == 0)
		{
			break;
		}
		FPlatformProcess::Sleep(0.02f);
	}

	const FXaceTransportStats Stats = Transport != nullptr ? Transport->GetStats() : FXaceTransportStats();
	if (LastError.IsEmpty() && Stats.ProtocolErrors > 0)
	{
		LastError = Transport != nullptr ? Transport->GetLastError() : TEXT("Unreal adapter protocol error.");
	}

	const bool bOk = LastError.IsEmpty()
		&& bConnected
		&& bHandshakeAccepted
		&& AppliedSnapshots > 0
		&& AppliedEntities > 0
		&& FeedbackReady > 0
		&& InputPacketsBuilt > 0
		&& Stats.FramesReceived > 0
		&& Stats.FramesSent > 2
		&& Stats.ProtocolErrors == 0;

	if (!bOk && LastError.IsEmpty())
	{
		LastError = TEXT("Unreal live validation timed out before the adapter completed the full runtime loop.");
	}

	TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetBoolField(TEXT("ok"), bOk);
	Report->SetStringField(TEXT("host"), Host);
	Report->SetNumberField(TEXT("port"), Port);
	Report->SetBoolField(TEXT("connected"), bConnected);
	Report->SetBoolField(TEXT("handshake_accepted"), bHandshakeAccepted);
	Report->SetNumberField(TEXT("applied_snapshots"), AppliedSnapshots);
	Report->SetNumberField(TEXT("applied_entities"), AppliedEntities);
	Report->SetNumberField(TEXT("feedback_ready"), FeedbackReady);
	Report->SetNumberField(TEXT("input_packets_built"), InputPacketsBuilt);
	Report->SetNumberField(TEXT("frames_received"), Stats.FramesReceived);
	Report->SetNumberField(TEXT("frames_sent"), Stats.FramesSent);
	Report->SetNumberField(TEXT("bytes_received"), Stats.BytesReceived);
	Report->SetNumberField(TEXT("bytes_sent"), Stats.BytesSent);
	Report->SetNumberField(TEXT("queued_messages"), Stats.QueuedMessages);
	Report->SetNumberField(TEXT("protocol_errors"), Stats.ProtocolErrors);
	Report->SetStringField(TEXT("error"), bOk ? TEXT("") : LastError);

	FString WriteError;
	if (!WriteReport(OutputPath, Report, WriteError))
	{
		UE_LOG(LogTemp, Error, TEXT("XACE Unreal live validation: %s"), *WriteError);
	}

	if (Transport != nullptr && Transport->IsConnected())
	{
		Transport->DisconnectFromRuntime(TEXT("unreal live validation complete"));
	}
	if (World != nullptr)
	{
		World->DestroyWorld(false);
		GEngine->DestroyWorldContext(World);
	}

	UE_LOG(LogTemp, Display, TEXT("XACE Unreal live validation report: %s"), *JsonToString(Report));
	return bOk ? 0 : 1;
}

void UXaceLiveValidationCommandlet::HandleConnectionChanged(bool bInConnected)
{
	bConnected = bInConnected;
}

void UXaceLiveValidationCommandlet::HandleHandshakeAccepted(const FXaceHandshakeAck& Ack)
{
	bHandshakeAccepted = Ack.bAccepted;
}

void UXaceLiveValidationCommandlet::HandleHandshakeRejected(const FString& Reason)
{
	bHandshakeAccepted = false;
	LastError = Reason.IsEmpty() ? TEXT("Unreal runtime handshake was rejected.") : Reason;
}

void UXaceLiveValidationCommandlet::HandleSnapshotApplied(int64 Tick, int32 EntityCount)
{
	AppliedSnapshots++;
	AppliedEntities = FMath::Max(AppliedEntities, EntityCount);
}

void UXaceLiveValidationCommandlet::HandleFeedbackQueued(const FString& FeedbackJson)
{
	if (!FeedbackJson.TrimStartAndEnd().IsEmpty())
	{
		FeedbackReady++;
	}
}

void UXaceLiveValidationCommandlet::HandleInputPacketBuilt(const FXaceInputPacket& Packet)
{
	InputPacketsBuilt++;
}

void UXaceLiveValidationCommandlet::HandleProtocolError(const FString& Message)
{
	ProtocolErrors++;
	LastError = Message;
}
