#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class AActor;
class UWorld;
class UObject;
namespace XaceAuthoringWire
{
    using Object = TSharedPtr<FJsonObject>;
    XACEAUTHORING_API Object New();
    XACEAUTHORING_API FString String(const Object& Value, const FString& Key);
    XACEAUTHORING_API Object Child(const Object& Value, const FString& Key);
    XACEAUTHORING_API FString Json(const Object& Value);
    XACEAUTHORING_API Object Parse(const FString& CanonicalJson);
    XACEAUTHORING_API FString Hash(const FString& Text);
    XACEAUTHORING_API FString FileHash(const FString& Path);
    XACEAUTHORING_API bool Id(const FString& Value);
    XACEAUTHORING_API Object Vector(const FVector& Value);
    XACEAUTHORING_API Object Rotation(const FQuat& Value);
}

/** Explicit editor-only APIs. No runtime transport, CGS or identity-map publication. */
class XACEAUTHORING_API FXaceUnrealAuthoring
{
public:
    using Object = XaceAuthoringWire::Object;
    static const TCHAR* Version;
    FString Error;
    Object DependencyInventory;
    bool bTrustedProject = false;
    bool bRescanRequired = true;
    UWorld* LoadApprovedMap(const FString& ApprovedMap);
    // One clean, saved, non-partitioned persistent map per certified operation.
    Object CreateSetup(const Object& Spec, const FString& ApprovedDigest);
    Object Capture(UWorld* World, const FString& ApprovedMap, bool bDiscovery = false);
    bool Enroll(AActor* Actor, const Object& Metadata, const FString& ExpectedOld = TEXT(""));
    Object Metadata(AActor* Actor) const;
    Object Fields(AActor* Actor);
    FString Preservation(AActor* Actor);
    Object PreservationProperties(AActor* Actor);
    Object Asset(UObject* Resource);
    FString Fingerprint(const FString& ApprovedMap, bool AssetPackage = false);
    FString MapFilename(const FString& ApprovedMap);
    bool Editor(UWorld* World = nullptr);
    Object Prepare(UWorld* World, const FString& ApprovedMap, const FString& Request, const FString& TransactionId);
    // Commit/recover require the approved map unloaded to protect editor buffers.
    Object Commit(const FString& ApprovedMap, const FString& Directory, const FString& ApprovalDigest, bool bInjectFailure = false);
    Object Recover(const FString& ApprovedMap, const FString& Directory, const FString& ReceiptDigest);
    bool Fail(const FString& Message);
    static FString MetadataText(AActor* Actor);
private:
    FString LoadedFingerprint;
    TWeakObjectPtr<UWorld> LastWorld;
    bool ValidateMetadata(const Object& Metadata);
    bool Apply(AActor* Actor, const Object& Fields);
    bool VerifyFields(AActor* Actor, const Object& Fields);
    Object Receipt(const FString& Map, const FString& Directory, const FString& Digest);
    bool Persist(const FString& Directory, const Object& Receipt);
};
