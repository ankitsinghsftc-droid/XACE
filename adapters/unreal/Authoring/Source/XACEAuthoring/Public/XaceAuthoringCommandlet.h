#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "XaceAuthoringCommandlet.generated.h"
UCLASS()
class UXaceAuthoringCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UXaceAuthoringCommandlet();
    virtual int32 Main(const FString& Params) override;
};
