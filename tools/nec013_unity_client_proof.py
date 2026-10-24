"""Create-only Unity compilation/owned-host smoke proof, not full NEC013 acceptance."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec013') and not out.exists()
 project=out/'project';(project/'Assets/XACE/Editor').mkdir(parents=True)
 for path in (ROOT/'adapters/unity').glob('*.cs'):shutil.copyfile(path,project/'Assets/XACE'/path.name)
 shutil.copyfile(ROOT/'tools/NEC013UnityHostProof.cs',project/'Assets/XACE/Editor/NEC013UnityHostProof.cs')
 (project/'Packages').mkdir();(project/'Packages/manifest.json').write_text(json.dumps(dict(dependencies={f'com.unity.modules.{name}':'1.0.0' for name in ['particlesystem','physics','audio','animation','jsonserialize','ui','imgui']})),encoding='utf-8')
 (project/'ProjectSettings').mkdir();(project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n',encoding='utf-8')
 release=out/'release';shutil.copytree(ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Unity/release',release)
 launcher=out/'xace-player-launcher.exe';shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',launcher)
 command=['C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe','-batchmode','-nographics','-projectPath',str(project),'-executeMethod','NEC013UnityHostProof.Run','-xaceRelease',str(release),'-xaceLauncher',str(launcher),'-xaceLauncherHash',sha(launcher),'-xaceReleaseHash',sha(release/'native-release.json'),'-xaceHistory',str(out/'history'),'-xaceReport',str(out/'proof.json'),'-logFile',str(out/'editor.log')]
 (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8');(out/'sources.json').write_text(json.dumps({p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'adapters/unity').glob('*.cs')},indent=2),encoding='utf-8')
 with (out/'run.txt').open('wb') as log:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=360,creationflags=subprocess.CREATE_NO_WINDOW)
 assert result.returncode==0,'Unity proof failed; inspect retained editor.log'
 report=json.loads((out/'proof.json').read_text(encoding='utf-8-sig'));assert report['ok'];print(json.dumps(report))
if __name__=='__main__':main(Path(sys.argv[1]))
