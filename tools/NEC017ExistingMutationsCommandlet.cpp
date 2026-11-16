#include "NEC017ExistingMutationsCommandlet.h"
#include "XaceAuthoring.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "Engine/StaticMeshActor.h"
#include "EngineUtils.h"
#include "FileHelpers.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/Parse.h"
using namespace XaceAuthoringWire;
UNEC017ExistingMutationsCommandlet::UNEC017ExistingMutationsCommandlet(){IsClient=false;IsEditor=true;IsServer=false;LogToConsole=true;}
namespace {
AActor* Label(UWorld* W,const FString& Name){for(TActorIterator<AStaticMeshActor> It(W);It;++It)if(It->GetActorLabel()==Name)return *It;return nullptr;}
bool Save(const FString& Path,const Object& Value){return FFileHelper::SaveStringToFile(Json(Value),*Path,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);}
}
int32 UNEC017ExistingMutationsCommandlet::Main(const FString& Params){
 FString Phase;if(!FParse::Value(*Params,TEXT("Phase="),Phase))return 2;const FString Map=TEXT("/Game/World"),Report=FPaths::ProjectDir()/TEXT("mutation-")+Phase+TEXT(".json");auto Output=New();Output->SetStringField(TEXT("phase"),Phase);Output->SetBoolField(TEXT("ok"),false);
 #define REQUIRE_NATIVE(Test,Message) if(!(Test)){Output->SetStringField(TEXT("error"),Message);Save(Report,Output);return 1;}
 FXaceUnrealAuthoring Service;Service.bTrustedProject=true;UWorld* W=Service.LoadApprovedMap(Map);REQUIRE_NATIVE(W,Service.Error);auto Before=Service.Capture(W,Map);REQUIRE_NATIVE(Before,Service.Error);Output->SetObjectField(TEXT("before"),Before);
 auto Crate=Label(W,TEXT("Crate1"));REQUIRE_NATIVE(Crate,TEXT("Original Crate1 absent"));
 if(Phase==TEXT("rename"))Crate->SetActorLabel(TEXT("CrateOne"));
 else if(Phase==TEXT("move")){Crate->SetFolderPath(FName(TEXT("NEC017Workflow/Moved")));Output->SetStringField(TEXT("move_kind"),TEXT("Native Outliner folder; not a map asset rename"));}
 else if(Phase==TEXT("reparent")){
  auto North=Label(W,TEXT("North")),South=Label(W,TEXT("South"));AActor* Child=nullptr;for(TActorIterator<AStaticMeshActor> It(W);It;++It)if(It->GetAttachParentActor()==North&&It->GetActorLabel()==TEXT("DuplicateDisplayName"))Child=*It;
  REQUIRE_NATIVE(North&&South&&Child,TEXT("Original decorative hierarchy absent"));REQUIRE_NATIVE(Child->AttachToActor(South,FAttachmentTransformRules::KeepWorldTransform),TEXT("Native decorative reparent failed"));
 }else if(Phase==TEXT("delete")){auto Removed=Label(W,TEXT("Crate49"));REQUIRE_NATIVE(Removed&&W->DestroyActor(Removed),TEXT("Native deletion failed"));}
 else if(Phase==TEXT("duplicate")){FActorSpawnParameters P;P.Template=Crate;auto Copy=W->SpawnActor<AStaticMeshActor>(P);REQUIRE_NATIVE(Copy&&Copy->GetActorGuid()!=Crate->GetActorGuid(),TEXT("Native duplication/GUID allocation failed"));Copy->SetActorLabel(TEXT("DuplicatedCrate"));}
 else REQUIRE_NATIVE(false,TEXT("Unknown mutation phase"));
 REQUIRE_NATIVE(FEditorFileUtils::SaveMap(W,Service.MapFilename(Map)),TEXT("Native binary map save failed"));W=Service.LoadApprovedMap(Map);REQUIRE_NATIVE(W,Service.Error);auto After=Service.Capture(W,Map);
 if(Phase==TEXT("duplicate")){
  Output->SetBoolField(TEXT("collision_refused"),!After);Output->SetStringField(TEXT("collision_error"),Service.Error);REQUIRE_NATIVE(!After,TEXT("Duplicate authoring identity silently admitted"));auto Copy=Label(W,TEXT("DuplicatedCrate"));REQUIRE_NATIVE(Copy,TEXT("Saved duplicate absent"));FString Old=FXaceUnrealAuthoring::MetadataText(Copy);auto Fresh=Parse(Old);REQUIRE_NATIVE(Fresh,TEXT("Duplicate metadata absent"));Fresh->SetStringField(TEXT("authoring_id"),TEXT("000000000000000000000000000f1b31"));REQUIRE_NATIVE(Service.Enroll(Copy,Fresh,Old),Service.Error);REQUIRE_NATIVE(FEditorFileUtils::SaveMap(W,Service.MapFilename(Map)),TEXT("Distinct identity binary save failed"));W=Service.LoadApprovedMap(Map);After=Service.Capture(W,Map);Output->SetBoolField(TEXT("explicit_distinct_identity"),After.IsValid());
 }
 REQUIRE_NATIVE(After,Service.Error);Output->SetObjectField(TEXT("after"),After);Output->SetBoolField(TEXT("ok"),true);return Save(Report,Output)?0:1;
 #undef REQUIRE_NATIVE
}
