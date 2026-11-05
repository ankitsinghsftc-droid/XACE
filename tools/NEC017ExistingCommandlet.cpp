#include "NEC017ExistingCommandlet.h"
#include "XaceAuthoring.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "GameFramework/WorldSettings.h"
#include "FileHelpers.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/PackageName.h"
using namespace XaceAuthoringWire;
UNEC017ExistingCommandlet::UNEC017ExistingCommandlet(){IsClient=false;IsEditor=true;IsServer=false;LogToConsole=true;}
int32 UNEC017ExistingCommandlet::Main(const FString& Params)
{
 const FString Map=TEXT("/Game/World");
 FString File; if(!FPackageName::DoesPackageExist(Map,&File))return 2;
 FString Approved; if(!FFileHelper::LoadFileToString(Approved,*(FPaths::ProjectDir()/TEXT("NEC017.enroll-approved"))))return 2;
 const bool Reload=FParse::Param(*Params,TEXT("ColdReopen"));
 FXaceUnrealAuthoring Service;Service.bTrustedProject=true;
 auto Save=[&](const FString& Name,const Object& Data){return Data && FFileHelper::SaveStringToFile(Json(Data),*(FPaths::ProjectDir()/TEXT(".xace")/Name),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);};
 auto Error=[&](){auto R=New();R->SetBoolField(TEXT("ok"),false);R->SetStringField(TEXT("error"),Service.Error);Save(TEXT("failure.json"),R);return 1;};
 if(!Reload && FileHash(File)!=Approved)return 2;
 UWorld* W=Service.LoadApprovedMap(Map);if(!W)return Error();
 if(!Reload){
  auto Discovery=Service.Capture(W,Map,true);if(!Save(TEXT("existing-discovery.json"),Discovery))return Error();
  const auto& Rows=Discovery->GetArrayField(TEXT("actors"));
  int32 N=0;
  for(const auto& Row:Rows){
   const FString Guid=String(Row->AsObject(),TEXT("actor_guid"));AActor* Found=nullptr;
   for(AActor* Actor:W->PersistentLevel->Actors)if(Actor && Actor->GetActorGuid().ToString(EGuidFormats::Digits)==Guid){Found=Actor;break;}
   if(!Found || !FXaceUnrealAuthoring::MetadataText(Found).IsEmpty())return Error();
   auto Identity=New();Identity->SetStringField(TEXT("schema"),TEXT("xace.native_identity.v1"));
   Identity->SetStringField(TEXT("namespace_id"),TEXT("17171717171717171717171717171717"));
   Identity->SetStringField(TEXT("authoring_id"),FString::Printf(TEXT("%032x"),++N));
   Identity->SetStringField(TEXT("generation"),TEXT("1"));Identity->SetStringField(TEXT("kind"),Found==W->GetWorldSettings()?TEXT("scene"):TEXT("object"));
   if(!Service.Enroll(Found,Identity,TEXT("")))return Error();
  }
  if(!FEditorFileUtils::SaveMap(W,File))return Error();
  W=Service.LoadApprovedMap(Map);if(!W)return Error();
 }
 auto Inventory=Service.Capture(W,Map);if(!Inventory)return Error();
 return Save(Reload?TEXT("existing-cold.json"):TEXT("existing-enrolled.json"),Inventory)?0:1;
}
