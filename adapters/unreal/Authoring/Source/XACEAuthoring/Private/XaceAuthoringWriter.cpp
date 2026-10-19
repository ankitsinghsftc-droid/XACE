#include "XaceAuthoring.h"
#include "XaceAuthoringBinding.h"
#include "GameFramework/WorldSettings.h"
#include "Engine/LevelScriptActor.h"
#include "Editor.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "Engine/StaticMeshActor.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/ScopeExit.h"
#include "UObject/Package.h"
#include "Misc/PackagePath.h"
#include "Misc/PackageName.h"
#include "Windows/WindowsHWrapper.h"
#include "UObject/SavePackage.h"
#include "HAL/PlatformFileManager.h"
using namespace XaceAuthoringWire;
namespace
{
bool Raw(const Object& O,const TCHAR* K,int64& V)
{
    FString S=String(O,K);return !S.IsEmpty() && S.Len()<=20 && LexTryParseString(V,*S) && LexToString(V)==S && V>=-8192000000LL && V<=8192000000LL;
}
bool Inverse(const Object& O,FVector& V,bool Scale)
{
    int64 X,Y,Z;if(!O || O->Values.Num()!=3 || !Raw(O,TEXT("x"),X)||!Raw(O,TEXT("y"),Y)||!Raw(O,TEXT("z"),Z))return false;
    V=Scale?FVector(double(Z),double(X),double(Y))/1e6:FVector(-double(Z),double(X),double(Y))/1e4;
    return !Scale || (V.X>0 && V.Y>0 && V.Z>0);
}
bool NativeSave(UPackage* Package,UObject* Asset,const FString& Filename)
{
    FSavePackageArgs Args;Args.TopLevelFlags=RF_Public|RF_Standalone;// This is a temporary autosave of the same package, not Save As.
    Args.SaveFlags=SAVE_NoError|SAVE_KeepDirty|SAVE_FromAutosave;
    return UPackage::SavePackage(Package,Asset,*Filename,Args);
}
FString TransactionRoot(){return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir()/TEXT(".xace/XACEAuthoring/Transactions"));}
bool Confined(const FString& Path,const FString& Root)
{
    FString Full=FPaths::ConvertRelativePathToFull(Path);FPaths::NormalizeFilename(Full);FString Base=FPaths::ConvertRelativePathToFull(Root);FPaths::NormalizeFilename(Base);
    if(!Full.StartsWith(Base+TEXT("/")) || Full.Contains(TEXT("/../")))return false;
    auto& P=FPlatformFileManager::Get().GetPlatformFile();FString Current=Full;
    while(Current.Len()>=Base.Len()){if(P.IsSymlink(*Current)==ESymlinkResult::Symlink)return false;FString Next=FPaths::GetPath(Current);if(Next==Current)break;Current=Next;}return true;
}
bool Copy(const FString& Dest,const FString& Source){return IFileManager::Get().Copy(*Dest,*Source,true,true)==COPY_OK;}
bool Replace(const FString& Dest,const FString& Source){return ::MoveFileExW(*FPaths::ConvertRelativePathToFull(Source),*FPaths::ConvertRelativePathToFull(Dest),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;}
}
bool FXaceUnrealAuthoring::Apply(AActor* A,const Object& F)
{
    if(!A || A->GetClass()!=AStaticMeshActor::StaticClass() || !F || !A->GetRootComponent())return Fail(TEXT("Native writer supports existing StaticMeshActor fields only"));
    for(const auto& Pair:F->Values){
        const FString& K=Pair.Key;
        if(K==TEXT("transform.position")||K==TEXT("transform.scale")){
            FVector V;if(!Inverse(Child(F,K),V,K==TEXT("transform.scale")))return Fail(TEXT("Invalid inverse vector"));
            if(K==TEXT("transform.position"))A->GetRootComponent()->SetRelativeLocation(V);else A->GetRootComponent()->SetRelativeScale3D(V);
        }else if(K==TEXT("transform.rotation")){
            auto Q=Child(F,K);int64 X,Y,Z,W;if(!Q||Q->Values.Num()!=4||!Raw(Q,TEXT("x"),X)||!Raw(Q,TEXT("y"),Y)||!Raw(Q,TEXT("z"),Z)||!Raw(Q,TEXT("w"),W))return Fail(TEXT("Invalid inverse quaternion"));
            FQuat Rotation(double(Z)/1e6,-double(X)/1e6,-double(Y)/1e6,double(W)/1e6);if(FMath::Abs(Rotation.SizeSquared()-1)>0.000004)return Fail(TEXT("Nonunit quaternion"));
            A->GetRootComponent()->SetRelativeRotation(Rotation);
        }else if(K==TEXT("presentation.asset")){
            auto Ref=Child(F,K);FString Path=String(Ref,TEXT("resolved_path"));if(!Path.StartsWith(TEXT("/Game/")))return Fail(TEXT("Project mesh resource required"));
            auto* Mesh=LoadObject<UStaticMesh>(nullptr,*Path);auto Actual=Asset(Mesh);
            if(!Actual || Json(Actual)!=Json(Ref))return Fail(TEXT("Resource identity/type mismatch"));
            CastChecked<AStaticMeshActor>(A)->GetStaticMeshComponent()->SetStaticMesh(Mesh);
        }else if(K==TEXT("input.action")){
            auto* Binding=A->FindComponentByClass<UXaceAuthoringBinding>();FString Value=String(F,K);
            if(!Binding || Binding->InputAction.IsEmpty() || Value.IsEmpty() || Value.Len()>128)return Fail(TEXT("Existing explicit input selector required"));
            Binding->InputAction=Value;
        }else if(K==TEXT("binding.playback")){
            auto* Binding=A->FindComponentByClass<UXaceAuthoringBinding>();auto Value=Child(F,K);auto Ref=Child(Value,TEXT("asset"));FString Path=String(Ref,TEXT("resolved_path"));
            if(!Binding || Binding->BindingId.IsEmpty() || !Value || Value->Values.Num()!=4 || String(Value,TEXT("binding_id"))!=Binding->BindingId || !Path.StartsWith(TEXT("/Game/")))return Fail(TEXT("Existing explicit playback identity required"));
            UObject* Resource=LoadObject<UObject>(nullptr,*Path);auto Actual=Asset(Resource);
            if(!Actual || Json(Actual)!=Json(Ref))return Fail(TEXT("Playback resource identity/type mismatch"));
            Binding->EventName=String(Value,TEXT("event_name"));Binding->PlaybackKind=String(Value,TEXT("playback_kind"));Binding->Resource=Resource;
        }else return Fail(TEXT("Field not writable: ")+K);
    }
    return VerifyFields(A,F);
}
bool FXaceUnrealAuthoring::VerifyFields(AActor* A,const Object& F)
{
    auto Actual=Fields(A);if(!Error.IsEmpty())return false;
    FTransform T=A->GetRootComponent()->GetRelativeTransform();
    for(const auto& Pair:F->Values){FString K=Pair.Key;
        if(K==TEXT("input.action")){if(String(Actual,K)!=String(F,K))return Fail(TEXT("Saved input selector mismatch"));continue;}
        if(K==TEXT("presentation.asset") || K==TEXT("binding.playback")){if(Json(Child(Actual,K))!=Json(Child(F,K)))return Fail(TEXT("Saved asset readback mismatch"));continue;}
        auto Expected=Child(F,K);if(!Expected)return Fail(TEXT("Invalid numeric field"));
        TArray<double> Values;
        if(K==TEXT("transform.rotation")){FQuat Q=T.GetRotation();Values={-Q.Y*1e6,-Q.Z*1e6,Q.X*1e6,Q.W*1e6};double Sign=Values[3]!=0?Values[3]:(Values[0]!=0?Values[0]:(Values[1]!=0?Values[1]:Values[2]));if(Sign<0)for(double& V:Values)V=-V;}
        else {FVector V=K==TEXT("transform.scale")?T.GetScale3D():T.GetLocation();Values=K==TEXT("transform.scale")?TArray<double>{V.Y*1e6,V.Z*1e6,V.X*1e6}:TArray<double>{V.Y*1e4,V.Z*1e4,-V.X*1e4};}
        TArray<FString> Axes={TEXT("x"),TEXT("y"),TEXT("z"),TEXT("w")};
        for(int32 I=0;I<Values.Num();++I){int64 R;if(!Raw(Expected,*Axes[I],R)||!FMath::IsFinite(Values[I])||Values[I]!=double(R))return Fail(TEXT("Native numeric readback cannot preserve fixed value"));}
    }
    return true;
}
bool FXaceUnrealAuthoring::Persist(const FString& Dir,const Object& R)
{
    FString Text=Json(R);if(Text.IsEmpty() || !FFileHelper::SaveStringToFile(Text,*(Dir/TEXT("receipt.next")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM) || !Replace(Dir/TEXT("receipt.json"),Dir/TEXT("receipt.next")))return Fail(TEXT("Receipt persistence failed; retain before-images"));return true;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Prepare(UWorld* W,const FString& Map,const FString& Request,const FString& Tx)
{
    Error.Reset();auto Inventory=Capture(W,Map);if(!Inventory)return nullptr;
    auto R=Parse(Request);const TArray<TSharedPtr<FJsonValue>>* Edits=nullptr;
    if(!Id(Tx)||!R||R->Values.Num()!=3||String(R,TEXT("schema"))!=TEXT("xace.unreal_authoring_write_request.v1")||String(R,TEXT("expected_inventory_digest"))!=Hash(Json(Inventory))||!R->TryGetArrayField(TEXT("edits"),Edits)||Edits->IsEmpty()||Edits->Num()>10000)return Fail(TEXT("Invalid/stale native writer request")),nullptr;
    FString Dir=TransactionRoot()/Tx;if(!Confined(Dir,TransactionRoot())||IFileManager::Get().DirectoryExists(*Dir))return Fail(TEXT("Unsafe/reused transaction directory")),nullptr;
    TMap<FString,AActor*> Actors;for(AActor* A:W->PersistentLevel->Actors)if(A)Actors.Add(String(Metadata(A),TEXT("authoring_id")),A);
    TSet<FString> Seen;for(const auto& E:*Edits){auto O=E->AsObject();FString IdValue=String(O,TEXT("authoring_id"));if(!O||O->Values.Num()!=3||String(O,TEXT("document"))!=Map||!Actors.Contains(IdValue)||Seen.Contains(IdValue)||!Child(O,TEXT("fields"))||Child(O,TEXT("fields"))->Values.IsEmpty())return Fail(TEXT("Invalid duplicate/out-of-scope edit")),nullptr;Seen.Add(IdValue);}
    auto Resources=New();
    for(const auto& E:*Edits){auto FieldsValue=Child(E->AsObject(),TEXT("fields"));
        for(auto Ref:{Child(FieldsValue,TEXT("presentation.asset")),Child(Child(FieldsValue,TEXT("binding.playback")),TEXT("asset"))})if(Ref){FString Name=FPackageName::ObjectPathToPackageName(String(Ref,TEXT("resolved_path")));FString Stamp=Fingerprint(Name,true);if(Stamp.IsEmpty()||!Error.IsEmpty())return nullptr;Resources->SetStringField(Name,Stamp);}}

    if(!IFileManager::Get().MakeDirectory(*Dir,true))return Fail(TEXT("Transaction directory unavailable")),nullptr;
    FString Original=MapFilename(Map),Stage=Dir/TEXT("staged.umap"),Backup=Dir/TEXT("before.umap");
    if(!Copy(Backup,Original))return Fail(TEXT("Before-image preparation failed")),nullptr;
    UPackage* Package=W->GetOutermost();FPackagePath OriginalPath=Package->GetLoadedPath();FGuid OriginalGuid=Package->GetPersistentGuid();
    TMap<AActor*,FTransform> Transforms;TMap<AStaticMeshActor*,UStaticMesh*> Meshes;
    for(const auto& E:*Edits){auto O=E->AsObject();AActor* A=Actors[String(O,TEXT("authoring_id"))];if(!A->GetRootComponent())return Fail(TEXT("Missing native root")),nullptr;Transforms.Add(A,A->GetRootComponent()->GetRelativeTransform());if(auto* M=Cast<AStaticMeshActor>(A))Meshes.Add(M,M->GetStaticMeshComponent()->GetStaticMesh());}
    struct FBindingState { FString InputAction,BindingId,EventName,PlaybackKind; UObject* Resource; };
    TMap<UXaceAuthoringBinding*,FBindingState> BindingStates;
    for(const auto& E:*Edits)if(auto* B=Actors[String(E->AsObject(),TEXT("authoring_id"))]->FindComponentByClass<UXaceAuthoringBinding>())BindingStates.Add(B,{B->InputAction,B->BindingId,B->EventName,B->PlaybackKind,B->Resource});
    TMap<FString,FString> ExpectedStored;
    auto Stored=[&](AActor* A){auto Value=New();A->GetActorLabel();Value->SetObjectField(TEXT("fields"),A->IsA<AWorldSettings>()?New():Fields(A));Value->SetObjectField(TEXT("unowned"),PreservationProperties(A));return Json(Value);};
    auto Included=[](UWorld* World,AActor* A){return A && !A->HasAnyFlags(RF_Transient) && !A->IsA<ALevelScriptActor>() && A!=World->GetDefaultBrush();};
    bool Saved=false;
    {
        ON_SCOPE_EXIT {for(const auto& P:BindingStates){auto* B=P.Key;const auto& V=P.Value;B->InputAction=V.InputAction;B->BindingId=V.BindingId;B->EventName=V.EventName;B->PlaybackKind=V.PlaybackKind;B->Resource=V.Resource;}for(const auto& P:Transforms)P.Key->GetRootComponent()->SetRelativeTransform(P.Value);for(const auto& P:Meshes)P.Key->GetStaticMeshComponent()->SetStaticMesh(P.Value);Package->SetLoadedPath(OriginalPath);Package->SetPersistentGuid(OriginalGuid);Package->SetDirtyFlag(false);};
        for(const auto& E:*Edits){auto O=E->AsObject();if(!Apply(Actors[String(O,TEXT("authoring_id"))],Child(O,TEXT("fields"))))return nullptr;}
        for(AActor* A:W->PersistentLevel->Actors)if(Included(W,A))ExpectedStored.Add(A->GetActorGuid().ToString(EGuidFormats::Digits),Stored(A));
        Saved=NativeSave(Package,W,Stage);
    }
    if(!Saved)return Fail(TEXT("Native staged map serialization failed")),nullptr;
    // Load the binary stage into a separate transient package for saved readback.
    const FString VerifyMount=TEXT("/XACEVerify_")+Tx+TEXT("/");
    const FString VerifyDirectory=Dir+TEXT("/");
    FPackageName::RegisterMountPoint(VerifyMount,VerifyDirectory);
    ON_SCOPE_EXIT {FPackageName::UnRegisterMountPoint(VerifyMount,VerifyDirectory);};
    UPackage* Loaded=LoadPackage(nullptr,*(VerifyMount+TEXT("staged")),LOAD_None);UWorld* Verified=Loaded?UWorld::FindWorldInPackage(Loaded):nullptr;
    if(!Verified)return Fail(TEXT("Staged binary map reopen failed")),nullptr;
    if(Loaded->GetPersistentGuid()!=OriginalGuid)return Fail(TEXT("Staged package identity changed")),nullptr;
    TMap<FString,FString> ActualStored;
    for(AActor* A:Verified->PersistentLevel->Actors)if(Included(Verified,A))ActualStored.Add(A->GetActorGuid().ToString(EGuidFormats::Digits),Stored(A));
    auto ExpectedEvidence=New(),ActualEvidence=New();
    for(const auto& Entry:ExpectedStored)ExpectedEvidence->SetObjectField(Entry.Key,Parse(Entry.Value));
    for(const auto& Entry:ActualStored)ActualEvidence->SetObjectField(Entry.Key,Parse(Entry.Value));
    if(Json(ExpectedEvidence).IsEmpty() || Json(ActualEvidence).IsEmpty() || !FFileHelper::SaveStringToFile(Json(ExpectedEvidence),*(Dir/TEXT("stored-before-save.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM) || !FFileHelper::SaveStringToFile(Json(ActualEvidence),*(Dir/TEXT("stored-after-save.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))return Fail(TEXT("Stored-property stage evidence unavailable")),nullptr;
    if(ActualStored.Num()!=ExpectedStored.Num())return Fail(TEXT("Staged actor set changed")),nullptr;
    for(const auto& Entry:ExpectedStored)if(!ActualStored.Contains(Entry.Key)||ActualStored[Entry.Key]!=Entry.Value)return Fail(TEXT("Staged stored properties changed")),nullptr;
    TMap<FString,AActor*> SavedActors;for(AActor* A:Verified->PersistentLevel->Actors)if(A)SavedActors.Add(String(Metadata(A),TEXT("authoring_id")),A);
    for(const auto& E:*Edits){auto O=E->AsObject();FString IdValue=String(O,TEXT("authoring_id"));if(!SavedActors.Contains(IdValue)||!VerifyFields(SavedActors[IdValue],Child(O,TEXT("fields"))))return Fail(TEXT("Saved native identity/field readback failed")),nullptr;}
    auto After=Capture(W,Map);FFileHelper::SaveStringToFile(Json(Inventory),*(Dir/TEXT("inventory-before.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);FFileHelper::SaveStringToFile(Json(After),*(Dir/TEXT("inventory-after-prepare.json")),FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);if(!After||Hash(Json(After))!=Hash(Json(Inventory))||FileHash(Original)!=FileHash(Backup))return Fail(TEXT("Original changed during preparation")),nullptr;
    for(const auto& P:Resources->Values)if(Fingerprint(P.Key,true)!=P.Value->AsString())return Fail(TEXT("Replacement resource drift during prepare")),nullptr;
    auto ReceiptValue=New();ReceiptValue->SetObjectField(TEXT("resources"),Resources);ReceiptValue->SetStringField(TEXT("schema"),TEXT("xace.unreal_native_transaction.v1"));ReceiptValue->SetStringField(TEXT("transaction_id"),Tx);ReceiptValue->SetStringField(TEXT("map"),Map);ReceiptValue->SetStringField(TEXT("state"),TEXT("prepared"));ReceiptValue->SetStringField(TEXT("before"),FileHash(Backup));ReceiptValue->SetStringField(TEXT("after"),FileHash(Stage));ReceiptValue->SetStringField(TEXT("dependency_fingerprint"),Fingerprint(Map));ReceiptValue->SetArrayField(TEXT("edits"),*Edits);
    if(!Persist(Dir,ReceiptValue))return nullptr;auto Result=New();Result->SetStringField(TEXT("directory"),Dir);Result->SetStringField(TEXT("approval_digest"),Hash(Json(ReceiptValue)));Result->SetObjectField(TEXT("receipt"),ReceiptValue);return Result;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Receipt(const FString& Map,const FString& Dir,const FString& Digest)
{
    if(!Editor()||!Confined(Dir,TransactionRoot())||FPaths::GetPath(Dir)!=TransactionRoot()||!Id(FPaths::GetCleanFilename(Dir)))return Fail(TEXT("Invalid native recovery scope")),nullptr;
    UWorld* Current=GEditor->GetEditorWorldContext().World();if(Current && Current->GetOutermost()->GetName()==Map)return Fail(TEXT("Unload approved map before commit/recovery; never discard editor buffers")),nullptr;
    if(UPackage* P=FindPackage(nullptr,*Map);P && P->IsDirty())return Fail(TEXT("Dirty approved package")),nullptr;
    FString Text;if(!FFileHelper::LoadFileToString(Text,*(Dir/TEXT("receipt.json"))))return Fail(TEXT("Missing recovery receipt")),nullptr;
    auto R=Parse(Text);if(!R||Hash(Text)!=Digest||String(R,TEXT("schema"))!=TEXT("xace.unreal_native_transaction.v1")||String(R,TEXT("transaction_id"))!=FPaths::GetCleanFilename(Dir)||String(R,TEXT("map"))!=Map||FileHash(Dir/TEXT("before.umap"))!=String(R,TEXT("before")))return Fail(TEXT("Receipt/backup mismatch")),nullptr;
    if(!Confined(Dir/TEXT("before.umap"),TransactionRoot())||!Confined(Dir/TEXT("staged.umap"),TransactionRoot()))return Fail(TEXT("Linked transaction artifacts")),nullptr;return R;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Recover(const FString& Map,const FString& Dir,const FString& Digest)
{
    Error.Reset();auto R=Receipt(Map,Dir,Digest);if(!R)return nullptr;FString File=MapFilename(Map);if(File.IsEmpty())return nullptr;
    if(R->HasField(TEXT("conflict")))return Fail(TEXT("Concurrent displaced image requires explicit manual recovery")),nullptr;
    FString Current=FileHash(File);FString State=TEXT("rolled_back");
    if(Current==String(R,TEXT("after"))){if(!Copy(Dir/TEXT("restore.umap"),Dir/TEXT("before.umap"))||!Replace(File,Dir/TEXT("restore.umap")))State=TEXT("recovery_conflict");}
    else if(Current!=String(R,TEXT("before")))State=TEXT("recovery_conflict");
    R->SetStringField(TEXT("state"),State);if(!Persist(Dir,R))return nullptr;bRescanRequired=true;return R;
}
FXaceUnrealAuthoring::Object FXaceUnrealAuthoring::Commit(const FString& Map,const FString& Dir,const FString& Digest,bool Inject)
{
    Error.Reset();auto R=Receipt(Map,Dir,Digest);if(!R)return nullptr;FString File=MapFilename(Map);
    if(File.IsEmpty()||String(R,TEXT("state"))!=TEXT("prepared")||FileHash(File)!=String(R,TEXT("before"))||FileHash(Dir/TEXT("staged.umap"))!=String(R,TEXT("after"))||Fingerprint(Map)!=String(R,TEXT("dependency_fingerprint")))return Fail(TEXT("Native source/stage/dependency changed since approval")),nullptr;
    auto Resources=Child(R,TEXT("resources"));if(!Resources)return Fail(TEXT("Missing resource approval stamps")),nullptr;
    for(const auto& P:Resources->Values)if(Fingerprint(P.Key,true)!=P.Value->AsString()||!Error.IsEmpty())return Fail(TEXT("Replacement resource changed since approval")),nullptr;
    R->SetStringField(TEXT("state"),TEXT("applying"));if(!Persist(Dir,R))return nullptr;
    if(!Copy(Dir/TEXT("publish.umap"),Dir/TEXT("staged.umap"))||!::ReplaceFileW(*FPaths::ConvertRelativePathToFull(File),*FPaths::ConvertRelativePathToFull(Dir/TEXT("publish.umap")),*FPaths::ConvertRelativePathToFull(Dir/TEXT("displaced.umap")),0,nullptr,nullptr))return Fail(TEXT("Native replacement failed; recover retained receipt")),nullptr;
    if(FileHash(Dir/TEXT("displaced.umap"))!=String(R,TEXT("before"))){R->SetStringField(TEXT("state"),TEXT("recovery_conflict"));R->SetStringField(TEXT("conflict"),TEXT("Concurrent source replacement; actual displaced bytes retained"));Persist(Dir,R);Fail(TEXT("Concurrent native edit retained in displaced.umap; explicit recovery required"));return R;}
    if(Inject){auto Result=Recover(Map,Dir,Hash(Json(R)));Error=TEXT("Injected replacement failure; recovery attempted");return Result;}
    R->SetStringField(TEXT("state"),TEXT("committed"));if(!Persist(Dir,R))return nullptr;bRescanRequired=true;return R;
}
