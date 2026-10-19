#include "XaceAuthoringProofCommandlet.h"
#include "XaceAuthoring.h"
#include "XaceAuthoringBinding.h"
#include "Sound/SoundWave.h"
#include "GameFramework/InputSettings.h"
#include "Misc/ConfigCacheIni.h"
#include "Editor.h"
#include "FileHelpers.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/WorldSettings.h"
#include "Components/StaticMeshComponent.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "UObject/SavePackage.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/PackageName.h"
#include "Misc/EngineVersion.h"
#include "ScopedTransaction.h"
#include "Subsystems/EditorActorSubsystem.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "Engine/LevelStreamingDynamic.h"
using namespace XaceAuthoringWire;
UXaceAuthoringProofCommandlet::UXaceAuthoringProofCommandlet(){IsClient=false;IsEditor=true;IsServer=false;LogToConsole=true;}
int32 UXaceAuthoringProofCommandlet::Main(const FString& Params){FString Phase=TEXT("run");FParse::Value(*Params,TEXT("Phase="),Phase);return Run(Phase);}
namespace
{
FString IdValue(int32 N){return FString::Printf(TEXT("%032x"),N);}
Object Identity(int32 N,bool Scene=false){auto O=New();O->SetStringField(TEXT("schema"),TEXT("xace.native_identity.v1"));O->SetStringField(TEXT("namespace_id"),IdValue(100));O->SetStringField(TEXT("authoring_id"),IdValue(N));O->SetStringField(TEXT("kind"),Scene?TEXT("scene"):TEXT("object"));O->SetStringField(TEXT("generation"),TEXT("1"));return O;}
void SaveJson(const FString& Name,const Object& O){FFileHelper::SaveStringToFile(Json(O),*(FPaths::ProjectDir()/TEXT(".xace")/Name),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);}
Object ReadJson(const FString& Name){FString S;FFileHelper::LoadFileToString(S,*(FPaths::ProjectDir()/TEXT(".xace")/Name));return Parse(S);}
bool SaveAsset(UObject* Asset,const FString& Filename){FSavePackageArgs A;A.TopLevelFlags=RF_Public|RF_Standalone;A.SaveFlags=SAVE_NoError;IFileManager::Get().MakeDirectory(*FPaths::GetPath(Filename),true);return UPackage::SavePackage(Asset->GetOutermost(),Asset,*Filename,A);}
AActor* Find(UWorld* W,int32 N){for(AActor* A:W->PersistentLevel->Actors)if(A && String(Parse(FXaceUnrealAuthoring::MetadataText(A)),TEXT("authoring_id"))==IdValue(N))return A;return nullptr;}
FString Request(const Object& Inventory,const FString& Map,int32 N,const Object& Fields){auto E=New();E->SetStringField(TEXT("document"),Map);E->SetStringField(TEXT("authoring_id"),IdValue(N));E->SetObjectField(TEXT("fields"),Fields);auto R=New();R->SetStringField(TEXT("schema"),TEXT("xace.unreal_authoring_write_request.v1"));R->SetStringField(TEXT("expected_inventory_digest"),Hash(Json(Inventory)));R->SetArrayField(TEXT("edits"),{MakeShared<FJsonValueObject>(E)});return Json(R);}
Object Position(int64 X,int64 Y,int64 Z){auto O=New();O->SetStringField(TEXT("x"),LexToString(X));O->SetStringField(TEXT("y"),LexToString(Y));O->SetStringField(TEXT("z"),LexToString(Z));auto F=New();F->SetObjectField(TEXT("transform.position"),O);return F;}
}
int32 UXaceAuthoringProofCommandlet::Run(const FString& Phase)
{
    // Only the runner-created fixture project opts into these destructive fixture resets.
    if(!FPaths::FileExists(FPaths::ProjectDir()/TEXT("NEC006.fixture")))return 2;
    FXaceUnrealAuthoring Service;Service.bTrustedProject=true;TArray<TSharedPtr<FJsonValue>> Cases;bool Ok=true;
    auto Check=[&](const TCHAR* Name,bool Value){auto C=New();C->SetStringField(TEXT("name"),Name);C->SetBoolField(TEXT("ok"),Value);Cases.Add(MakeShared<FJsonValueObject>(C));Ok&=Value;UE_LOG(LogTemp,Display,TEXT("NEC006 %s %d %s"),Name,Value,*Service.Error);return Value;};
    auto Finish=[&](){auto R=New();R->SetStringField(TEXT("schema"),TEXT("xace.nec006.unreal_proof.v1"));R->SetStringField(TEXT("engine_version"),FEngineVersion::Current().ToString());R->SetBoolField(TEXT("ok"),Ok);R->SetBoolField(TEXT("commandlet"),IsRunningCommandlet());R->SetStringField(TEXT("error"),Service.Error);R->SetArrayField(TEXT("cases"),Cases);SaveJson(TEXT("proof-")+Phase+TEXT(".json"),R);return Ok?0:1;};
    const FString Map=TEXT("/Game/Fixture/World");const FString Filename=FPackageName::LongPackageNameToFilename(Map,TEXT(".umap"));
    if(Phase==TEXT("gateway")){
        if(!FPaths::FileExists(FPaths::ProjectDir()/TEXT("NEC010.fixture")))return 2;
        auto Command=ReadJson(TEXT("nec010-command.json"));const FString Action=String(Command,TEXT("action"));Object Result;
        if(Action==TEXT("capture") || Action==TEXT("prepare")){
            UWorld* W=Service.LoadApprovedMap(Map);
            if(W)Result=Action==TEXT("capture")?Service.Capture(W,Map):Service.Prepare(W,Map,Json(Child(Command,TEXT("request"))),String(Command,TEXT("transaction_id")));
        } else {
            auto Prepared=Child(Command,TEXT("prepared"));FString Directory=String(Prepared,TEXT("directory"));
            if(Action==TEXT("commit"))Result=Service.Commit(Map,Directory,String(Prepared,TEXT("approval_digest")));
            if(Action==TEXT("recover"))Result=Service.Recover(Map,Directory,FileHash(Directory/TEXT("receipt.json")));
        }
        auto Output=New();bool Success=Result.IsValid() && Service.Error.IsEmpty();Output->SetBoolField(TEXT("ok"),Success);
        Output->SetStringField(TEXT("error"),Service.Error);if(Result)Output->SetObjectField(TEXT("result"),Result);
        SaveJson(TEXT("nec010-result.json"),Output);return Success?0:1;
    }
    if(Phase==TEXT("capture")){
        UWorld* W=Service.LoadApprovedMap(Map);auto Captured=W?Service.Capture(W,Map):nullptr;
        Check(TEXT("trusted_staged_binary_extraction"),Captured.IsValid());SaveJson(TEXT("native-staged.json"),Captured);return Finish();
    }
    if(Phase==TEXT("interactive")){
        Check(TEXT("real_editor_session"),!IsRunningCommandlet());UWorld* W=Service.LoadApprovedMap(Map);if(!Check(TEXT("interactive_saved_map_load"),W!=nullptr))return Finish();
        AActor* A=Find(W,2);FString Old=FXaceUnrealAuthoring::MetadataText(A);
        Check(TEXT("editor_identity_transaction"),Service.Enroll(A,Identity(42),Old));
        Check(TEXT("editor_undo"),GEditor->UndoTransaction() && FXaceUnrealAuthoring::MetadataText(A)==Old);
        Check(TEXT("editor_redo"),GEditor->RedoTransaction() && String(Service.Metadata(A),TEXT("authoring_id"))==IdValue(42));
        Check(TEXT("dirty_map_capture_refused"),!Service.Capture(W,Map));
        GEditor->UndoTransaction();Check(TEXT("undo_restores_clean_capture"),Service.Capture(W,Map).IsValid());
        Check(TEXT("interactive_native_save"),FEditorFileUtils::SaveMap(W,Filename));W=Service.LoadApprovedMap(Map);
        Check(TEXT("interactive_save_reopen"),W && Service.Capture(W,Map).IsValid());
        return Finish();
    }
    if(Phase==TEXT("reload")){
        UWorld* W=Service.LoadApprovedMap(Map);if(!Check(TEXT("fresh_process_map_capture"),W && Service.Capture(W,Map).IsValid()))return Finish();
        auto Before=Service.Capture(W,Map);SaveJson(TEXT("native-cold.json"),Before);SaveJson(TEXT("dependencies-cold.json"),Service.DependencyInventory);Check(TEXT("cold_capture_same_identity_values"),Json(Before)==Json(ReadJson(TEXT("native-before.json"))));
        FString Text;FFileHelper::LoadFileToString(Text,*(FPaths::ProjectDir()/TEXT(".xace")/TEXT("python-request.json")));
        auto Prepared=Service.Prepare(W,Map,Text,IdValue(901));if(!Check(TEXT("python_request_native_prepare"),Prepared.IsValid()))return Finish();
        UEditorLoadingAndSavingUtils::NewBlankMap(false);W=nullptr;
        auto Committed=Service.Commit(Map,String(Prepared,TEXT("directory")),String(Prepared,TEXT("approval_digest")));if(!Check(TEXT("python_request_native_commit"),String(Committed,TEXT("state"))==TEXT("committed")))return Finish();
        W=Service.LoadApprovedMap(Map);if(!Check(TEXT("python_request_saved_reopen"),W!=nullptr))return Finish();SaveJson(TEXT("native-after-python.json"),Service.Capture(W,Map));
        UEditorLoadingAndSavingUtils::NewBlankMap(false);auto Restored=Service.Recover(Map,String(Prepared,TEXT("directory")),FileHash(String(Prepared,TEXT("directory"))/TEXT("receipt.json")));Check(TEXT("native_writer_exact_undo"),String(Restored,TEXT("state"))==TEXT("rolled_back"));return Finish();
    }
    UWorld* W=UEditorLoadingAndSavingUtils::NewBlankMap(false);if(!Check(TEXT("native_editor_world"),W!=nullptr))return Finish();
    UStaticMesh* Source=LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube"));UPackage* MeshPackage=CreatePackage(TEXT("/Game/Fixture/Mesh"));UStaticMesh* Mesh=Source?Cast<UStaticMesh>(StaticDuplicateObject(Source,MeshPackage,TEXT("Mesh"))):nullptr;
    if(!Check(TEXT("real_binary_mesh_asset"),Mesh && SaveAsset(Mesh,FPackageName::LongPackageNameToFilename(TEXT("/Game/Fixture/Mesh"),TEXT(".uasset")))))return Finish();FAssetRegistryModule::AssetCreated(Mesh);
    UStaticMesh* OtherSource=LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Sphere.Sphere"));UPackage* OtherPackage=CreatePackage(TEXT("/Game/Fixture/OtherMesh"));
    UStaticMesh* OtherMesh=OtherSource?Cast<UStaticMesh>(StaticDuplicateObject(OtherSource,OtherPackage,TEXT("OtherMesh"))):nullptr;
    if(!Check(TEXT("second_binary_mesh_asset"),OtherMesh && SaveAsset(OtherMesh,FPackageName::LongPackageNameToFilename(TEXT("/Game/Fixture/OtherMesh"),TEXT(".uasset")))))return Finish();FAssetRegistryModule::AssetCreated(OtherMesh);
    // Authoring-only audio asset: no audible playback certification is claimed.
    UPackage* ClipPackage=CreatePackage(TEXT("/Game/Fixture/Clip"));auto* Clip=NewObject<USoundWave>(ClipPackage,TEXT("Clip"),RF_Public|RF_Standalone);
    if(!Check(TEXT("saved_audio_declaration_resource"),SaveAsset(Clip,FPackageName::LongPackageNameToFilename(TEXT("/Game/Fixture/Clip"),TEXT(".uasset")))))return Finish();FAssetRegistryModule::AssetCreated(Clip);
    FString InputConfig=TEXT("[/Script/Engine.InputSettings]\n+ActionMappings=(ActionName=\"XaceMove\",Key=SpaceBar)\n+ActionMappings=(ActionName=\"XaceOther\",Key=Enter)\n");
    if(!Check(TEXT("declared_input_config_saved"),FFileHelper::SaveStringToFile(InputConfig,*(FPaths::ProjectConfigDir()/TEXT("DefaultInput.ini")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)))return Finish();
    FConfigCacheIni::LoadGlobalIniFile(GInputIni,TEXT("Input"),nullptr,true);GetMutableDefault<UInputSettings>()->ReloadConfig();
    Check(TEXT("scene_identity_enrollment"),Service.Enroll(W->GetWorldSettings(),Identity(1,true)));
    for(int32 N=2;N<=3;++N){auto* A=W->SpawnActor<AStaticMeshActor>();A->SetActorLabel(TEXT("Ordinary Name"));A->Tags.Add(FName(TEXT("literal:/Game/Fixture/World.World:keep")));A->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);A->GetStaticMeshComponent()->SetStaticMesh(Mesh);A->GetStaticMeshComponent()->SetCollisionProfileName(TEXT("NoCollision"));A->SetActorLocation(FVector(300,100*N,200));Check(N==2?TEXT("actor_one_enrollment"):TEXT("actor_two_enrollment"),Service.Enroll(A,Identity(N)));}
    auto* Binding=NewObject<UXaceAuthoringBinding>(Find(W,2),TEXT("ExplicitAuthoringBinding"));Binding->InputAction=TEXT("XaceMove");Binding->BindingId=TEXT("walk");Binding->EventName=TEXT("actor.walk");Binding->PlaybackKind=TEXT("Audio");Binding->Resource=Clip;Find(W,2)->AddInstanceComponent(Binding);Binding->RegisterComponent();
    if(!Check(TEXT("binary_map_native_save"),FEditorFileUtils::SaveMap(W,Filename)))return Finish();W=Service.LoadApprovedMap(Map);
    if(!Check(TEXT("saved_native_map_reload"),W!=nullptr))return Finish();SaveJson(TEXT("pre-enrollment-discovery.json"),Service.Capture(W,Map,true));auto Inventory=Service.Capture(W,Map);
    if(!Check(TEXT("meaningful_native_capture"),Inventory && Child(Inventory,TEXT("objects"))->Values.Num()==3))return Finish();SaveJson(TEXT("native-before.json"),Inventory);
    Check(TEXT("duplicate_labels_distinct_guids"),Find(W,2)->GetActorGuid()!=Find(W,3)->GetActorGuid());auto Discovery=Service.Capture(W,Map,true);Check(TEXT("actual_native_discovery"),Discovery.IsValid());SaveJson(TEXT("native-discovery.json"),Discovery);
    FString UnownedBeforeMesh=Service.Preservation(Find(W,2));
    SaveJson(TEXT("preservation-before-resource.json"),Service.PreservationProperties(W->GetWorldSettings()));
    SaveJson(TEXT("actor-preservation-before-resource.json"),Service.PreservationProperties(Find(W,2)));
    auto ChangedFields=Position(8000000,2000000,-3000000);ChangedFields->SetObjectField(TEXT("presentation.asset"),Service.Asset(LoadObject<UStaticMesh>(nullptr,TEXT("/Game/Fixture/OtherMesh.OtherMesh"))));
    SaveJson(TEXT("preservation-after-resource.json"),Service.PreservationProperties(W->GetWorldSettings()));
    SaveJson(TEXT("actor-preservation-after-resource.json"),Service.PreservationProperties(Find(W,2)));
    SaveJson(TEXT("native-before-prepare.json"),Service.Capture(W,Map));
    ChangedFields->SetStringField(TEXT("input.action"),TEXT("XaceOther"));auto Playback=New();Playback->SetStringField(TEXT("binding_id"),TEXT("walk"));Playback->SetStringField(TEXT("event_name"),TEXT("actor.reviewed"));Playback->SetStringField(TEXT("playback_kind"),TEXT("Audio"));Playback->SetObjectField(TEXT("asset"),Service.Asset(LoadObject<USoundWave>(nullptr,TEXT("/Game/Fixture/Clip.Clip"))));ChangedFields->SetObjectField(TEXT("binding.playback"),Playback);
    auto Prepared=Service.Prepare(W,Map,Request(Inventory,Map,2,ChangedFields),IdValue(800));
    if(!Check(TEXT("native_staged_save_readback"),Prepared.IsValid()))return Finish();
    FString BeforeHash=FileHash(Filename);Check(TEXT("prepare_keeps_original"),BeforeHash==String(Child(Prepared,TEXT("receipt")),TEXT("before")));
    Check(TEXT("loaded_map_commit_refused"),!Service.Commit(Map,String(Prepared,TEXT("directory")),String(Prepared,TEXT("approval_digest"))));
    UEditorLoadingAndSavingUtils::NewBlankMap(false);W=nullptr;
    Check(TEXT("wrong_approval_refused"),!Service.Commit(Map,String(Prepared,TEXT("directory")),FString::ChrN(64,'0')));
    auto Committed=Service.Commit(Map,String(Prepared,TEXT("directory")),String(Prepared,TEXT("approval_digest")));
    if(!Check(TEXT("approved_native_commit"),String(Committed,TEXT("state"))==TEXT("committed")))return Finish();
    W=Service.LoadApprovedMap(Map);if(!Check(TEXT("committed_binary_reopen"),W!=nullptr))return Finish();
    Check(TEXT("saved_actor_position"),Find(W,2)->GetActorLocation().Equals(FVector(300,800,200),0));
    Check(TEXT("saved_native_mesh_replacement"),Cast<AStaticMeshActor>(Find(W,2))->GetStaticMeshComponent()->GetStaticMesh()->GetPathName()==TEXT("/Game/Fixture/OtherMesh.OtherMesh"));
    Check(TEXT("mesh_change_preserves_unowned_properties"),Service.Preservation(Find(W,2))==UnownedBeforeMesh);
    Check(TEXT("input_selector_saved"),Find(W,2)->FindComponentByClass<UXaceAuthoringBinding>()->InputAction==TEXT("XaceOther"));
    Check(TEXT("playback_declaration_saved"),Find(W,2)->FindComponentByClass<UXaceAuthoringBinding>()->EventName==TEXT("actor.reviewed"));
    Check(TEXT("unknown_actor_label_preserved"),Find(W,2)->GetActorLabel()==TEXT("Ordinary Name"));
    Check(TEXT("literal_package_text_preserved"),Find(W,2)->Tags.Contains(FName(TEXT("literal:/Game/Fixture/World.World:keep"))));
    UEditorLoadingAndSavingUtils::NewBlankMap(false);auto Restored=Service.Recover(Map,String(Prepared,TEXT("directory")),FileHash(String(Prepared,TEXT("directory"))/TEXT("receipt.json")));
    Check(TEXT("receipt_reload_recovery"),String(Restored,TEXT("state"))==TEXT("rolled_back"));Check(TEXT("rollback_exact_binary_bytes"),FileHash(Filename)==BeforeHash);
    W=Service.LoadApprovedMap(Map);Inventory=Service.Capture(W,Map);
    // Fail-closed gates against real native objects and saved binary packages.
    FXaceUnrealAuthoring Untrusted;Check(TEXT("untrusted_editor_refused"),!Untrusted.LoadApprovedMap(Map));
    Check(TEXT("map_path_traversal_refused"),Service.MapFilename(TEXT("/Game/../Fixture/World")).IsEmpty());
    Check(TEXT("noncanonical_numeric_json_refused"),!Parse(TEXT("{\"x\":1}")));
    Check(TEXT("duplicate_json_keys_refused"),!Parse(TEXT("{\"x\":\"1\",\"x\":\"2\"}")));
    EWorldType::Type OriginalType=W->WorldType;W->WorldType=EWorldType::PIE;
    Check(TEXT("pie_world_capture_refused"),!Service.Capture(W,Map));W->WorldType=OriginalType;
    auto* Streaming=NewObject<ULevelStreamingDynamic>(W);W->AddStreamingLevel(Streaming);
    Check(TEXT("streaming_level_profile_refused"),!Service.Capture(W,Map));W->RemoveStreamingLevel(Streaming);
    auto Invalid=New();Invalid->SetStringField(TEXT("native.name"),TEXT("overwrite"));
    Check(TEXT("native_owned_write_refused"),!Service.Prepare(W,Map,Request(Inventory,Map,2,Invalid),IdValue(810)));
    Check(TEXT("unsafe_transaction_id_refused"),!Service.Prepare(W,Map,Request(Inventory,Map,2,Position(8000000,2000000,-3000000)),TEXT("../escape")));
    auto Fault=Service.Prepare(W,Map,Request(Inventory,Map,2,Position(8000000,2000000,-3000000)),IdValue(811));
    if(!Check(TEXT("fault_prepare"),Fault.IsValid()))return Finish();
    UEditorLoadingAndSavingUtils::NewBlankMap(false);
    auto FaultResult=Service.Commit(Map,String(Fault,TEXT("directory")),String(Fault,TEXT("approval_digest")),true);
    Check(TEXT("injected_failure_exact_rollback"),String(FaultResult,TEXT("state"))==TEXT("rolled_back") && FileHash(Filename)==BeforeHash);
    W=Service.LoadApprovedMap(Map);Inventory=Service.Capture(W,Map);
    auto ResourceApproval=Service.Prepare(W,Map,Request(Inventory,Map,2,ChangedFields),IdValue(815));
    if(!Check(TEXT("replacement_resource_approval"),ResourceApproval.IsValid()))return Finish();
    OtherMesh=LoadObject<UStaticMesh>(nullptr,TEXT("/Game/Fixture/OtherMesh.OtherMesh"));OtherMesh->SetLightMapResolution(128);OtherMesh->MarkPackageDirty();
    Check(TEXT("replacement_resource_native_resave"),SaveAsset(OtherMesh,FPackageName::LongPackageNameToFilename(TEXT("/Game/Fixture/OtherMesh"),TEXT(".uasset"))));
    UEditorLoadingAndSavingUtils::NewBlankMap(false);
    Check(TEXT("replacement_resource_drift_refused"),!Service.Commit(Map,String(ResourceApproval,TEXT("directory")),String(ResourceApproval,TEXT("approval_digest"))));
    W=Service.LoadApprovedMap(Map);Inventory=Service.Capture(W,Map);
    auto Stale=Service.Prepare(W,Map,Request(Inventory,Map,2,Position(8000000,2000000,-3000000)),IdValue(812));
    if(!Check(TEXT("dependency_guard_prepare"),Stale.IsValid()))return Finish();
    FString Config=FPaths::ProjectConfigDir()/TEXT("NEC006Drift.ini");FFileHelper::SaveStringToFile(TEXT("[Fixture]\nValue=changed\n"),*Config);
    Check(TEXT("config_drift_capture_refused"),!Service.Capture(W,Map));UEditorLoadingAndSavingUtils::NewBlankMap(false);
    Check(TEXT("dependency_drift_commit_refused"),!Service.Commit(Map,String(Stale,TEXT("directory")),String(Stale,TEXT("approval_digest"))));
    IFileManager::Get().Delete(*Config);W=Service.LoadApprovedMap(Map);
    // Actual editor duplication copies enrollment but creates a different actor GUID.
    FActorSpawnParameters DuplicateParameters;DuplicateParameters.Template=Find(W,2);
    AActor* Duplicate=W->SpawnActor<AStaticMeshActor>(DuplicateParameters);
    if(!Check(TEXT("native_actor_duplicate"),Duplicate && Duplicate->GetActorGuid()!=Find(W,2)->GetActorGuid()))return Finish();
    FString DuplicateOld=FXaceUnrealAuthoring::MetadataText(Duplicate);
    Check(TEXT("duplicate_metadata_copied"),DuplicateOld==FXaceUnrealAuthoring::MetadataText(Find(W,2)));
    Check(TEXT("duplicate_binary_save"),FEditorFileUtils::SaveMap(W,Filename));W=Service.LoadApprovedMap(Map);
    Check(TEXT("duplicate_authoring_identity_refused"),!Service.Capture(W,Map));
    Duplicate=nullptr;for(AActor* A:W->PersistentLevel->Actors)if(A && FXaceUnrealAuthoring::MetadataText(A)==DuplicateOld && A!=Find(W,2)){Duplicate=A;break;}
    if(!Check(TEXT("explicit_duplicate_rekey"),Duplicate && Service.Enroll(Duplicate,Identity(4),DuplicateOld)))return Finish();
    FGuid RekeyGuid=Duplicate->GetActorGuid();Check(TEXT("rekey_native_save"),FEditorFileUtils::SaveMap(W,Filename));W=Service.LoadApprovedMap(Map);
    Check(TEXT("rekey_saved_reopen"),Service.Capture(W,Map).IsValid() && Find(W,4)->GetActorGuid()==RekeyGuid);
    AActor* A=Find(W,4);A->Modify();A->SetActorLabel(TEXT("Renamed Native Instance"));A->AttachToActor(Find(W,3),FAttachmentTransformRules::KeepRelativeTransform);A->MarkPackageDirty();
    Check(TEXT("rename_parent_native_save"),FEditorFileUtils::SaveMap(W,Filename));W=Service.LoadApprovedMap(Map);auto Reparented=Service.Capture(W,Map);SaveJson(TEXT("native-reparented.json"),Reparented);
    Check(TEXT("rename_parent_identity_stable"),Reparented && Find(W,4)->GetActorGuid()==RekeyGuid && String(Child(Child(Reparented,TEXT("objects")),IdValue(4)),TEXT("parent_id"))==IdValue(3));
    // A saved Blueprint instance remains opaque; byte drift requires recapture.
    UPackage* BPkg=CreatePackage(TEXT("/Game/Fixture/Behavior"));
    UBlueprint* BP=FKismetEditorUtilities::CreateBlueprint(AActor::StaticClass(),BPkg,TEXT("Behavior"),BPTYPE_Normal,UBlueprint::StaticClass(),UBlueprintGeneratedClass::StaticClass());
    if(!Check(TEXT("native_blueprint_created"),BP!=nullptr))return Finish();
    FKismetEditorUtilities::CompileBlueprint(BP);FAssetRegistryModule::AssetCreated(BP);
    FString BPFile=FPackageName::LongPackageNameToFilename(TEXT("/Game/Fixture/Behavior"),TEXT(".uasset"));
    Check(TEXT("binary_blueprint_asset_save"),SaveAsset(BP,BPFile));AActor* Instance=W->SpawnActor<AActor>(BP->GeneratedClass);
    Check(TEXT("blueprint_instance_enrollment"),Service.Enroll(Instance,Identity(5)));
    Check(TEXT("blueprint_map_save"),FEditorFileUtils::SaveMap(W,Filename));W=Service.LoadApprovedMap(Map);auto Unknown=Service.Capture(W,Map);SaveJson(TEXT("native-unknown.json"),Unknown);
    Check(TEXT("blueprint_instance_opaque"),Unknown && Child(Child(Unknown,TEXT("objects")),IdValue(5))->GetArrayField(TEXT("opaque"))[0]->AsObject()->GetBoolField(TEXT("critical")));
    FString OldFingerprint=Service.Fingerprint(Map);BP=LoadObject<UBlueprint>(nullptr,TEXT("/Game/Fixture/Behavior.Behavior"));BP->BlueprintDescription=TEXT("Changed native behavior inventory");BP->MarkPackageDirty();
    Check(TEXT("dirty_blueprint_dependency_refused"),!Service.Capture(W,Map));Check(TEXT("changed_blueprint_saved"),SaveAsset(BP,BPFile));
    Check(TEXT("saved_blueprint_drift_detected"),Service.Fingerprint(Map)!=OldFingerprint && !Service.Capture(W,Map));
    // Preserve a newer native map rather than overwriting it with an old before-image.
    UEditorLoadingAndSavingUtils::NewBlankMap(false);FString NewerHash=FileHash(Filename);
    auto Conflict=Service.Recover(Map,String(Prepared,TEXT("directory")),FileHash(String(Prepared,TEXT("directory"))/TEXT("receipt.json")));
    Check(TEXT("newer_native_edit_preserved"),String(Conflict,TEXT("state"))==TEXT("recovery_conflict") && FileHash(Filename)==NewerHash);
    // Reset only this explicit fixture to the retained original bytes for cold proof.
    Check(TEXT("fixture_original_restored"),IFileManager::Get().Copy(*Filename,*(String(Prepared,TEXT("directory"))/TEXT("before.umap")),true,true)==COPY_OK && FileHash(Filename)==BeforeHash);
    W=Service.LoadApprovedMap(Map);SaveJson(TEXT("native-before.json"),Service.Capture(W,Map));SaveJson(TEXT("dependencies-before.json"),Service.DependencyInventory);return Finish();
}
