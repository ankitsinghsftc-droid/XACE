#pragma once
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// Presentation readers only: arbitrary semantic types/capabilities stay opaque.
namespace XaceCanonical
{
    constexpr int64 MaxExact = 9007199254740991LL;
    TSharedPtr<FJsonObject> Parse(const FString& Raw);
    FString Json(const TSharedPtr<FJsonObject>& Object);
    FString Hash(const FString& Raw);
    bool Integer(const TSharedPtr<FJsonObject>& Object, const FString& Key, int64& Out, int64 Minimum = 0);
    bool Vector(const TSharedPtr<FJsonObject>& Object, FVector& Out, bool bScale = false);
    bool Rotation(const TSharedPtr<FJsonObject>& Object, FQuat& Out);
    bool Entities(const TArray<TSharedPtr<FJsonValue>>& Values);
}

class FXaceNativeSession
{
public:
    FString OfferJson, Credential, Error;
    int64 PeerId = 0, PlayerId = 0, ControllerId = 0, NextTick = 0, Generation = 0;
    bool bRecovering = true;
    TSharedPtr<FJsonObject> World;
    TMap<FString, int64> Bindings;
    bool Enabled() const { return !OfferJson.IsEmpty(); }
    bool Configure(const FString& TicketJson, const FString& WorldJson);
    // accept/drop/recover/reject; state commits only after complete verification.
    FString Verify(const TSharedPtr<FJsonObject>& Message);
    bool Request(int64 Tick);
    bool CanSend(int64 Tick, int64 Peer, int64 Player) const;
    void Sent() { bSent = true; }
    void Fence() { bRecovering = true; RequestedTick = -1; }
private:
    TSharedPtr<FJsonObject> Epoch;
    FString CgsHash;
    int64 Sequence = 0, RequestedTick = -1;
    bool bSent = false;
    bool Bind(const TSharedPtr<FJsonObject>& Map, const TArray<TSharedPtr<FJsonValue>>& Entities);
};
