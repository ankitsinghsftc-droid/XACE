"""Create-only imported Unreal native PIE, Windows cook and relocated run proof."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from tools.nec015_package_proof import ENGINE,run,sha
from tools.nec013_unity_player_proof import gone
import playable_package as pp
from native_executor_contract import admit,digest

def files(root):return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}
def main(out,source=None,package_base=None,project_destination=None,disable_pch=False):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert shutil.disk_usage(ROOT).free>8*1024**3,'8GiB native build headroom required';out.mkdir(parents=True)
 source=Path(source).resolve() if source is not None else ROOT/'evidence/nec017/20261105/unreal-existing-publish-b/project';assert source.is_relative_to(ROOT/'evidence/nec017');original={name:files(source/name) for name in ['Content','Config']};project=Path(project_destination).resolve() if project_destination is not None else out/'project';assert not project.exists();assert project.is_relative_to(Path('C:/Users/ankit/XACE-Recovery/continuity')) if project_destination is not None else project.is_relative_to(out);project.mkdir(parents=True)
 for name in original:shutil.copytree(source/name,project/name)
 template=ROOT/'evidence/nec015/20261027/build-wrapper-a/project';shutil.copytree(template/'Source',project/'Source')
 descriptor=json.loads((template/'NEC015.uproject').read_bytes());descriptor['Plugins']=[dict(Name='XACE',Enabled=True),dict(Name='AndroidFileServer',Enabled=False)];(project/'NEC015.uproject').write_bytes(pp.encode(descriptor));uproject=project/'NEC015.uproject'
 plugin=project/'Plugins/XACE';shutil.copytree(template/'Plugins/XACE',plugin,ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache'))
 for current in (ROOT/'adapters/unreal').iterdir():
  if current.suffix in ['.h','.cpp']:
   target=plugin/'Source/XACEAdapter'/('Public' if current.suffix=='.h' else 'Private')/current.name
   assert target.exists(),str(target)
   if current.name=='XaceNativeContractProofCommandlet.cpp':assert current.read_text(encoding='utf-8') in target.read_text(encoding='utf-8'),'Expected editor-only commandlet wrapper changed'
   else:shutil.copyfile(current,target)
 (out/'explicit-mobility-choice.json').write_bytes(pp.encode(dict(scope='New imported-map copy only',action='Refuse original Static roots first, then explicitly set50bound roots Movable for authoritative projection',original_source_changed=False,lighting_performance_may_change=True)))
 shutil.copyfile(ROOT/'tools/NEC017ExistingPlayProof.h',plugin/'Source/XACEAdapter/Public/NEC017ExistingPlayProof.h')
 module=plugin/'Source/XACEAdapter/Private/XACEAdapterModule.cpp';module.write_text('#include "XACEAdapterModule.h"\n#include "NEC017ExistingPlayProof.h"\n#include "Modules/ModuleManager.h"\nIMPLEMENT_MODULE(FXACEAdapterModule, XACEAdapter)\nvoid FXACEAdapterModule::StartupModule(){NEC017Existing::Start();}\nvoid FXACEAdapterModule::ShutdownModule(){}\n',encoding='utf-8')
 config=project/'Config/DefaultEngine.ini';config.write_text(config.read_text(encoding='utf-8')+'\n[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap=/Game/World\nEditorStartupMap=/Game/World\n[/Script/WindowsTargetPlatform.WindowsTargetSettings]\nDefaultGraphicsRHI=DefaultGraphicsRHI_DX11\n',encoding='utf-8')
 cfg=project/'Config/DefaultGame.ini';cfg.write_text((cfg.read_text(encoding='utf-8') if cfg.exists() else '')+'\n[/Script/UnrealEd.ProjectPackagingSettings]\nbUsePakFile=True\nbUseIoStore=False\n+MapsToCook=(FilePath="/Game/World")\n+DirectoriesToAlwaysCook=(Path="/Game")\nbSkipEditorContent=False\n',encoding='utf-8')
 base=Path(package_base).resolve() if package_base is not None else ROOT/'evidence/nec017/20261106/existing-execution-b/unreal';assert base.is_relative_to(ROOT/'evidence/nec017');archive_files=pp.read_archive((base/'game.xacepkg').read_bytes());cgs=json.loads(archive_files['game.cgs.json']);compiled,_=pp.compiled_artifacts(cgs);receipt_path=ROOT/'evidence/nec011/20261021/reference-admission-a/executor-receipt.json';receipt=json.loads(receipt_path.read_bytes());exe=base/'relocated/runtime/xace_runtime.exe';support=admit(receipt,expected_receipt_digest=digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=compiled)
 presentation={p:data for p,data in archive_files.items() if p.startswith('presentation/')};presentation['presentation/player/settings.json']=pp.encode(dict(schema='xace.player.controls.v1',controller_id=1,instructions='Declared native move axis',bindings=[dict(action='move_x',positive=68,negative=65,kind='axis_1d')]))
 archive=pp.build_package(cgs,archive_files['execution_plan.json'],exe.read_bytes(),support,package_id='nec017.existing.unreal',version='0.1.0',presentation_files=presentation);(out/'game.xacepkg').write_bytes(archive);release=project/'release';release.mkdir()
 for name,data in pp.read_archive(archive).items():
  p=release/'package'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 shutil.copyfile(receipt_path,release/'executor-receipt.json');shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 (release/'native-release.json').write_bytes(pp.encode(dict(schema='xace.native_release.v1',engine='Unreal',game_id='nec017-existing-unreal',package_manifest_sha256=sha(release/'package/playable.manifest.json'),executor_receipt_sha256=sha(release/'executor-receipt.json'),required_capabilities=['native.structured_transform.v1'],compatibility=receipt['compatibility'],save_schema='nec017.existing.v1',resources=[])))
 pins={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),ROOT/'tools/NEC017ExistingPlayProof.h',*sorted((ROOT/'adapters/unreal').glob('*.h')),*sorted((ROOT/'adapters/unreal').glob('*.cpp')),*sorted((ROOT/'packages/project-system').glob('*.py'))]};(out/'source-pins.json').write_bytes(pp.encode(pins));(out/'original-files.json').write_bytes(pp.encode(original));env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 command=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'NEC015Editor','Win64','Development',f'-Project={uproject}','-nohotreload','-installed','-NoUBA','-MaxParallelActions=1',f'-log={out/"editor-build-ubt.log"}'];command+=['-NoPCH'] if disable_pch else [];(out/'editor-build-command.json').write_bytes(pp.encode(command));run(command,out/'editor-build.log',env,1200)
 print('Imported Unreal observer compiled',flush=True)
 command=[str(ENGINE/'Binaries/Win64/UnrealEditor-Cmd.exe'),str(uproject),'-unattended','-d3d11','-nosplash','-RenderOffscreen','-stdout','-FullStdOutLogOutput',f'-NEC017ExistingReport={out/"editor-play.json"}',f'-abslog={out/"editor-play-engine.log"}'];(out/'editor-play-command.json').write_bytes(pp.encode(command));run(command,out/'editor-play.log',env,300)
 editor=json.loads((out/'editor-play.json').read_text(encoding='utf-8-sig'));assert editor['ok'] and editor['static_root_refused'] and editor['process_cleanup'] and not editor['packaged'] and gone(editor['runtime_pid']) and gone(editor['owner_pid']);print('Imported Unreal actual PIE passed',flush=True)
 for name,expected in original['Content'].items():
  if name!='World.umap':assert sha(project/'Content'/name)==expected,'Original resource drift: '+name
 assert all(files(source/name)==data for name,data in original.items());(out/'editor-proof.json').write_bytes(pp.encode(dict(ok=True,actual_imported_map=True,editor=editor,original_source_unchanged=True,other_map_assets_unchanged=True,full_nec017_complete=False)))
 command=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/AutomationTool/AutomationTool.dll'),'BuildCookRun',f'-project={uproject}','-nop4','-unattended','-utf8output','-platform=Win64','-clientconfig=Development','-build','-cook','-stage','-pak','-archive',f'-archivedirectory={out/"archive"}','-map=/Game/World','-nocompileeditor','-skipbuildeditor','-nodebuginfo','-UbtArgs=-NoUBA -MaxParallelActions=1'+(' -NoPCH' if disable_pch else '')];(out/'package-command.json').write_bytes(pp.encode(command));started=time.perf_counter();run(command,out/'package.log',env,3600);seconds=time.perf_counter()-started
 windows=out/'archive/Windows';game=windows/'NEC015';assert game.is_dir();shutil.copytree(release,game/'release');shutil.copyfile(project/'NEC017.expected.json',game/'NEC017.expected.json')
 marker=windows/'Engine/Build/InstalledProjectBuild.txt';marker.parent.mkdir(parents=True,exist_ok=True)
 if not marker.exists():marker.write_text('NEC017 installed native game\n',encoding='utf-8')
 version=json.loads((project/'XACEApproval.json').read_text(encoding='utf-8-sig'))['unreal'];(game/'XACEBuild.json').write_bytes(pp.encode(dict(schema='xace.unreal.cooked_files.v1',unreal=version,files=files(game))))
 env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');env['LOCALAPPDATA']=str(out/'player-user-data');before=files(windows)
 command=[str(windows/'NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended',f'-NEC017ExistingReport={out/"player.json"}',f'-abslog={out/"player-engine.log"}'];(out/'player-command.json').write_bytes(pp.encode(command));run(command,out/'player.log',env,150)
 player=json.loads((out/'player.json').read_text(encoding='utf-8-sig'));assert player['ok'] and player['packaged'] and gone(player['runtime_pid']) and gone(player['owner_pid']);assert files(windows)==before and all(files(source/name)==data for name,data in original.items()) and all(sha(ROOT/name)==h for name,h in pins.items())
 (out/'proof.json').write_bytes(pp.encode(dict(ok=True,editor=editor,player=player,package_seconds=seconds,original_unchanged=True,installation_unchanged=True,clean_machine=False,source_stable=True,full_nec017_complete=False)));print('Imported Unreal packaged gameplay passed',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))
