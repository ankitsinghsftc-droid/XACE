#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "XaceNativeContractProofCommandlet.generated.h"
UCLASS()
class UXaceNativeContractProofCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UXaceNativeContractProofCommandlet();
    virtual int32 Main(const FString& Params) override;
};
