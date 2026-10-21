#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "NEC011FidelityCommandlet.generated.h"
UCLASS()
class UNEC011FidelityCommandlet : public UCommandlet {
 GENERATED_BODY()
public:
 UNEC011FidelityCommandlet();
 virtual int32 Main(const FString& Params) override;
};
