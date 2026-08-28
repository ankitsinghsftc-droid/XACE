#include "XaceConsoleWidget.h"

#include "Components/Button.h"
#include "Components/EditableTextBox.h"
#include "Components/ProgressBar.h"
#include "Components/ScrollBox.h"
#include "Components/TextBlock.h"
#include "Dom/JsonValue.h"
#include "Misc/SecureHash.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

void UXaceConsoleWidget::NativeOnInitialized()
{
	Super::NativeOnInitialized();
	SessionId = FGuid::NewGuid().ToString(EGuidFormats::Digits).Left(8);
	if (SubmitButton != nullptr)
	{
		SubmitButton->OnClicked.AddDynamic(this, &UXaceConsoleWidget::HandleSubmitClicked);
	}
	if (ApplyButton != nullptr)
	{
		ApplyButton->OnClicked.AddDynamic(this, &UXaceConsoleWidget::HandleApplyClicked);
	}
	if (CancelButton != nullptr)
	{
		CancelButton->OnClicked.AddDynamic(this, &UXaceConsoleWidget::HandleCancelClicked);
	}
	RefreshUi();
}

void UXaceConsoleWidget::NativeDestruct()
{
	if (Transport != nullptr)
	{
		Transport->OnHandshakeAccepted.RemoveDynamic(this, &UXaceConsoleWidget::HandleHandshake);
		Transport->OnProtocolError.RemoveDynamic(this, &UXaceConsoleWidget::HandleProtocolError);
		Transport->OnJsonMessage.RemoveAll(this);
	}
	Super::NativeDestruct();
}

void UXaceConsoleWidget::BindTransport(UXaceTransportComponent* InTransport)
{
	if (Transport == InTransport)
	{
		return;
	}
	if (Transport != nullptr)
	{
		Transport->OnHandshakeAccepted.RemoveDynamic(this, &UXaceConsoleWidget::HandleHandshake);
		Transport->OnProtocolError.RemoveDynamic(this, &UXaceConsoleWidget::HandleProtocolError);
		Transport->OnJsonMessage.RemoveAll(this);
	}
	Transport = InTransport;
	if (Transport != nullptr)
	{
		Transport->OnHandshakeAccepted.AddDynamic(this, &UXaceConsoleWidget::HandleHandshake);
		Transport->OnProtocolError.AddDynamic(this, &UXaceConsoleWidget::HandleProtocolError);
		Transport->OnJsonMessage.AddUObject(this, &UXaceConsoleWidget::HandleJsonMessage);
	}
}

void UXaceConsoleWidget::SubmitPrompt(const FString& Prompt)
{
	const FString Clean = Prompt.TrimStartAndEnd();
	if (Clean.IsEmpty())
	{
		return;
	}
	SetState(EXaceConsoleState::PromptSubmitted);
	PendingMutationId.Reset();
	CurrentConfidence = 0.0f;
	if (PreviewText != nullptr)
	{
		PreviewText->SetText(FText::GetEmpty());
	}
	AppendLog(TEXT("> ") + Clean);
	OnPromptSubmitted.Broadcast(Clean);

	TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
	Payload->SetStringField(TEXT("prompt"), Clean);
	Payload->SetStringField(TEXT("session_id"), SessionId);
	SendControl(TEXT("PromptSubmit"), Payload);
}

void UXaceConsoleWidget::ReceivePreview(const FString& Preview, float Confidence, const FString& MutationId)
{
	PendingMutationId = MutationId;
	CurrentConfidence = FMath::Clamp(Confidence, 0.0f, 1.0f);
	if (PreviewText != nullptr)
	{
		PreviewText->SetText(FText::FromString(Preview));
	}
	AppendLog(TEXT("preview: ") + Preview);
	SetState(EXaceConsoleState::UserDecision);
}

void UXaceConsoleWidget::SetConsoleError(const FString& Message)
{
	AppendLog(TEXT("error: ") + Message);
	SetState(EXaceConsoleState::Error);
}

