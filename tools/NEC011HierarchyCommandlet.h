#pragma once
#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "NEC011HierarchyCommandlet.generated.h"
UCLASS()
class UNEC011HierarchyCommandlet : public UCommandlet { GENERATED_BODY() public: UNEC011HierarchyCommandlet(); virtual int32 Main(const FString& Params) override; };
