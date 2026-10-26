#include "XaceNativeHostClient.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
THIRD_PARTY_INCLUDES_START
#include <openssl/sha.h>
THIRD_PARTY_INCLUDES_END
namespace {
bool HashValid(const FString& S) { if(S.Len()!=64)return false;for(TCHAR C:S)if(!((C>='0'&&C<='9')||(C>='a'&&C<='f')))return false;return true; }
bool PathValid(const FString& S) { return S.Len()>2 && !FPaths::IsRelative(S) && !S.Contains(TEXT("\"")) && !S.Contains(TEXT("\r")) && !S.Contains(TEXT("\n")); }
FString Quote(const FString& S) { FString Result=TEXT("\"");int32 Slashes=0;for(TCHAR C:S){if(C=='\\'){++Slashes;continue;}Result+=FString::ChrN(C=='"'?Slashes*2+1:Slashes,'\\');Result.AppendChar(C);Slashes=0;}return Result+FString::ChrN(Slashes*2,'\\')+TEXT("\""); }
}
FString FXaceNativeHostClient::FileHash(const FString& Path)
{
    TArray<uint8> Bytes;if(!FFileHelper::LoadFileToArray(Bytes,*Path))return TEXT("");
    uint8 Digest[SHA256_DIGEST_LENGTH];return SHA256(Bytes.GetData(),Bytes.Num(),Digest)?BytesToHex(Digest,SHA256_DIGEST_LENGTH).ToLower():TEXT("");
}
bool FXaceNativeHostClient::Start(const FString& Launcher,const FString& LauncherHash,const FString& Release,const FString& ReleaseHash,const FString& History,uint64 Controller)
{
    if(Closed||Process.IsValid()||Controller==0||!PathValid(Launcher)||!PathValid(Release)||!PathValid(History)||!HashValid(LauncherHash)||!HashValid(ReleaseHash)||FileHash(Launcher)!=LauncherHash){Error=TEXT("Native launcher paths/identity invalid");return false;}
    void* ChildOut=nullptr;void* ChildIn=nullptr;void* ChildError=nullptr;
    if(!FPlatformProcess::CreatePipe(Read,ChildOut)||!FPlatformProcess::CreatePipe(ChildIn,Write,true)||!FPlatformProcess::CreatePipe(Diagnostics,ChildError))
    {FPlatformProcess::ClosePipe(ChildIn,ChildOut);FPlatformProcess::ClosePipe(nullptr,ChildError);Error=TEXT("Native owner pipe creation failed");Close();return false;}
    const FString Args=TEXT("--native-host --source ")+Quote(Release)+TEXT(" --expected ")+Quote(ReleaseHash)+TEXT(" --history ")+Quote(History)+FString::Printf(TEXT(" --controller %llu"),Controller);
    Process=FPlatformProcess::CreateProc(*Launcher,*Args,false,true,true,&ProcessId,0,*Release,ChildOut,ChildIn,ChildError);
    FPlatformProcess::ClosePipe(ChildIn,ChildOut);FPlatformProcess::ClosePipe(nullptr,ChildError);
    if(!Process.IsValid()){Error=TEXT("Native owner launch failed");Close();return false;}return true;
}
bool FXaceNativeHostClient::Send(const FString& Command,const FString& Slot)
{
    if(Closed||!Process.IsValid()||!Error.IsEmpty())return false;
    if(Command!=TEXT("play")&&Command!=TEXT("stop")&&Command!=TEXT("verify")&&Command!=TEXT("status")&&Command!=TEXT("check-save")){Error=TEXT("Unsupported host command");return false;}
    if(Command==TEXT("check-save")){if(Slot.IsEmpty()||Slot.Len()>64)return false;for(TCHAR C:Slot)if(!((C>='a'&&C<='z')||(C>='A'&&C<='Z')||(C>='0'&&C<='9')||C=='-'||C=='_'))return false;}
    auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("action"),Command);if(Command==TEXT("check-save"))Row->SetStringField(TEXT("slot"),Slot);
    FString Line;auto Writer=TJsonWriterFactory<TCHAR,TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);FJsonSerializer::Serialize(Row,Writer);Line+=TEXT("\n");
    FTCHARToUTF8 Bytes(*Line);int32 Written=0;
    if(Bytes.Length()>8192||!FPlatformProcess::WritePipe(Write,reinterpret_cast<const uint8*>(Bytes.Get()),Bytes.Length(),&Written)||Written!=Bytes.Length()){Error=TEXT("Native command pipe failed");return false;}return true;
}
bool FXaceNativeHostClient::Poll(TArray<TSharedPtr<FJsonObject>>& Messages)
{
    Messages.Reset();if(Closed||!Process.IsValid())return false;
    TArray<uint8> Bytes;FPlatformProcess::ReadPipeToArray(Read,Bytes);if(Bytes.Num()>131072||Pending.Num()+Bytes.Num()>131072){Error=TEXT("Native response limit");return false;}Pending.Append(Bytes);
    int32 Index=0;
    while(Pending.Find(uint8('\n'),Index))
    {
        if(Index>65536||Messages.Num()>=64){Error=TEXT("Native message limit");return false;}
        FUTF8ToTCHAR Text(reinterpret_cast<const ANSICHAR*>(Pending.GetData()),Index);FString Line(Text.Length(),Text.Get());TSharedPtr<FJsonObject> Row;
        if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Line),Row)||!Row.IsValid()){Error=TEXT("Native response invalid");return false;}
        Messages.Add(Row);Pending.RemoveAt(0,Index+1,EAllowShrinking::No);
    }
    if(Pending.Num()>65536){Error=TEXT("Native line limit");return false;}
    const FString Diagnostic=FPlatformProcess::ReadPipe(Diagnostics);if(!Diagnostic.IsEmpty()){Error=TEXT("Native diagnostic: ")+Diagnostic.Left(2048);return false;}
    if(!FPlatformProcess::IsProcRunning(Process)&&Messages.IsEmpty()){Error=TEXT("Native authority owner exited");return false;}return Error.IsEmpty();
}
void FXaceNativeHostClient::Close()
{
    if(Closed)return;Closed=true;
    FPlatformProcess::ClosePipe(Read,Write);Read=nullptr;Write=nullptr;
    FPlatformProcess::ClosePipe(Diagnostics,nullptr);Diagnostics=nullptr;
    if(Process.IsValid())FPlatformProcess::CloseProc(Process);
}