void UXaceConsoleWidget::ApplyMutation()
{
	SetState(EXaceConsoleState::Applying);
	AppendLog(TEXT("apply requested"));
	OnApplyRequested.Broadcast(PendingMutationId);

	TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
	Payload->SetStringField(TEXT("decision"), TEXT("Apply"));
	Payload->SetStringField(TEXT("mutation_id"), PendingMutationId);
	Payload->SetStringField(TEXT("session_id"), SessionId);
	SendControl(TEXT("MutationDecision"), Payload);
}

void UXaceConsoleWidget::CancelMutation()
{
	AppendLog(TEXT("cancelled"));
	OnCancelRequested.Broadcast(PendingMutationId);

	TSharedRef<FJsonObject> Payload = MakeShared<FJsonObject>();
	Payload->SetStringField(TEXT("decision"), TEXT("Cancel"));
	Payload->SetStringField(TEXT("mutation_id"), PendingMutationId);
	Payload->SetStringField(TEXT("session_id"), SessionId);
	SendControl(TEXT("MutationDecision"), Payload);

	PendingMutationId.Reset();
	CurrentConfidence = 0.0f;
	SetState(EXaceConsoleState::Idle);
}

FString UXaceConsoleWidget::GetStateName() const
{
	switch (State)
	{
	case EXaceConsoleState::Idle: return TEXT("Idle");
	case EXaceConsoleState::PromptSubmitted: return TEXT("PromptSubmitted");
	case EXaceConsoleState::PreviewReceived: return TEXT("PreviewReceived");
	case EXaceConsoleState::UserDecision: return TEXT("UserDecision");
	case EXaceConsoleState::Applying: return TEXT("Applying");
	case EXaceConsoleState::Error: return TEXT("Error");
	default: return TEXT("Unknown");
	}
}

void UXaceConsoleWidget::HandleSubmitClicked()
{
	if (PromptInput == nullptr)
	{
		return;
	}
	const FString Prompt = PromptInput->GetText().ToString();
	PromptInput->SetText(FText::GetEmpty());
	SubmitPrompt(Prompt);
}

void UXaceConsoleWidget::HandleApplyClicked()
{
	ApplyMutation();
}

void UXaceConsoleWidget::HandleCancelClicked()
{
	CancelMutation();
}

void UXaceConsoleWidget::HandleHandshake(const FXaceHandshakeAck& Ack)
{
	RuntimeCgsHash = Ack.CgsHash;
	AppendLog(TEXT("connected: ") + Ack.SessionId);
	AppendLog(TEXT("cgs hash: ") + ShortHash(RuntimeCgsHash));
	if (State == EXaceConsoleState::Error)
	{
		SetState(EXaceConsoleState::Idle);
	}
}

void UXaceConsoleWidget::HandleProtocolError(const FString& Message)
{
	SetConsoleError(Message);
}

void UXaceConsoleWidget::HandleJsonMessage(const TSharedPtr<FJsonObject>& Message)
{
	FString MsgType;
	if (!Message.IsValid() || !Message->TryGetStringField(TEXT("msg_type"), MsgType))
	{
		return;
	}

	if (MsgType == TEXT("tick_snapshot"))
	{
		double TickValue = 0.0;
		Message->TryGetNumberField(TEXT("tick"), TickValue);
		LastRuntimeTick = int64(FMath::Max(0.0, TickValue));
		LastSnapshotHash = SnapshotProofHash(Message);
		RefreshUi();
		return;
	}

	if (MsgType == TEXT("adapter_side_effect_rollback"))
	{
		PendingMutationId.Reset();
		CurrentConfidence = 0.0f;
		if (PreviewText != nullptr)
		{
			PreviewText->SetText(FText::GetEmpty());
		}
		FString Reason;
		Message->TryGetStringField(TEXT("reason"), Reason);
		AppendLog(TEXT("rollback: ") + (Reason.IsEmpty() ? TEXT("adapter side effects restored") : Reason));
		SetState(EXaceConsoleState::Idle);
		return;
	}

	if (MsgType != TEXT("control"))
	{
		return;
	}

	FString ControlType;
	Message->TryGetStringField(TEXT("control_type"), ControlType);
	if (ControlType == TEXT("MutationPreview"))
	{
		FString Description;
		FString MutationId;
		double Confidence = 0.0;
		Message->TryGetStringField(TEXT("description"), Description);
		Message->TryGetStringField(TEXT("mutation_id"), MutationId);
		Message->TryGetNumberField(TEXT("confidence"), Confidence);
		ReceivePreview(
			Description,
			float(Confidence),
			MutationId
		);
	}
	else if (ControlType == TEXT("MutationApplied"))
	{
		AppendLog(TEXT("applied"));
		SetState(EXaceConsoleState::Idle);
	}
	else if (ControlType == TEXT("MutationCancelled"))
	{
		AppendLog(TEXT("cancelled by runtime"));
		SetState(EXaceConsoleState::Idle);
	}
}

