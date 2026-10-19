#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "XaceAuthoringBinding.generated.h"

/** Persisted authoring declarations only; no input handling or playback logic. */
UCLASS(NotBlueprintable, ClassGroup=(XACE))
class XACEAUTHORING_API UXaceAuthoringBinding : public UActorComponent
{
    GENERATED_BODY()
public:
    UXaceAuthoringBinding() { PrimaryComponentTick.bCanEverTick=false; }
    UPROPERTY(EditAnywhere, Category="XACE") FString InputAction;
    UPROPERTY(EditAnywhere, Category="XACE") FString BindingId;
    UPROPERTY(EditAnywhere, Category="XACE") FString EventName;
    UPROPERTY(EditAnywhere, Category="XACE") FString PlaybackKind;
    UPROPERTY(EditAnywhere, Category="XACE") TObjectPtr<UObject> Resource=nullptr;
};
