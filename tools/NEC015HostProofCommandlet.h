#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "NEC015HostProofCommandlet.generated.h"
UCLASS()
class UNEC015HostProofCommandlet : public UCommandlet
{
 GENERATED_BODY()
public:
 virtual int32 Main(const FString& Params) override;
};
