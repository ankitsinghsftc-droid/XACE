"""Actual Editor Play proof in a fresh native scene; full shipping acceptance is separate."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out,build=False):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec013') and not out.exists()
 project=out/'project';(project/'Assets/XACE/Editor').mkdir(parents=True)
 for path in (ROOT/'adapters/unity').glob('*.cs'):shutil.copyfile(path,project/'Assets/XACE'/path.name)
 shutil.copyfile(ROOT/'tools/NEC013UnityPlayProof.cs',project/'Assets/XACE/Editor/NEC013UnityPlayProof.cs')
 if build:
  shutil.copyfile(ROOT/'tools/NEC013UnityBuildProof.cs',project/'Assets/XACE/Editor/NEC013UnityBuildProof.cs')
  shutil.copyfile(ROOT/'tools/NEC013UnityPlayerProbe.cs',project/'Assets/XACE/NEC013UnityPlayerProbe.cs')
 (project/'Packages').mkdir();(project/'Packages/manifest.json').write_text(json.dumps(dict(dependencies={f'com.unity.modules.{name}':'1.0.0' for name in ['particlesystem','physics','audio','animation','jsonserialize','ui','imgui']})),encoding='utf-8')
 (project/'ProjectSettings').mkdir();(project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n',encoding='utf-8')
 release=project/'Assets/StreamingAssets/XACERelease';shutil.copytree(ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Unity/release',release)
 shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 command=['C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe','-batchmode','-nographics','-projectPath',str(project),'-executeMethod','NEC013UnityPlayProof.Run','-xaceReport',str(out/'proof.json'),'-logFile',str(out/'editor.log')]
 if build:command[command.index('NEC013UnityPlayProof.Run')]='NEC013UnityBuildProof.Run';command+=['-xaceBuild',str(out/'shipping/NativeGame.exe')]
 (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8');(out/'sources.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'adapters/unity').glob('*.cs')},indent=2),encoding='utf-8')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 with (out/'run.txt').open('wb') as log:result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=900 if build else 360,creationflags=subprocess.CREATE_NO_WINDOW)
 assert result.returncode==0,'Unity Play proof failed; inspect retained editor.log'
 report=json.loads((out/'proof.json').read_text(encoding='utf-8-sig'));assert report['ok'];print(json.dumps(report))
if __name__=='__main__':main(Path(sys.argv[1]),build="--build" in sys.argv)
