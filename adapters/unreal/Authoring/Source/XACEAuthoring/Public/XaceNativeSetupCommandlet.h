#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "XaceNativeSetupCommandlet.generated.h"
UCLASS()
class UXaceNativeSetupCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UXaceNativeSetupCommandlet();
    virtual int32 Main(const FString& Params) override;
};
