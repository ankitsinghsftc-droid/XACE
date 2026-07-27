#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "XaceTransport.h"
#include "XaceConsoleWidget.generated.h"

class UButton;
class UEditableTextBox;
class UProgressBar;
class UScrollBox;
class UTextBlock;

UENUM(BlueprintType)
enum class EXaceConsoleState : uint8
{
	Idle,
	PromptSubmitted,
	PreviewReceived,
	UserDecision,
	Applying,
	Error
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXacePromptSubmitted, const FString&, Prompt);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FXaceMutationDecision, const FString&, MutationId);

UCLASS()
class UXaceConsoleWidget : public UUserWidget
{
	GENERATED_BODY()

public:
	UPROPERTY(BlueprintAssignable) FXacePromptSubmitted OnPromptSubmitted;
	UPROPERTY(BlueprintAssignable) FXaceMutationDecision OnApplyRequested;
	UPROPERTY(BlueprintAssignable) FXaceMutationDecision OnCancelRequested;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE") bool bSendControlToRuntime = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="XACE") int32 MaxLogLines = 200;

	UPROPERTY(BlueprintReadOnly, Category="XACE") EXaceConsoleState State = EXaceConsoleState::Idle;
	UPROPERTY(BlueprintReadOnly, Category="XACE") FString SessionId;
	UPROPERTY(BlueprintReadOnly, Category="XACE") FString PendingMutationId;
	UPROPERTY(BlueprintReadOnly, Category="XACE") FString RuntimeCgsHash;
	UPROPERTY(BlueprintReadOnly, Category="XACE") FString LastSnapshotHash;
	UPROPERTY(BlueprintReadOnly, Category="XACE") int64 LastRuntimeTick = 0;

	UPROPERTY(meta=(BindWidgetOptional)) UEditableTextBox* PromptInput = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UButton* SubmitButton = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UButton* ApplyButton = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UButton* CancelButton = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UTextBlock* StateText = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UTextBlock* PreviewText = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UProgressBar* ConfidenceBar = nullptr;
	UPROPERTY(meta=(BindWidgetOptional)) UScrollBox* LogScroll = nullptr;

	UFUNCTION(BlueprintCallable, Category="XACE") void BindTransport(UXaceTransportComponent* InTransport);
	UFUNCTION(BlueprintCallable, Category="XACE") void SubmitPrompt(const FString& Prompt);
	UFUNCTION(BlueprintCallable, Category="XACE") void ReceivePreview(const FString& Preview, float Confidence, const FString& MutationId);
	UFUNCTION(BlueprintCallable, Category="XACE") void SetConsoleError(const FString& Message);
	UFUNCTION(BlueprintCallable, Category="XACE") void ApplyMutation();
	UFUNCTION(BlueprintCallable, Category="XACE") void CancelMutation();
	UFUNCTION(BlueprintCallable, Category="XACE") FString GetStateName() const;

protected:
	virtual void NativeOnInitialized() override;
	virtual void NativeDestruct() override;

private:
	UPROPERTY() UXaceTransportComponent* Transport = nullptr;
	TArray<FString> LogLines;
	float CurrentConfidence = 0.0f;
	int64 ControlSequence = 1;

	UFUNCTION() void HandleSubmitClicked();
	UFUNCTION() void HandleApplyClicked();
	UFUNCTION() void HandleCancelClicked();
	UFUNCTION() void HandleHandshake(const FXaceHandshakeAck& Ack);
	UFUNCTION() void HandleProtocolError(const FString& Message);

	void HandleJsonMessage(const TSharedPtr<FJsonObject>& Message);
	void SetState(EXaceConsoleState NextState);
	void AppendLog(const FString& Line);
	void SendControl(const FString& ControlType, const TSharedRef<FJsonObject>& Payload);
	void RefreshUi();
	static FString SnapshotProofHash(const TSharedPtr<FJsonObject>& Message);
	static FString ShortHash(const FString& Value);
	static FString JsonToString(const TSharedRef<FJsonObject>& Object);
};
