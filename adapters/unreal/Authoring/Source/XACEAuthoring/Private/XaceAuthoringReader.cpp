#include "XaceAuthoring.h"
#include "XaceAuthoringBinding.h"
#include "GameFramework/InputSettings.h"
#include "Sound/SoundWave.h"
#include "Animation/AnimSequence.h"
#include "Editor.h"
#include "FileHelpers.h"
#include "ScopedTransaction.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "Engine/LevelScriptBlueprint.h"
#include "Engine/LevelScriptActor.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
#include "Engine/Blueprint.h"
#include "GameFramework/WorldSettings.h"
#include "GameFramework/GameModeBase.h"
#include "Components/StaticMeshComponent.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "Misc/EngineVersion.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "HAL/PlatformFileManager.h"
#include "UObject/UObjectIterator.h"
#include "UObject/UnrealType.h"
using namespace XaceAuthoringWire;
const TCHAR* FXaceUnrealAuthoring::Version=TEXT("5.7.4-51494982+++UE5+Release-5.7");
namespace
{
const FString Prefix=TEXT("XACE_AUTHORING_V1:");
bool SafeFile(const FString& Name)
{
    FString Current=FPaths::ConvertRelativePathToFull(Name);FPaths::NormalizeFilename(Current);
    if(Current.Contains(TEXT("/../")))return false;
    auto& Platform=FPlatformFileManager::Get().GetPlatformFile();
    while(!Current.IsEmpty()) {
        // Windows junctions/symlinks are excluded by the staging host as well.
        if(Platform.IsSymlink(*Current)==ESymlinkResult::Symlink)return false;
        FString Next=FPaths::GetPath(Current);if(Next==Current)break;Current=Next;
    }
    return true;
}
TSharedPtr<FJsonValue> Null(){return MakeShared<FJsonValueNull>();}
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::PreservationProperties(AActor* Actor)
{
    // The pinned editor exports stored properties; runtime/transient fields are
    // excluded by serialization flags. Separately mapped root transform and
    // static mesh reference are verified in typed fields. All other properties remain.
    auto Rows=New();UWorld* World=Actor->GetWorld();
    TArray<UObject*> Objects;Objects.Add(Actor);
    for(UActorComponent* Component:Actor->GetComponents())
        if(Component && !Component->HasAnyFlags(RF_Transient) && !Component->IsVisualizationComponent())Objects.Add(Component);
    for(UObject* Item:Objects){
        auto Properties=New();
        for(TFieldIterator<FProperty> It(Item->GetClass());It;++It){
            FProperty* Property=*It;
            if(Property->HasAnyPropertyFlags(CPF_Transient|CPF_DuplicateTransient|CPF_NonPIEDuplicateTransient|CPF_SkipSerialization))continue;
            const FString Name=Property->GetName();
            if(Item==Actor->GetRootComponent() && (Name==TEXT("RelativeLocation")||Name==TEXT("RelativeRotation")||Name==TEXT("RelativeScale3D")))continue;
            if(auto* MeshActor=Cast<AStaticMeshActor>(Actor); MeshActor &&
                Item==MeshActor->GetStaticMeshComponent() && Name==TEXT("StaticMesh") &&
                MeshActor->GetStaticMeshComponent()->GetStaticMesh())continue;
            if(auto* Binding=Cast<UXaceAuthoringBinding>(Item); Binding && Binding->GetClass()==UXaceAuthoringBinding::StaticClass()){
                if(Name==TEXT("InputAction") && !Binding->InputAction.IsEmpty())continue;
                if(!Binding->BindingId.IsEmpty() && (Name==TEXT("BindingId")||Name==TEXT("EventName")||Name==TEXT("PlaybackKind")||Name==TEXT("Resource")))continue;
            }
            FString Value;
            Property->ExportTextItem_Direct(Value,Property->ContainerPtrToValuePtr<void>(Item),nullptr,Item,PPF_None);
            // Normalize actual object references, never arbitrary user strings.
            // The staging package renames the UWorld, but object identity inside
            // that world is its relative path, including the referenced class.
            if(auto* Reference=CastField<FObjectPropertyBase>(Property)){
                UObject* Target=Reference->GetObjectPropertyValue_InContainer(Item);
                if(Target && World && (Target==World || Target->IsIn(World)))
                    Value=Target->GetClass()->GetPathName()+TEXT(":<world>:")+Target->GetPathName(World);
            }
            // Arrays of stored object references (e.g. InstanceComponents) also
            // relocate with the staged world. Preserve order/class/relative
            // identity; never normalize user strings or omit the collection.
            if(auto* Array=CastField<FArrayProperty>(Property))if(auto* Reference=CastField<FObjectPropertyBase>(Array->Inner)){
                FScriptArrayHelper Items(Array,Array->ContainerPtrToValuePtr<void>(Item));TArray<TSharedPtr<FJsonValue>> Entries;
                for(int32 Index=0;Index<Items.Num();++Index){
                    FString Entry;Array->Inner->ExportTextItem_Direct(Entry,Items.GetRawPtr(Index),nullptr,Item,PPF_None);
                    UObject* Target=Reference->GetObjectPropertyValue(Items.GetRawPtr(Index));
                    if(Target && World && (Target==World || Target->IsIn(World)))Entry=Target->GetClass()->GetPathName()+TEXT(":<world>:")+Target->GetPathName(World);
                    Entries.Add(MakeShared<FJsonValueString>(Entry));
                }
                auto ArrayValue=New();ArrayValue->SetArrayField(TEXT("object_references"),Entries);Value=Json(ArrayValue);
            }
            Properties->SetStringField(Name,Value);
        }
        FString Key=Item==Actor?TEXT("actor"):Item->GetName();
        Properties->SetStringField(TEXT("$class"),Item->GetClass()->GetPathName());Rows->SetObjectField(Key,Properties);
    }
    return Rows;
}
FString FXaceUnrealAuthoring::Preservation(AActor* Actor)
{
    FString Stored=Json(PreservationProperties(Actor));
    if(Stored.IsEmpty()){Fail(TEXT("Stored properties exceed supported serialization profile"));return TEXT("");}
    return Hash(TEXT("unreal.stored_properties.v1:")+Stored);
}
bool FXaceUnrealAuthoring::Fail(const FString& M){if(Error.IsEmpty())Error=M;return false;}
bool FXaceUnrealAuthoring::Editor(UWorld* W)
{
    if(!bTrustedProject)return Fail(TEXT("Explicit trusted staged-project approval required"));
    if(!GIsEditor || !GEditor || FEngineVersion::Current().ToString()!=Version)return Fail(TEXT("Pinned editor required"));
    if(GEditor->PlayWorld || (W && W->WorldType!=EWorldType::Editor))return Fail(TEXT("PIE/runtime authoring refused"));
    return true;
}
FString FXaceUnrealAuthoring::MapFilename(const FString& Map)
{
    if(!Map.StartsWith(TEXT("/Game/")) || !FPackageName::IsValidLongPackageName(Map) || Map.Contains(TEXT(".."))) {Fail(TEXT("Approved /Game map required"));return TEXT("");}
    FString Filename=FPaths::ConvertRelativePathToFull(FPackageName::LongPackageNameToFilename(Map,FPackageName::GetMapPackageExtension()));
    if(!SafeFile(Filename) || !FPaths::FileExists(Filename)){Fail(TEXT("Missing/linked map file"));return TEXT("");}
    return Filename;
}
FString FXaceUnrealAuthoring::Fingerprint(const FString& Map,bool AssetPackage)
{
    FString Filename;
    if(AssetPackage){
        if(!Map.StartsWith(TEXT("/Game/")) || Map.Contains(TEXT("..")) || !FPackageName::IsValidLongPackageName(Map)){Fail(TEXT("Invalid resource package"));return TEXT("");}
        Filename=FPackageName::LongPackageNameToFilename(Map,TEXT(".uasset"));
        if(!SafeFile(Filename) || !FPaths::FileExists(Filename)){Fail(TEXT("Missing/linked resource package"));return TEXT("");}
    }else Filename=MapFilename(Map);
    if(Filename.IsEmpty())return TEXT("");
    auto& Registry=FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
    Registry.ScanFilesSynchronous({Filename},true);
    TArray<FName> Pending={FName(*Map)};TSet<FName> Seen;auto Files=New();
    while(Pending.Num()) {
        FName PackageName=Pending.Pop();if(Seen.Contains(PackageName))continue;Seen.Add(PackageName);
        if(Seen.Num()>10000){Fail(TEXT("Dependency limit"));return TEXT("");}
        FString Name=PackageName.ToString();if(Name.StartsWith(TEXT("/Script/")))continue;
        FString Path;if(!FPackageName::DoesPackageExist(Name,&Path)){Fail(TEXT("Missing native dependency: ")+Name);return TEXT("");}
        Path=FPaths::ConvertRelativePathToFull(Path);
        if(!SafeFile(Path)){Fail(TEXT("Linked native dependency"));return TEXT("");}
        if(UPackage* Loaded=FindPackage(nullptr,*Name);Loaded && Loaded->IsDirty()){Fail(TEXT("Dirty native dependency"));return TEXT("");}
        Files->SetStringField(Name,FileHash(Path));
        for(const TCHAR* Ext:{TEXT("uexp"),TEXT("ubulk"),TEXT("uptnl")}){
            FString Side=FPaths::ChangeExtension(Path,Ext);if(FPaths::FileExists(Side)){Fail(TEXT("Split/bulk package profile unsupported"));return TEXT("");}}
        Registry.ScanFilesSynchronous({Path},true);
        TArray<FName> Dependencies;Registry.GetDependencies(PackageName,Dependencies);Pending.Append(Dependencies);
    }
    TArray<FString> Configs;IFileManager::Get().FindFilesRecursive(Configs,*FPaths::ProjectConfigDir(),TEXT("*.ini"),true,false);
    TArray<FString> GeneratedInputs;IFileManager::Get().FindFilesRecursive(GeneratedInputs,*(FPaths::ProjectSavedDir()/TEXT("Config")),TEXT("Input.ini"),true,false);Configs.Append(GeneratedInputs);
    for(const FString& Path:Configs){if(!SafeFile(Path)){Fail(TEXT("Linked config"));return TEXT("");}FString Relative=FPaths::ConvertRelativePathToFull(Path);FPaths::MakePathRelativeTo(Relative,*FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()));Files->SetStringField(Relative,FileHash(Path));}
    DependencyInventory=Files;return Hash(Json(Files));
}
UWorld* FXaceUnrealAuthoring::LoadApprovedMap(const FString& Map)
{
    Error.Reset();if(!Editor())return nullptr;
    for(TObjectIterator<UPackage> It;It;++It)if(It->IsDirty() && It->GetName().StartsWith(TEXT("/Game/"))){Fail(TEXT("Save/discard dirty project packages before native reload"));return nullptr;}
    FString File=MapFilename(Map);if(File.IsEmpty())return nullptr;
    FString Before=Fingerprint(Map);if(!Error.IsEmpty())return nullptr;
    UWorld* W=UEditorLoadingAndSavingUtils::LoadMap(File);
    if(!W || !Editor(W) || Before!=Fingerprint(Map)){Fail(TEXT("Native map load/source drift"));return nullptr;}
    LoadedFingerprint=Before;LastWorld=W;bRescanRequired=true;return W;
}
FString FXaceUnrealAuthoring::MetadataText(AActor* A)
{
    FString Result;if(!A)return Result;
    for(FName Tag:A->Tags){FString S=Tag.ToString();if(S.StartsWith(Prefix)){if(!Result.IsEmpty())return TEXT("duplicate");Result=S.Mid(Prefix.Len());}}
    return Result;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Metadata(AActor* A)const{return Parse(MetadataText(A));}
bool FXaceUnrealAuthoring::ValidateMetadata(const Object& M)
{
    int64 Generation=0;FString G=String(M,TEXT("generation"));
    return M && M->Values.Num()==5 && String(M,TEXT("schema"))==TEXT("xace.native_identity.v1") && Id(String(M,TEXT("namespace_id"))) && Id(String(M,TEXT("authoring_id"))) && LexTryParseString(Generation,*G) && Generation>0 && LexToString(Generation)==G && (String(M,TEXT("kind"))==TEXT("scene") || String(M,TEXT("kind"))==TEXT("object"));
}
bool FXaceUnrealAuthoring::Enroll(AActor* A,const Object& M,const FString& Expected)
{
    Error.Reset();if(!A || !Editor(A->GetWorld()) || !ValidateMetadata(M))return Fail(TEXT("Invalid actor/identity enrollment"));
    if(MetadataText(A)!=Expected || (!Expected.IsEmpty() && String(Parse(Expected),TEXT("authoring_id"))==String(M,TEXT("authoring_id"))))return Fail(TEXT("Stale identity; explicit distinct duplicate repair required"));
    const FScopedTransaction Transaction(NSLOCTEXT("XACE","Enroll","XACE enroll native identity"));
    A->Modify();A->Tags.RemoveAll([](FName Tag){return Tag.ToString().StartsWith(Prefix);});
    A->Tags.Add(FName(*(Prefix+Json(M))));A->MarkPackageDirty();bRescanRequired=true;return true;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Asset(UObject* Resource)
{
    FString Type;
    if(Resource && Resource->GetClass()==UStaticMesh::StaticClass())Type=TEXT("MESH");
    else if(Resource && Resource->GetClass()==USoundWave::StaticClass())Type=TEXT("AUDIO_CLIP");
    else if(Resource && Resource->GetClass()==UAnimSequence::StaticClass())Type=TEXT("ANIMATION_CLIP");
    else {Fail(TEXT("Unsupported persistent resource type"));return nullptr;}
    UPackage* Package=Resource->GetOutermost();FString Path;
    if(!Package->GetName().StartsWith(TEXT("/Game/")) || Package->IsDirty() || !Package->GetPersistentGuid().IsValid() || !FPackageName::DoesPackageExist(Package->GetName(),&Path)){Fail(TEXT("Saved project mesh resource required"));return nullptr;}
    auto O=New();O->SetStringField(TEXT("asset_id"),TEXT("unreal_")+Package->GetPersistentGuid().ToString(EGuidFormats::Digits));
    O->SetStringField(TEXT("asset_type"),Type);O->SetStringField(TEXT("status"),TEXT("LINKED"));O->SetStringField(TEXT("resolved_path"),Resource->GetPathName());return O;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Fields(AActor* A)
{
    auto O=New();O->SetStringField(TEXT("native.name"),A->GetActorLabel());O->SetStringField(TEXT("native.class"),A->GetClass()->GetPathName());
    if(A->GetRootComponent()){
        FTransform T=A->GetRootComponent()->GetRelativeTransform();
        O->SetObjectField(TEXT("transform.position"),Vector(T.GetLocation()));O->SetObjectField(TEXT("transform.rotation"),Rotation(T.GetRotation()));O->SetObjectField(TEXT("transform.scale"),Vector(T.GetScale3D()));
    }
    if(auto* MeshActor=Cast<AStaticMeshActor>(A);MeshActor && MeshActor->GetStaticMeshComponent()->GetStaticMesh()){
        auto Ref=Asset(MeshActor->GetStaticMeshComponent()->GetStaticMesh());if(Ref)O->SetObjectField(TEXT("presentation.asset"),Ref);
    }
    TInlineComponentArray<UXaceAuthoringBinding*> BindingComponents;A->GetComponents(BindingComponents);
    if(BindingComponents.Num()>1){Fail(TEXT("Ambiguous authoring binding components"));return nullptr;}
    if(auto* Binding=A->FindComponentByClass<UXaceAuthoringBinding>()){
        if(Binding->GetClass()!=UXaceAuthoringBinding::StaticClass()){Fail(TEXT("Custom authoring behavior requires explicit profile"));return nullptr;}
        if(!Binding->InputAction.IsEmpty()){
            TArray<FName> Actions,Axes;const auto* Settings=GetDefault<UInputSettings>();Settings->GetActionNames(Actions);Settings->GetAxisNames(Axes);
            if(!Actions.Contains(FName(*Binding->InputAction)) && !Axes.Contains(FName(*Binding->InputAction))){Fail(TEXT("Input action absent from native configuration"));return nullptr;}
            O->SetStringField(TEXT("input.action"),Binding->InputAction);
        }
        if(!Binding->BindingId.IsEmpty()){
            auto Ref=Asset(Binding->Resource);if(!Ref)return nullptr;
            const FString Type=String(Ref,TEXT("asset_type"));
            if(Binding->EventName.IsEmpty() || !((Binding->PlaybackKind==TEXT("Audio") && Type==TEXT("AUDIO_CLIP")) || (Binding->PlaybackKind==TEXT("Animation") && Type==TEXT("ANIMATION_CLIP")))){Fail(TEXT("Invalid playback declaration"));return nullptr;}
            auto Playback=New();Playback->SetStringField(TEXT("binding_id"),Binding->BindingId);Playback->SetStringField(TEXT("event_name"),Binding->EventName);Playback->SetStringField(TEXT("playback_kind"),Binding->PlaybackKind);Playback->SetObjectField(TEXT("asset"),Ref);O->SetObjectField(TEXT("binding.playback"),Playback);
        }
    }
    return O;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Capture(UWorld* W,const FString& Map,bool Discovery)
{
    Error.Reset();if(!W || !Editor(W))return nullptr;
    if(W!=LastWorld.Get() || W->GetOutermost()->GetName()!=Map)return Fail(TEXT("Explicit approved fresh map load required")),nullptr;
    if(W->GetOutermost()->IsDirty())return Fail(TEXT("Dirty map; save and reload required")),nullptr;
    if(W->IsPartitionedWorld() || W->GetStreamingLevels().Num()!=0 || W->GetLevels().Num()!=1)return Fail(TEXT("World Partition/streaming/multiple-level profile unsupported")),nullptr;
    FString Before=Fingerprint(Map);if(!Error.IsEmpty() || Before!=LoadedFingerprint)return Fail(TEXT("Saved source drift; explicit native reload required")),nullptr;
    auto Scene=Metadata(W->GetWorldSettings());
    if(!Discovery && (!ValidateMetadata(Scene)||String(Scene,TEXT("kind"))!=TEXT("scene")))return Fail(TEXT("Explicit scene identity required on WorldSettings")),nullptr;
    FString Namespace=String(Scene,TEXT("namespace_id"));FString SceneId=String(Scene,TEXT("authoring_id"));
    auto Rows=New();TArray<TSharedPtr<FJsonValue>> Discovered;TSet<FString> Guids;
    TArray<AActor*> Actors;for(AActor* A:W->PersistentLevel->Actors)if(A && !A->HasAnyFlags(RF_Transient) && !A->IsA<ALevelScriptActor>() && A!=W->GetDefaultBrush())Actors.Add(A);
    if(Actors.Num()>10000)return Fail(TEXT("Actor inventory limit")),nullptr;
    Actors.Sort([](const AActor& A,const AActor& B){return A.GetActorGuid().ToString()<B.GetActorGuid().ToString();});
    const FString Document=W->GetOutermost()->GetPersistentGuid().ToString(EGuidFormats::Digits);
    if(!W->GetOutermost()->GetPersistentGuid().IsValid())return Fail(TEXT("Saved persistent package GUID required")),nullptr;
    for(AActor* A:Actors){
        auto Meta=Metadata(A);const bool IsScene=A==W->GetWorldSettings();
        // GetActorLabel lazily initializes an empty saved label. Resolve it before
        // fingerprinting so reading the name cannot invalidate the same capture.
        const FString ActorLabel=A->GetActorLabel();
        auto F=IsScene?New():Fields(A);if(!Error.IsEmpty())return nullptr;
        const FString Guid=A->GetActorGuid().ToString(EGuidFormats::Digits);
        auto Opaque=New();bool Critical=!IsScene && A->GetClass()!=AStaticMeshActor::StaticClass();
        if(IsScene && (W->GetWorldSettings()->DefaultGameMode || W->PersistentLevel->GetLevelScriptBlueprint(true)))Critical=true;
        for(UActorComponent* Component:A->GetComponents()){
            if(!Component || Component->HasAnyFlags(RF_Transient) || Component->IsVisualizationComponent())continue;
            if(!IsScene && Component->GetClass()!=UStaticMeshComponent::StaticClass() && Component->GetClass()!=USceneComponent::StaticClass() && Component->GetClass()!=UXaceAuthoringBinding::StaticClass())Critical=true;
            if(auto* Primitive=Cast<UPrimitiveComponent>(Component);Primitive && Primitive->GetCollisionEnabled()!=ECollisionEnabled::NoCollision)Critical=true;
        }
        FString ClassSource;
        if(UObject* Blueprint=A->GetClass()->ClassGeneratedBy){Critical=true;ClassSource=Blueprint->GetOutermost()->GetName();}
        Opaque->SetStringField(TEXT("id"),TEXT("native.properties"));Opaque->SetStringField(TEXT("sha256"),Preservation(A));Opaque->SetBoolField(TEXT("critical"),Critical);Opaque->SetStringField(TEXT("reason"),Critical?TEXT("Native class/Blueprint/physics/level behavior retained; adoption blocked ")+ClassSource:TEXT("Unowned native properties retained"));
        if(Discovery){auto D=New();D->SetStringField(TEXT("actor_guid"),Guid);D->SetStringField(TEXT("document_id"),Document);D->SetStringField(TEXT("native_path_hint"),A->GetPathName());D->SetObjectField(TEXT("fields"),F);D->SetBoolField(TEXT("registered"),ValidateMetadata(Meta));D->SetArrayField(TEXT("opaque"),{MakeShared<FJsonValueObject>(Opaque)});Discovered.Add(MakeShared<FJsonValueObject>(D));continue;}
        if(!ValidateMetadata(Meta) || String(Meta,TEXT("namespace_id"))!=Namespace || (IsScene!=(String(Meta,TEXT("kind"))==TEXT("scene"))) || Rows->HasField(String(Meta,TEXT("authoring_id"))) || !A->GetActorGuid().IsValid() || Guids.Contains(Guid))return Fail(TEXT("Missing/foreign/duplicate actor identity; recovery required: ")+A->GetPathName()+TEXT(" GUID=")+Guid+TEXT(" metadata=")+MetadataText(A)),nullptr;
        Guids.Add(Guid);auto Row=New();Row->SetObjectField(TEXT("metadata"),Meta);auto Locator=New();Locator->SetStringField(TEXT("engine"),TEXT("unreal"));Locator->SetStringField(TEXT("document_id"),Document);Locator->SetStringField(TEXT("object_id"),Guid);Row->SetObjectField(TEXT("locator"),Locator);
        Row->SetField(TEXT("scene_id"),IsScene?Null():MakeShared<FJsonValueString>(SceneId));Row->SetField(TEXT("prefab_id"),Null());Row->SetField(TEXT("parent_id"),Null());
        if(AActor* Parent=A->GetAttachParentActor()){auto PM=Metadata(Parent);if(!ValidateMetadata(PM))return Fail(TEXT("Unregistered parent actor")),nullptr;Row->SetStringField(TEXT("parent_id"),String(PM,TEXT("authoring_id")));}
        Row->SetObjectField(TEXT("fields"),F);Row->SetArrayField(TEXT("dependencies"),{});Row->SetArrayField(TEXT("opaque"),{MakeShared<FJsonValueObject>(Opaque)});Row->SetStringField(TEXT("name"),ActorLabel);Row->SetStringField(TEXT("path_hint"),Map);Rows->SetObjectField(String(Meta,TEXT("authoring_id")),Row);
    }
    for(const auto& Pair:Rows->Values){auto R=Pair.Value->AsObject();FString Parent=String(R,TEXT("parent_id"));if(!Parent.IsEmpty() && !Rows->HasField(Parent))return Fail(TEXT("Parent outside approved map")),nullptr;}
    FString After=Fingerprint(Map);if(!Error.IsEmpty() || Before!=After)return Fail(TEXT("Native source changed during capture")),nullptr;
    auto Doc=New();Doc->SetStringField(TEXT("id"),Document);Doc->SetStringField(TEXT("before"),Before);Doc->SetStringField(TEXT("after"),After);Doc->SetBoolField(TEXT("dirty"),false);
    auto Source=New();Source->SetStringField(TEXT("engine"),TEXT("unreal"));Source->SetStringField(TEXT("engine_version"),Version);Source->SetStringField(TEXT("reader_version"),TEXT("unreal.authoring.reader.v1"));Source->SetStringField(TEXT("materializer_version"),TEXT("unreal.authoring.writer.v1"));Source->SetBoolField(TEXT("play_mode"),false);Source->SetArrayField(TEXT("documents"),{MakeShared<FJsonValueObject>(Doc)});
    auto Result=New();Result->SetStringField(TEXT("schema"),Discovery?TEXT("xace.unreal_native_discovery.v1"):TEXT("xace.unreal_authoring_inventory.v1"));Result->SetObjectField(TEXT("source"),Source);
    if(Discovery)Result->SetArrayField(TEXT("actors"),Discovered);else {Result->SetStringField(TEXT("namespace_id"),Namespace);Result->SetObjectField(TEXT("objects"),Rows);}
    if(Json(Result).IsEmpty())return Fail(TEXT("Bounded capture encoding failed")),nullptr;bRescanRequired=false;return Result;
}
