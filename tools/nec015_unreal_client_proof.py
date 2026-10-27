"""Create-only actual UE native-host client proof; not full PIE/package acceptance."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
import unreal_vertical_slice_certification as old
ROOT=Path(__file__).resolve().parents[1]
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec015') and not out.exists();assert shutil.disk_usage(ROOT).free>4*1024**3,'Insufficient SSD reserve; no cleanup'
 project=out/'project';project.mkdir(parents=True);uproject=project/'NEC015.uproject';uproject.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACE',Enabled=True)])),encoding='utf-8')
 plugin=project/'Plugins/XACE'
 for rel,text in old.unreal_generated_plugin_texts().items():
  p=plugin/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
 for name in [*old.ADAPTER_SOURCE_NAMES,'XaceNativeHostClient.h','XaceNativeHostClient.cpp','XaceNativeHost.h','XaceNativeHost.cpp','XaceNativeApproval.h','XaceNativeApproval.cpp','NEC015HostProofCommandlet.h','NEC015HostProofCommandlet.cpp']:
  source=ROOT/('tools' if name.startswith('NEC') else 'adapters/unreal')/name;dest=plugin/'Source/XACEAdapter'/('Public' if name.endswith('.h') else 'Private')/name;shutil.copyfile(source,dest)
 buildcs=plugin/'Source/XACEAdapter/XACEAdapter.Build.cs';buildcs.write_text(buildcs.read_text(encoding='utf-8').replace('PCHUsage =','if (Target.bBuildEditor) PrivateDependencyModuleNames.AddRange(new string[] { "UnrealEd" });\n        PCHUsage ='),encoding='utf-8')
 files={p.relative_to(plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (plugin/'Source').rglob('*') if p.is_file()};(out/'sources.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
 engine=Path('C:/Program Files/Epic Games/UE_5.7/Engine')
 cmd=[str(engine/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'UnrealEditor','Win64','Development',f'-Project={uproject}',f'-plugin={plugin/"XACE.uplugin"}','-nohotreload','-installed','-NoUBA','-MaxParallelActions=1',f'-log={out/"build-ubt.log"}']
 (out/'build-command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
 with (out/'build.txt').open('wb') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'UE compilation failed; logs retained'
 release=out/'release';shutil.copytree(ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Unreal/release',release)
 launcher=out/'xace-player-launcher.exe';shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',launcher)
 cmd=[str(engine/'Binaries/Win64/UnrealEditor-Cmd.exe'),str(uproject),'-run=NEC015HostProof','-unattended','-nullrhi','-nosplash',f'-Launcher={launcher}',f'-Release={release}',f'-History={out/"history"}',f'-Report={out/"proof.json"}',f'-abslog={out/"editor.log"}']
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 (out/'command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
 with (out/'run.txt').open('wb') as log:r=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'UE client proof failed; logs retained'
 proof=json.loads((out/'proof.json').read_text(encoding='utf-8-sig'));assert proof['ok'];print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]))
