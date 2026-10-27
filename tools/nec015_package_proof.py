"""Fresh native-map Windows package proof; no cleanup or prior-output replacement."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec013_unity_player_proof import gone
ENGINE=Path('C:/Program Files/Epic Games/UE_5.7/Engine')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def run(cmd,log,env,timeout):
 with log.open('wb') as stream:
  process=subprocess.Popen(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);end=time.monotonic()+timeout
  while process.poll() is None:
   if shutil.disk_usage(ROOT).free<2*1024**3 or time.monotonic()>end:
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True);raise RuntimeError('Owned build stopped at disk/time reserve; files retained')
   time.sleep(2)
  assert process.returncode==0,'Native build/run failed; retained '+str(log)
def main(out,resume=None):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec015') and not out.exists();assert shutil.disk_usage(ROOT).free>(4 if resume else 8)*1024**3,'Need packaging headroom (4 GiB verified incremental / 8 GiB fresh); no cleanup'
 out.mkdir(parents=True);source=ROOT/'evidence/nec015/20261026/pie-playback-d/project';project=out/'project'
 if resume is not None:
  resume=resume.resolve();assert resume.is_relative_to(ROOT/'evidence/nec015')
  project=resume/'project';plugin=project/'Plugins/XACE';uproject=project/'NEC015.uproject'
  recorded=json.loads((resume/'source-identities.json').read_text(encoding='utf-8'))
  assert all((project/k).is_file() and sha(project/k)==v for k,v in recorded.items()),'Prior build source changed'
  assert 'Result: Succeeded' in (resume/'editor-build.log').read_text(encoding='utf-8')
  (out/'reused-build.json').write_text(json.dumps(dict(path=str(resume),sources=recorded),indent=2),encoding='utf-8')
  env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
  if (project/'Source/NEC015Editor.Target.cs').exists():
   cmd=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'NEC015Editor','Win64','Development',f'-Project={uproject}','-nohotreload','-installed','-NoUBA','-MaxParallelActions=1',f'-log={out/"editor-build-ubt.log"}']
   (out/'editor-build-command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8');run(cmd,out/'editor-build.log',env,900)
 else:
  shutil.copytree(source,project,ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache','XACEApproval.json'))
  plugin=project/'Plugins/XACE';priv=plugin/'Source/XACEAdapter/Private';pub=plugin/'Source/XACEAdapter/Public'
  for p in (ROOT/'adapters/unreal').glob('*'):
   if p.suffix in ['.h','.cpp'] and (pub/p.name if p.suffix=='.h' else priv/p.name).exists():shutil.copyfile(p,(pub if p.suffix=='.h' else priv)/p.name)
  shutil.copyfile(ROOT/'tools/NEC015PackagedProof.h',pub/'NEC015PackagedProof.h')
  shutil.copyfile(ROOT/'tools/NEC015PIEProof.h',pub/'NEC015PIEProof.h')
  module=priv/'XACEAdapterModule.cpp';module.write_text(module.read_text(encoding='utf-8').replace('#include "NEC015PIEProof.h"','#include "NEC015PIEProof.h"\n#include "NEC015PackagedProof.h"').replace(' NEC015PIE::Start();\n#endif',' NEC015PIE::Start();\n#else\n NEC015Packaged::Start();\n#endif'),encoding='utf-8')
  descriptor=project/'NEC015.uproject';data=json.loads(descriptor.read_text(encoding='utf-8'));data['Modules']=[dict(Name='NEC015',Type='Runtime',LoadingPhase='Default')];descriptor.write_text(json.dumps(data,indent=2),encoding='utf-8')
  game_source=project/'Source/NEC015';game_source.mkdir(parents=True)
  (game_source/'NEC015.Build.cs').write_text('using UnrealBuildTool; public class NEC015 : ModuleRules { public NEC015(ReadOnlyTargetRules Target) : base(Target) { PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs; PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" }); } }',encoding='utf-8')
  (game_source/'NEC015.cpp').write_text('#include "Modules/ModuleManager.h"\nIMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, NEC015, "NEC015");\n',encoding='utf-8')
  (project/'Source/NEC015.Target.cs').write_text('using UnrealBuildTool; public class NEC015Target : TargetRules { public NEC015Target(TargetInfo Target) : base(Target) { Type=TargetType.Game; DefaultBuildSettings=BuildSettingsVersion.Latest; IncludeOrderVersion=EngineIncludeOrderVersion.Latest; ExtraModuleNames.Add("NEC015"); } }',encoding='utf-8')
  (project/'Source/NEC015Editor.Target.cs').write_text('using UnrealBuildTool; public class NEC015EditorTarget : TargetRules { public NEC015EditorTarget(TargetInfo Target) : base(Target) { Type=TargetType.Editor; DefaultBuildSettings=BuildSettingsVersion.Latest; IncludeOrderVersion=EngineIncludeOrderVersion.Latest; ExtraModuleNames.Add("NEC015"); } }',encoding='utf-8')
  config=project/'Config';config.mkdir(exist_ok=True)
  (config/'DefaultEngine.ini').write_text('[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap=/Game/NativeProof\nEditorStartupMap=/Game/NativeProof\n[/Script/WindowsTargetPlatform.WindowsTargetSettings]\nDefaultGraphicsRHI=DefaultGraphicsRHI_DX11\n',encoding='utf-8')
  (config/'DefaultGame.ini').write_text('[/Script/UnrealEd.ProjectPackagingSettings]\nbUsePakFile=True\nbUseIoStore=False\n+MapsToCook=(FilePath="/Game/NativeProof")\n+DirectoriesToAlwaysCook=(Path="/Game")\n+DirectoriesToAlwaysCook=(Path="/Engine/EngineSounds")\n',encoding='utf-8')
  env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data');uproject=project/'NEC015.uproject'
  sources={p.relative_to(project).as_posix():sha(p) for p in project.rglob('*') if p.is_file()};(out/'source-identities.json').write_text(json.dumps(sources,indent=2),encoding='utf-8')
  cmd=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'NEC015Editor','Win64','Development',f'-Project={uproject}','-nohotreload','-installed','-NoUBA','-MaxParallelActions=1',f'-log={out/"editor-build-ubt.log"}']
  (out/'editor-build-command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8');run(cmd,out/'editor-build.log',env,900)
 cmd=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/AutomationTool/AutomationTool.dll'),'BuildCookRun',f'-project={uproject}','-nop4','-unattended','-utf8output','-platform=Win64','-clientconfig=Development','-build','-cook','-stage','-pak','-archive',f'-archivedirectory={out/"archive"}','-map=/Game/NativeProof','-nocompileeditor','-skipbuildeditor','-nodebuginfo','-UbtArgs=-NoUBA -MaxParallelActions=1']
 (out/'package-command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8');run(cmd,out/'package.log',env,3600)
 windows=out/'archive/Windows';game=windows/'NEC015';assert game.is_dir();shutil.copytree(project/'release',game/'release')
 version=json.loads((source/'XACEApproval.json').read_text(encoding='utf-8-sig'))['unreal']
 (game/'XACEBuild.json').write_text(json.dumps(dict(schema='xace.unreal.cooked_files.v1',unreal=version,files={p.relative_to(game).as_posix():sha(p) for p in game.rglob('*') if p.is_file()}),indent=2),encoding='utf-8')
 exe=windows/'NEC015.exe';assert exe.exists();env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 cmd=[str(exe),'-d3d11','-RenderOffscreen','-unattended',f'-XaceNativePreflight={out/"preflight.json"}',f'-abslog={out/"preflight-engine.log"}'];(out/'preflight-command.json').write_text(json.dumps(cmd),encoding='utf-8');run(cmd,out/'preflight.log',env,120)
 proof=json.loads((out/'preflight.json').read_text(encoding='utf-8-sig'));assert proof['ok'] and proof['cooked'] and not proof['authority_started'],proof
 cmd=[str(exe),'-d3d11','-RenderOffscreen','-unattended',f'-XaceNativeReport={out/"player.json"}',f'-abslog={out/"player-engine.log"}'];(out/'player-command.json').write_text(json.dumps(cmd),encoding='utf-8');run(cmd,out/'player.log',env,120)
 proof=json.loads((out/'player.json').read_text(encoding='utf-8-sig'));assert proof['ok'] and proof['packaged'] and gone(proof['owner_pid']) and gone(proof['runtime_pid']);proof.update(clean_machine=False,process_cleanup=True)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]) if len(sys.argv)>2 else None)