void UXaceConsoleWidget::SetState(EXaceConsoleState NextState)
{
	State = NextState;
	RefreshUi();
}

void UXaceConsoleWidget::AppendLog(const FString& Line)
{
	LogLines.Add(FDateTime::Now().ToString(TEXT("[%H:%M:%S] ")) + Line);
	while (LogLines.Num() > MaxLogLines)
	{
		LogLines.RemoveAt(0);
	}
	if (LogScroll != nullptr)
	{
		LogScroll->ClearChildren();
		for (const FString& Item : LogLines)
		{
			UTextBlock* Text = NewObject<UTextBlock>(LogScroll);
			Text->SetText(FText::FromString(Item));
			LogScroll->AddChild(Text);
		}
		LogScroll->ScrollToEnd();
	}
}

void UXaceConsoleWidget::SendControl(const FString& ControlType, const TSharedRef<FJsonObject>& Payload)
{
	if (!bSendControlToRuntime || Transport == nullptr)
	{
		return;
	}
	Payload->SetStringField(TEXT("msg_type"), TEXT("control"));
	Payload->SetStringField(TEXT("control_type"), ControlType);
	Payload->SetNumberField(TEXT("sequence_id"), ControlSequence++);
	Transport->SendJsonObject(Payload);
}

void UXaceConsoleWidget::RefreshUi()
{
	if (StateText != nullptr)
	{
		const FString Proof = FString::Printf(
			TEXT("%s | Tick: %lld | CGS: %s | Snapshot: %s"),
			*GetStateName(),
			LastRuntimeTick,
			*ShortHash(RuntimeCgsHash),
			*ShortHash(LastSnapshotHash)
		);
		StateText->SetText(FText::FromString(Proof));
	}
	if (ConfidenceBar != nullptr)
	{
		ConfidenceBar->SetPercent(CurrentConfidence);
	}
	const bool bCanPrompt = State == EXaceConsoleState::Idle || State == EXaceConsoleState::Error;
	const bool bCanDecide = State == EXaceConsoleState::UserDecision;
	if (SubmitButton != nullptr)
	{
		SubmitButton->SetIsEnabled(bCanPrompt);
	}
	if (PromptInput != nullptr)
	{
		PromptInput->SetIsEnabled(bCanPrompt);
	}
	if (ApplyButton != nullptr)
	{
		ApplyButton->SetIsEnabled(bCanDecide);
	}
	if (CancelButton != nullptr)
	{
		CancelButton->SetIsEnabled(bCanDecide || State == EXaceConsoleState::PromptSubmitted);
	}
}

FString UXaceConsoleWidget::SnapshotProofHash(const TSharedPtr<FJsonObject>& Message)
{
	if (!Message.IsValid())
	{
		return FString();
	}
	const FString Raw = JsonToString(Message.ToSharedRef());
	FMD5 Md5;
	FTCHARToUTF8 Bytes(*Raw);
	Md5.Update(reinterpret_cast<const uint8*>(Bytes.Get()), Bytes.Length());
	uint8 Digest[16];
	Md5.Final(Digest);

	FString Out;
	for (uint8 Byte : Digest)
	{
		Out += FString::Printf(TEXT("%02x"), Byte);
	}
	return Out;
}

FString UXaceConsoleWidget::ShortHash(const FString& Value)
{
	return Value.IsEmpty() ? TEXT("-") : Value.Left(12);
}

FString UXaceConsoleWidget::JsonToString(const TSharedRef<FJsonObject>& Object)
{
	FString Out;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Object, Writer);
	return Out;
}
