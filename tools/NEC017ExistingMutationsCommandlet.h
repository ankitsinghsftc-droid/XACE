#pragma once
#include "Commandlets/Commandlet.h"
#include "NEC017ExistingMutationsCommandlet.generated.h"
UCLASS()
class UNEC017ExistingMutationsCommandlet:public UCommandlet {
 GENERATED_BODY()
 public:UNEC017ExistingMutationsCommandlet();virtual int32 Main(const FString& Params) override;
};
