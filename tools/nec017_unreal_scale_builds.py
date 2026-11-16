"""Three Unreal native cooks/readbacks at1,000 objects; static data scope only."""
from pathlib import Path
import json,os,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import inventory,sha
from tools.nec015_package_proof import ENGINE
from tools.nec017_unity_scale_builds import run
OBSERVER=r'''#include "Modules/ModuleManager.h"
#include "Containers/Ticker.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Engine/StaticMeshActor.h"
#include "EngineUtils.h"
#include "HAL/PlatformProperties.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
namespace NEC017Scale {
static FString Report;
static TSharedPtr<FJsonObject> Parse(const FString& S){TSharedPtr<FJsonObject> O;auto R=TJsonReaderFactory<>::Create(S);return FJsonSerializer::Deserialize(R,O)?O:nullptr;}
static bool Tick(float){if(!GEngine)return true;UWorld* World=nullptr;for(auto& Context:GEngine->GetWorldContexts())if(Context.World()&&Context.World()->IsGameWorld()&&Context.World()->HasBegunPlay())World=Context.World();if(!World)return true;
 FString Text;bool Ok=FFileHelper::LoadFileToString(Text,*(FPaths::ProjectDir()/TEXT("scale-expected.json")));auto Expected=Parse(Text);Ok=Ok&&Expected&&Expected->Values.Num()==1000;TSet<FString> Seen;int32 Count=0;
 for(TActorIterator<AStaticMeshActor> It(World);It;++It){for(auto Tag:It->Tags){auto Raw=Tag.ToString();if(!Raw.StartsWith(TEXT("XACE_AUTHORING_V1:")))continue;auto Meta=Parse(Raw.Mid(18));if(!Meta||Meta->GetStringField(TEXT("kind"))!=TEXT("object")){Ok=false;continue;}FString Id=Meta->GetStringField(TEXT("namespace_id"))+TEXT(":")+Meta->GetStringField(TEXT("authoring_id"));++Count;if(Seen.Contains(Id)||!Expected||!Expected->HasField(Id)){Ok=false;continue;}Seen.Add(Id);auto Value=Expected->GetObjectField(Id);FVector P(Value->GetNumberField(TEXT("x")),Value->GetNumberField(TEXT("y")),Value->GetNumberField(TEXT("z")));Ok=Ok&&It->GetActorLocation().Equals(P,0.0001)&&It->GetActorScale3D().Equals(FVector::OneVector,0.00001)&&It->GetActorQuat().Equals(FQuat::Identity,0.00001);}}
 Ok=Ok&&Count==1000&&Seen.Num()==1000;auto Result=MakeShared<FJsonObject>();Result->SetBoolField(TEXT("ok"),Ok);Result->SetBoolField(TEXT("exported"),FPlatformProperties::RequiresCookedData());Result->SetNumberField(TEXT("objects"),Count);Result->SetStringField(TEXT("scope"),TEXT("Static serialized transform actors; no XACE gameplay runtime or graphics workload"));FString Out;auto Writer=TJsonWriterFactory<>::Create(&Out);FJsonSerializer::Serialize(Result.ToSharedRef(),Writer);FFileHelper::SaveStringToFile(Out,*Report,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);FPlatformMisc::RequestExitWithStatus(false,Ok?0:1);return false;
}
}
class FNEC017ScaleModule:public FDefaultGameModuleImpl{public:void StartupModule()override{if(FParse::Value(FCommandLine::Get(),TEXT("NEC017ScaleReport="),NEC017Scale::Report))FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateStatic(&NEC017Scale::Tick));}};
IMPLEMENT_PRIMARY_GAME_MODULE(FNEC017ScaleModule, NEC017Scale, "NEC017Scale");
'''
def main(out,destination):
 out=out.resolve();destination=destination.resolve();base=Path('C:/Users/ankit/XACE-Recovery/continuity').resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists() and destination.is_relative_to(base) and not destination.exists() and len(str(destination))<90 and shutil.disk_usage(ROOT).free>4*1024**3
 out.mkdir(parents=True);destination.mkdir(parents=True);source=ROOT/'evidence/nec017/20261028/unreal-scale-a/unreal-project';before=inventory(source/'Content');shutil.copytree(source/'Content',destination/'Content');module=destination/'Source/NEC017Scale';module.mkdir(parents=True)
 (module/'NEC017Scale.cpp').write_text(OBSERVER);(module/'NEC017Scale.Build.cs').write_text('using UnrealBuildTool;public class NEC017Scale:ModuleRules{public NEC017Scale(ReadOnlyTargetRules Target):base(Target){PCHUsage=PCHUsageMode.NoPCHs;PublicDependencyModuleNames.AddRange(new string[]{"Core","CoreUObject","Engine","Json"});}}')
 for suffix,kind in [('', 'Game'),('Editor','Editor')]:
  (destination/('Source/NEC017Scale'+suffix+'.Target.cs')).write_text('using UnrealBuildTool;public class NEC017Scale'+suffix+'Target:TargetRules{public NEC017Scale'+suffix+'Target(TargetInfo Target):base(Target){Type=TargetType.'+kind+';DefaultBuildSettings=BuildSettingsVersion.Latest;IncludeOrderVersion=EngineIncludeOrderVersion.Latest;ExtraModuleNames.Add("NEC017Scale");}}')
 uproject=destination/'NEC017Scale.uproject';uproject.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Modules=[dict(Name='NEC017Scale',Type='Runtime',LoadingPhase='Default')],Plugins=[dict(Name='AndroidFileServer',Enabled=False)])))
 config=destination/'Config';config.mkdir();(config/'DefaultEngine.ini').write_text('[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap=/Game/XACEGenerated/World\nEditorStartupMap=/Game/XACEGenerated/World\n[/Script/WindowsTargetPlatform.WindowsTargetSettings]\nDefaultGraphicsRHI=DefaultGraphicsRHI_DX11\n[/Script/Engine.RendererSettings]\nr.RayTracing=False\nr.AllowStaticLighting=False\n');(config/'DefaultGame.ini').write_text('[/Script/UnrealEd.ProjectPackagingSettings]\nbUsePakFile=True\nbUseIoStore=False\n+MapsToCook=(FilePath="/Game/XACEGenerated/World")\n')
 plan=json.loads((source.parent/'setup-plan.json').read_bytes());expected={}
 for row in plan['native_request']['objects']:
  identity=row['identity'];p=row['fields']['transform.position'];expected[identity['namespace_id']+':'+identity['authoring_id']]=dict(x=-int(p['z'])/10000,y=int(p['x'])/10000,z=int(p['y'])/10000)
 assert len(expected)==1000;(destination/'scale-expected.json').write_text(json.dumps(expected,sort_keys=True));approved={n:inventory(destination/n) for n in ['Content','Source','Config']};(out/'source-pins.json').write_text(json.dumps(dict(project=str(destination),files=approved,uproject_sha256=sha(uproject)),sort_keys=True,indent=2));env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');dotnet=str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe')
 run([dotnet,str(ENGINE/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'NEC017ScaleEditor','Win64','Development',f'-Project={uproject}','-nohotreload','-installed','-NoUBA','-NoPCH','-MaxParallelActions=1'],out,'editor-build',env,1800);samples=[]
 for n in range(3):
  archive=out/('build-'+str(n));command=[dotnet,str(ENGINE/'Binaries/DotNET/AutomationTool/AutomationTool.dll'),'BuildCookRun',f'-project={uproject}','-nop4','-unattended','-utf8output','-platform=Win64','-clientconfig=Development','-build','-cook','-cookall','-stage','-pak','-archive',f'-archivedirectory={archive}','-map=/Game/XACEGenerated/World','-nocompileeditor','-skipbuildeditor','-nodebuginfo','-UbtArgs=-NoUBA -NoPCH -MaxParallelActions=1'];metric=run(command,out,'build-'+str(n),env,1800)
  game=archive/'Windows/NEC017Scale';shutil.copyfile(destination/'scale-expected.json',game/'scale-expected.json');installed=inventory(archive);report=out/('player-'+str(n)+'.json');run([str(game/'Binaries/Win64/NEC017Scale.exe'),'-d3d11','-RenderOffscreen','-unattended',f'-NEC017ScaleReport={report}',f'-abslog={out/("player-"+str(n)+"-engine.log")}'],out,'player-'+str(n),env,150)
  value=json.loads(report.read_text(encoding='utf-8-sig'));assert value['ok'] and value['objects']==1000 and value['exported'] and inventory(archive)==installed and inventory(source/'Content')==before and all(inventory(destination/k)==approved[k] for k in approved) and sha(uproject)==json.loads((out/'source-pins.json').read_bytes())['uproject_sha256']
  samples.append(dict(build=n,measurement=metric,player=value,output_bytes=sum(p.stat().st_size for p in archive.rglob('*') if p.is_file())));print(json.dumps(dict(build=n,objects=1000,seconds=metric['seconds'],ok=True)),flush=True)
 (out/'proof.json').write_text(json.dumps(dict(ok=True,engine='Unreal5.7.4',objects=1000,rebuilds=3,samples=samples,original_unchanged=True,source_unchanged=True,compiler_cache_reused_between_builds=True,cookall_requested=True,scale_scope='Native serialized transform-actor cook/build/readback; no XACE gameplay runtime or graphics workload',gameplay_runtime_scale_certified=False,graphics_scale_certified=False,full_nec017_complete=False),indent=2))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
