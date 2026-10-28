#include "XaceAuthoring.h"
#include "XaceAuthoringBinding.h"
#include "Editor.h"
#include "FileHelpers.h"
#include "Engine/World.h"
#include "Engine/StaticMeshActor.h"
#include "GameFramework/WorldSettings.h"
#include "Components/StaticMeshComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/PackageName.h"
using namespace XaceAuthoringWire;
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::CreateSetup(const Object& Spec,const FString& ApprovedDigest)
{
    Error.Reset();if(!Editor())return nullptr;
    if(!Spec || Spec->Values.Num()!=3 || String(Spec,TEXT("schema"))!=TEXT("xace.unreal_native_setup.v1") || Json(Spec).IsEmpty() || Hash(Json(Spec))!=ApprovedDigest)return Fail(TEXT("Invalid/stale setup request")),nullptr;
    FString Authorization;FFileHelper::LoadFileToString(Authorization,*(FPaths::ProjectDir()/TEXT(".xace/native-setup-approved.json")));auto Approval=Parse(Authorization);
    FString Root=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());FPaths::NormalizeDirectoryName(Root);
    FString ApprovedRoot=FPaths::ConvertRelativePathToFull(String(Approval,TEXT("stage_root")));FPaths::NormalizeDirectoryName(ApprovedRoot);
    if(!Approval || String(Approval,TEXT("digest"))!=ApprovedDigest || Root!=ApprovedRoot)return Fail(TEXT("Foreign setup stage")),nullptr;
    const FString Map=TEXT("/Game/XACEGenerated/World");const FString Directory=FPaths::ProjectContentDir()/TEXT("XACEGenerated");
    if(IFileManager::Get().DirectoryExists(*Directory))return Fail(TEXT("Existing generated content must not be replaced")),nullptr;
    auto Scene=Child(Spec,TEXT("scene"));const TArray<TSharedPtr<FJsonValue>>* Rows=nullptr;
    if(!ValidateMetadata(Scene)||String(Scene,TEXT("kind"))!=TEXT("scene")||!Spec->TryGetArrayField(TEXT("objects"),Rows)||Rows->IsEmpty()||Rows->Num()>1000)return Fail(TEXT("Explicit scene and object identities required")),nullptr;
    TSet<FString> Seen;Seen.Add(String(Scene,TEXT("authoring_id")));
    for(const auto& Value:*Rows){auto Row=Value->AsObject();auto Identity=Child(Row,TEXT("identity"));auto F=Child(Row,TEXT("fields"));FString Name=String(Row,TEXT("name"));
        if(!Row||Row->Values.Num()!=3||!ValidateMetadata(Identity)||String(Identity,TEXT("namespace_id"))!=String(Scene,TEXT("namespace_id"))||String(Identity,TEXT("kind"))!=TEXT("object")||Seen.Contains(String(Identity,TEXT("authoring_id")))||Name.IsEmpty()||Name.Len()>128||!F||(F->Values.Num()<3||F->Values.Num()>6)||!F->HasField(TEXT("transform.position"))||!F->HasField(TEXT("transform.rotation"))||!F->HasField(TEXT("transform.scale")))return Fail(TEXT("Invalid setup object")),nullptr;
        for(const auto& Entry:F->Values)if(Entry.Key!=TEXT("transform.position") && Entry.Key!=TEXT("transform.rotation") && Entry.Key!=TEXT("transform.scale") && Entry.Key!=TEXT("presentation.asset") && Entry.Key!=TEXT("input.action") && Entry.Key!=TEXT("binding.playback"))return Fail(TEXT("Unsupported setup field")),nullptr;
        Seen.Add(String(Identity,TEXT("authoring_id")));
    }
    UWorld* Current=GEditor->GetEditorWorldContext().World();
    if(Current && Current->GetOutermost()->IsDirty())return Fail(TEXT("Dirty editor world; do not discard existing work")),nullptr;
    UWorld* World=UEditorLoadingAndSavingUtils::NewBlankMap(false);if(!World || !Enroll(World->GetWorldSettings(),Scene))return nullptr;
    for(const auto& Value:*Rows){auto Row=Value->AsObject();auto* Actor=World->SpawnActor<AStaticMeshActor>();Actor->SetActorLabel(String(Row,TEXT("name")));Actor->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);Actor->GetStaticMeshComponent()->SetCollisionProfileName(TEXT("NoCollision"));
        auto FieldsValue=Child(Row,TEXT("fields"));
        if(FieldsValue->HasField(TEXT("input.action")) || FieldsValue->HasField(TEXT("binding.playback"))){
            auto* Binding=NewObject<UXaceAuthoringBinding>(Actor,TEXT("XaceAuthoringBinding"));Binding->InputAction=String(FieldsValue,TEXT("input.action"));Binding->BindingId=String(Child(FieldsValue,TEXT("binding.playback")),TEXT("binding_id"));Actor->AddInstanceComponent(Binding);Binding->RegisterComponent();
        }
        if(!Enroll(Actor,Child(Row,TEXT("identity")))||!Apply(Actor,Child(Row,TEXT("fields"))))return nullptr;
    }
    FString Filename=FPackageName::LongPackageNameToFilename(Map,FPackageName::GetMapPackageExtension());
    if(!IFileManager::Get().MakeDirectory(*Directory,true)||!FEditorFileUtils::SaveMap(World,Filename))return Fail(TEXT("Native setup map save failed")),nullptr;
    World=LoadApprovedMap(Map);auto Inventory=World?Capture(World,Map):nullptr;if(!Inventory)return nullptr;
    auto Result=New();Result->SetStringField(TEXT("schema"),TEXT("xace.unreal_native_setup_result.v1"));Result->SetObjectField(TEXT("inventory"),Inventory);Result->SetStringField(TEXT("request_digest"),ApprovedDigest);return Result;
}
