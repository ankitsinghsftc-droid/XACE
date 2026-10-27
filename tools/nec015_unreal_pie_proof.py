"""Create-only actual Unreal Editor PIE native host proof; not packaged acceptance."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
import unreal_vertical_slice_certification as old
ROOT=Path(__file__).resolve().parents[1]
def main(out,reuse=None,two=False):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec015') and not out.exists();assert shutil.disk_usage(ROOT).free>4*1024**3,'Insufficient SSD reserve; no cleanup'
 project=out/'project';project.mkdir(parents=True);uproject=project/'NEC015.uproject';uproject.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACE',Enabled=True)])),encoding='utf-8')
 plugin=project/'Plugins/XACE'
 for rel,text in old.unreal_generated_plugin_texts().items():
  p=plugin/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
 for name in [*old.ADAPTER_SOURCE_NAMES,'XaceNativeHostClient.h','XaceNativeHostClient.cpp','XaceNativeHost.h','XaceNativeHost.cpp','XaceNativeApproval.h','XaceNativeApproval.cpp','NEC015PIEProof.h']:
  source=ROOT/('tools' if name.startswith('NEC') else 'adapters/unreal')/name;dest=plugin/'Source/XACEAdapter'/('Public' if name.endswith('.h') else 'Private')/name;shutil.copyfile(source,dest)
 module=plugin/'Source/XACEAdapter/Private/XACEAdapterModule.cpp'
 module.write_text(module.read_text(encoding='utf-8').replace('#include "XACEAdapterModule.h"','#include "XACEAdapterModule.h"\n#include "NEC015PIEProof.h"').replace('void FXACEAdapterModule::StartupModule()\n{','void FXACEAdapterModule::StartupModule()\n{\n#if WITH_EDITOR\n NEC015PIE::Start();\n#endif'),encoding='utf-8')
 buildcs=plugin/'Source/XACEAdapter/XACEAdapter.Build.cs';buildcs.write_text(buildcs.read_text(encoding='utf-8').replace('PCHUsage =','if (Target.bBuildEditor) PrivateDependencyModuleNames.AddRange(new string[] { "UnrealEd" });\n        PCHUsage ='),encoding='utf-8')
 files={p.relative_to(plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (plugin/'Source').rglob('*') if p.is_file()};(out/'sources.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
 engine=Path('C:/Program Files/Epic Games/UE_5.7/Engine')
 cmd=[str(engine/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'UnrealEditor','Win64','Development',f'-Project={uproject}',f'-plugin={plugin/"XACE.uplugin"}','-nohotreload','-installed','-NoUBA','-MaxParallelActions=1',f'-log={out/"build-ubt.log"}']
 (out/'build-command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
 if reuse:
  assert files==json.loads((reuse/'sources.json').read_text(encoding='utf-8')),'Source identity differs; cannot reuse binaries'
  shutil.copytree(reuse/'project/Plugins/XACE/Binaries',plugin/'Binaries')
  (out/'reused-build.json').write_text(json.dumps(dict(source=str(reuse),files={p.relative_to(plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (plugin/'Binaries').rglob('*') if p.is_file()}),indent=2),encoding='utf-8')
 else:
  with (out/'build.txt').open('wb') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0,'UE compilation failed; logs retained'
 release=project/'release';shutil.copytree(ROOT/'evidence/nec015/20261026/playback-package-a/release',release)
 launcher=release/'xace-player-launcher.exe';shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',launcher)
 cmd=[str(engine/'Binaries/Win64/UnrealEditor-Cmd.exe'),str(uproject),'-unattended','-d3d11','-nosplash','-RenderOffscreen','-stdout','-FullStdOutLogOutput',f'-XacePIEReport={out/"proof.json"}',f'-abslog={out/"editor.log"}']
 if two:cmd.append('-XaceTwoPIE')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 (out/'command.json').write_text(json.dumps(cmd,indent=2),encoding='utf-8')
 with (out/'run.txt').open('wb') as log:r=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'UE client proof failed; logs retained'
 proof=json.loads((out/'proof.json').read_text(encoding='utf-8-sig'));assert proof['ok'];print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]).resolve() if len(sys.argv)>2 and sys.argv[2]!='--two' else None,'--two' in sys.argv)
