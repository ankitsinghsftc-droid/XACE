"""Create native Unity test content before installing any XACE adapter."""
from pathlib import Path
import sys,shutil,subprocess,json,hashlib,wave
ROOT=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]).resolve()
assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists()
assert shutil.disk_usage(ROOT).free>6*1024**3,'6 GiB reserve required'
project=out/'project';(project/'Assets/Editor').mkdir(parents=True);(project/'Assets/Game').mkdir();(project/'Packages').mkdir();(project/'ProjectSettings').mkdir()
shutil.copyfile(ROOT/'tools/nec017_unity_existing_fixture.cs',project/'Assets/Editor/NEC017ExistingFixture.cs')
(project/'Assets/Game/NEC017NativeCounter.cs').write_text('using UnityEngine; public class NEC017NativeCounter:MonoBehaviour {public int nativeScore;void Update(){nativeScore++;}}')
(project/'Packages/manifest.json').write_text(json.dumps({'dependencies':{'com.unity.modules.physics':'1.0.0','com.unity.modules.audio':'1.0.0','com.unity.modules.animation':'1.0.0','com.unity.modules.jsonserialize':'1.0.0'}}))
(project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n')
with wave.open(str(project/'Assets/Game/Tone.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(1);w.setframerate(22050);w.writeframes(bytes([128])*2205)
exe=Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')
command=[str(exe),'-batchmode','-nographics','-projectPath',str(project),'-executeMethod','NEC017ExistingFixture.Create','-logFile',str(out/'editor.log')]
(out/'command.json').write_text(json.dumps(dict(command=command,executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest()),indent=2))
with (out/'process.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
assert r.returncode==0,'Native Unity creation failed; logs retained'
proof=json.loads((project/'fixture-created.json').read_bytes());assert proof['ok'] and proof['authored_instances']==50 and not proof['xace_enrolled']
files={p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['Assets','Packages','ProjectSettings'] for p in (project/folder).rglob('*') if p.is_file()}
(out/'pre-adoption-manifest.json').write_text(json.dumps(dict(files=files,fixture=proof,scope='Native source only; no adoption, gameplay equivalence or shipping certification'),indent=2));print(json.dumps(proof),flush=True)
