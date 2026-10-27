#include "XaceNativeApproval.h"
#include "XaceNativeHostClient.h"
#include "XaceNativeContract.h"
#include "HAL/FileManager.h"
#include "Misc/Paths.h"
#include "Misc/FileHelper.h"
#include "Misc/EngineVersion.h"
#if WITH_EDITOR
#include "Editor.h"
#include "Engine/World.h"
#endif
namespace {
bool Inventory(TMap<FString,FString>& Files,FString& Error){
 FString Root=FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());FPaths::NormalizeDirectoryName(Root);Root+=TEXT("/");TArray<FString> Paths;IFileManager::Get().FindFilesRecursive(Paths,*Root,TEXT("*"),true,false);Paths.Sort();
 for(const FString& Path:Paths){FString Rel=Path;if(!FPaths::MakePathRelativeTo(Rel,*Root)||Rel.StartsWith(TEXT("../"))){Error=TEXT("Source inventory escapes project");return false;}TArray<FString> Parts;Rel.ParseIntoArray(Parts,TEXT("/"));bool Skip=Rel==TEXT("XACEApproval.json")||Rel==TEXT("XACEBuild.json");for(const auto& Part:Parts)if(Part==TEXT("Binaries")||Part==TEXT("Intermediate")||Part==TEXT("Saved")||Part==TEXT("DerivedDataCache")||Part==TEXT("XACEEvidence")||Part==TEXT(".git"))Skip=true;if(Skip)continue;
  FString Hash=FXaceNativeHostClient::FileHash(Path);if(Hash.Len()!=64){Error=TEXT("Source cannot be hashed: ")+Rel;return false;}Files.Add(Rel,Hash);
 }
 return !Files.IsEmpty();
}
bool Read(const FString& Name,TSharedPtr<FJsonObject>& Object,FString& Error){FString Text;if(!FFileHelper::LoadFileToString(Text,*(FPaths::ProjectDir()/Name))||!(Object=XaceCanonical::Parse(Text)).IsValid()){Error=TEXT("Explicit native approval/receipt missing: ")+Name;return false;}return true;}
bool Dirty(FString& Error){
#if WITH_EDITOR
 if(GEditor){auto World=GEditor->GetEditorWorldContext().World();if(World&&World->GetOutermost()->IsDirty()){Error=TEXT("Save and review native map changes before Play");return true;}}
#endif
 return false;
}
}
namespace XaceNativeApproval {
bool RecordSavedSource(FString& Error){
 if(Dirty(Error))return false;const FString Path=FPaths::ProjectDir()/TEXT("XACEApproval.json");if(FPaths::FileExists(Path)){Error=TEXT("Approval exists; preserve it before explicitly approving a new revision");return false;}
 TMap<FString,FString> Files;if(!Inventory(Files,Error))return false;auto Record=MakeShared<FJsonObject>();Record->SetStringField(TEXT("schema"),TEXT("xace.unreal.source_approval.v1"));Record->SetStringField(TEXT("unreal"),FEngineVersion::Current().ToString());auto Rows=MakeShared<FJsonObject>();TArray<FString> Keys;Files.GetKeys(Keys);Keys.Sort();for(const auto& Key:Keys)Rows->SetStringField(Key,Files[Key]);Record->SetObjectField(TEXT("files"),Rows);
 if(!FFileHelper::SaveStringToFile(XaceCanonical::Json(Record),*Path,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_NoReplaceExisting)){Error=TEXT("Could not create source approval");return false;}return true;
}
bool ValidateSource(FString& Error){
 if(Dirty(Error))return false;TSharedPtr<FJsonObject> Record;if(!Read(TEXT("XACEApproval.json"),Record,Error))return false;FString Schema,Version;const TSharedPtr<FJsonObject>* Rows=nullptr;
 if(!Record->TryGetStringField(TEXT("schema"),Schema)||Schema!=TEXT("xace.unreal.source_approval.v1")||!Record->TryGetStringField(TEXT("unreal"),Version)||Version!=FEngineVersion::Current().ToString()||!Record->TryGetObjectField(TEXT("files"),Rows)){Error=TEXT("Native approval schema/engine mismatch");return false;}
 TMap<FString,FString> Current;if(!Inventory(Current,Error))return false;if(Current.Num()!=(*Rows)->Values.Num()){Error=TEXT("Native source inventory changed");return false;}
 for(const auto& Pair:Current){FString Expected;if(!(*Rows)->TryGetStringField(Pair.Key,Expected)||Expected!=Pair.Value){Error=TEXT("Native source changed: ")+Pair.Key;return false;}}return true;
}
bool ValidateCooked(FString& Error){
 TSharedPtr<FJsonObject> Record;if(!Read(TEXT("XACEBuild.json"),Record,Error))return false;FString Schema,Version;const TSharedPtr<FJsonObject>* Rows=nullptr;
 if(!Record->TryGetStringField(TEXT("schema"),Schema)||Schema!=TEXT("xace.unreal.cooked_files.v1")||!Record->TryGetStringField(TEXT("unreal"),Version)||Version!=FEngineVersion::Current().ToString()||!Record->TryGetObjectField(TEXT("files"),Rows)||(*Rows)->Values.IsEmpty()){Error=TEXT("Cooked approval schema/engine mismatch");return false;}
 for(const auto& Pair:(*Rows)->Values){FString Expected;if(Pair.Key.IsEmpty()||!FPaths::IsRelative(Pair.Key)||Pair.Key.Contains(TEXT(".."))||Pair.Key.Contains(TEXT("\\"))||!Pair.Value->TryGetString(Expected)||Expected.Len()!=64||FXaceNativeHostClient::FileHash(FPaths::ProjectDir()/Pair.Key)!=Expected){Error=TEXT("Cooked file mismatch: ")+Pair.Key;return false;}}
 return true;
}
}
