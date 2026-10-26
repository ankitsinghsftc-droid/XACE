#include "NEC015HostProofCommandlet.h"
#include "XaceNativeHostClient.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
namespace {
bool Receive(FXaceNativeHostClient& Client,TSharedPtr<FJsonObject>& Row)
{
 double End=FPlatformTime::Seconds()+20;while(FPlatformTime::Seconds()<End){TArray<TSharedPtr<FJsonObject>> Rows;if(!Client.Poll(Rows))return false;if(Rows.Num()==1){Row=Rows[0];return true;}if(Rows.Num()>1)return false;FPlatformProcess::Sleep(.01f);}return false;
}
bool Gone(uint32 Id){if(Id==0)return false;auto P=FPlatformProcess::OpenProcess(Id);bool Result=!P.IsValid()||!FPlatformProcess::IsProcRunning(P);if(P.IsValid())FPlatformProcess::CloseProc(P);return Result;}
}
int32 UNEC015HostProofCommandlet::Main(const FString& Params)
{
 FString Launcher,Release,History,Report;FParse::Value(*Params,TEXT("Launcher="),Launcher);FParse::Value(*Params,TEXT("Release="),Release);FParse::Value(*Params,TEXT("History="),History);FParse::Value(*Params,TEXT("Report="),Report);
 auto Proof=MakeShared<FJsonObject>();int32 Checks=0;FString Error;uint32 Owner=0,Runtime=0;
 const FString Pin=FXaceNativeHostClient::FileHash(Launcher),Expected=FXaceNativeHostClient::FileHash(Release/TEXT("native-release.json"));
 auto Check=[&](bool Good,const FString& Why){if(!Good){Error=Why;return false;}++Checks;return true;};
 FXaceNativeHostClient Client;TSharedPtr<FJsonObject> Row;
 do {
  FXaceNativeHostClient Refused;if(!Check(!Refused.Start(Launcher,FString::ChrN(64,'0'),Release,Expected,History,1)&&Refused.ProcessId==0,TEXT("Bad launcher pin accepted")))break;
  if(!Check(Client.Start(Launcher,Pin,Release,Expected,History,1),Client.Error))break;Owner=Client.ProcessId;
  if(!Check(Receive(Client,Row)&&Row->GetStringField(TEXT("state"))==TEXT("stopped"),TEXT("Admission failed: ")+Client.Error))break;
  for(int32 Cycle=0;Cycle<3&&Error.IsEmpty();++Cycle){
   if(!Check(Client.Send(TEXT("play"))&&Receive(Client,Row)&&Row->GetBoolField(TEXT("ok")),TEXT("Play failed: ")+Client.Error))break;
   auto Result=Row->GetObjectField(TEXT("result"));Runtime=uint32(Result->GetNumberField(TEXT("runtime_pid")));
   if(!Check(Runtime>0&&FPaths::FileExists(Result->GetStringField(TEXT("ticket"))),TEXT("Missing runtime ticket")))break;
   if(!Check(Client.Send(TEXT("play"))&&Receive(Client,Row)&&uint32(Row->GetObjectField(TEXT("result"))->GetNumberField(TEXT("runtime_pid")))==Runtime,TEXT("Repeated Play changed runtime")))break;
   if(Cycle<2){if(!Check(Client.Send(TEXT("stop"))&&Receive(Client,Row)&&Row->GetObjectField(TEXT("result"))->GetStringField(TEXT("state"))==TEXT("stopped"),TEXT("Stop failed")))break;}
  }
 } while(false);
 Client.Close();for(int32 I=0;I<200&&(!Gone(Owner)||!Gone(Runtime));++I)FPlatformProcess::Sleep(.02f);
 Check(Gone(Owner)&&Gone(Runtime),TEXT("Owned processes survived EOF"));
 Proof->SetBoolField(TEXT("ok"),Error.IsEmpty());Proof->SetNumberField(TEXT("checks"),Checks);Proof->SetStringField(TEXT("error"),Error);Proof->SetNumberField(TEXT("owner_pid"),Owner);Proof->SetNumberField(TEXT("runtime_pid"),Runtime);Proof->SetBoolField(TEXT("full_pie"),false);Proof->SetBoolField(TEXT("packaged_build"),false);
 FString Text;auto Writer=TJsonWriterFactory<>::Create(&Text);FJsonSerializer::Serialize(Proof.ToSharedRef(),Writer);FFileHelper::SaveStringToFile(Text,*Report);return Error.IsEmpty()?0:1;
}
