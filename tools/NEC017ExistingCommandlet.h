#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "NEC017ExistingCommandlet.generated.h"
// Test-only wrapper, copied into an isolated fixture plugin by the harness.
UCLASS()
class UNEC017ExistingCommandlet : public UCommandlet
{
 GENERATED_BODY()
public:
 UNEC017ExistingCommandlet();
 virtual int32 Main(const FString& Params) override;
};
