#include "NEC011HierarchyCommandlet.h"
#include "XaceAuthoring.h"
#include "FileHelpers.h"
#include "Engine/World.h"
#include "Engine/StaticMeshActor.h"
#include "GameFramework/WorldSettings.h"
#include "Components/StaticMeshComponent.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
using namespace XaceAuthoringWire;
UNEC011HierarchyCommandlet::UNEC011HierarchyCommandlet(){IsEditor=true;IsClient=false;IsServer=false;LogToConsole=true;}
int32 UNEC011HierarchyCommandlet::Main(const FString& Params){
 FXaceUnrealAuthoring Service;Service.bTrustedProject=true;auto W=UEditorLoadingAndSavingUtils::NewBlankMap(false);if(!W)return 1;
 auto Identity=[](int32 N,bool Scene){auto O=New();O->SetStringField(TEXT("schema"),TEXT("xace.native_identity.v1"));O->SetStringField(TEXT("namespace_id"),FString::Printf(TEXT("%032x"),100));O->SetStringField(TEXT("authoring_id"),FString::Printf(TEXT("%032x"),N));O->SetStringField(TEXT("kind"),Scene?TEXT("scene"):TEXT("object"));O->SetStringField(TEXT("generation"),TEXT("1"));return O;};
 if(!Service.Enroll(W->GetWorldSettings(),Identity(1,true)))return 2;
 auto Parent=W->SpawnActor<AStaticMeshActor>();auto Child=W->SpawnActor<AStaticMeshActor>();
 Parent->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);Child->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);
 Parent->GetStaticMeshComponent()->SetCollisionProfileName(TEXT("NoCollision"));Child->GetStaticMeshComponent()->SetCollisionProfileName(TEXT("NoCollision"));
 Parent->SetActorLabel(TEXT("Parent"));Child->SetActorLabel(TEXT("Child"));Parent->SetActorLocation(FVector(0,200,0));Child->AttachToActor(Parent,FAttachmentTransformRules::KeepRelativeTransform);Child->SetActorRelativeLocation(FVector(0,100,0));
 if(!Service.Enroll(Parent,Identity(2,false))||!Service.Enroll(Child,Identity(3,false)))return 3;
 IFileManager::Get().MakeDirectory(*(FPaths::ProjectContentDir()/TEXT("Fixture")),true);
 return FEditorFileUtils::SaveMap(W,FPaths::ProjectContentDir()/TEXT("Fixture/World.umap"))?0:4;
}
