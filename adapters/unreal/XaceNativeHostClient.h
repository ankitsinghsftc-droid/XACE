#pragma once
#include "CoreMinimal.h"
#include "HAL/PlatformProcess.h"
#include "Dom/JsonObject.h"

// Creator-trusted Windows owner-pipe client; gameplay/admission remain in Rust.
// One-shot instance. Closing stdin drops only this owner's runtime Job.
class FXaceNativeHostClient
{
public:
    FXaceNativeHostClient() = default;
    ~FXaceNativeHostClient() { Close(); }
    FXaceNativeHostClient(const FXaceNativeHostClient&) = delete;
    FXaceNativeHostClient& operator=(const FXaceNativeHostClient&) = delete;
    bool Start(const FString& Launcher,const FString& LauncherHash,const FString& Release,const FString& ReleaseHash,const FString& History,uint64 Controller);
    bool Send(const FString& Command,const FString& Slot=TEXT(""));
    bool Poll(TArray<TSharedPtr<FJsonObject>>& Messages);
    void Close();
    FString Error;
    uint32 ProcessId = 0;
    static FString FileHash(const FString& Path);
private:
    FProcHandle Process;
    void* Read = nullptr;
    void* Write = nullptr;
    void* Diagnostics = nullptr;
    TArray<uint8> Pending;
    bool Closed = false;
};
