#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "XaceAuthoringProofCommandlet.generated.h"
UCLASS()
class UXaceAuthoringProofCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UXaceAuthoringProofCommandlet();
    virtual int32 Main(const FString& Params) override;
    static int32 Run(const FString& Phase);
};
