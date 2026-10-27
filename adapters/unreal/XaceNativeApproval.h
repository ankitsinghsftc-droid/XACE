#pragma once
#include "CoreMinimal.h"
// Explicit creator approval only; validation never rewrites an approval.
namespace XaceNativeApproval {
 bool RecordSavedSource(FString& Error);
 bool ValidateSource(FString& Error);
 bool ValidateCooked(FString& Error);
}
