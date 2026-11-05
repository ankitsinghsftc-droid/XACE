"""Create a separate native Unreal fixture before any XACE enrollment."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,time,wave
ROOT=Path(__file__).resolve().parents[1]
EDITOR=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
def main(out):
 out=out.resolve()
 assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists()
 assert shutil.disk_usage(ROOT).free>6*1024**3,'Need6GiB headroom; no cleanup performed'
 project=out/'project';(project/'Config').mkdir(parents=True);(project/'SourceContent').mkdir()
 uproject=project/'NEC017Existing.uproject'
 uproject.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name=name,Enabled=True) for name in ['PythonScriptPlugin','EditorScriptingUtilities','SequencerScripting']]),indent=2))
 (project/'Config/DefaultEngine.ini').write_text('[/Script/Engine.RendererSettings]\nr.RayTracing=False\nr.AllowStaticLighting=False\n[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap=/Game/World\nEditorStartupMap=/Game/World\n')
 (project/'Config/DefaultInput.ini').write_text('[/Script/Engine.InputSettings]\n+ActionMappings=(ActionName="Jump",bShift=False,bCtrl=False,bAlt=False,bCmd=False,Key=SpaceBar)\n')
 with wave.open(str(project/'SourceContent/Tone.wav'),'wb') as audio:
  audio.setnchannels(1);audio.setsampwidth(1);audio.setframerate(22050);audio.writeframes(bytes([128])*2205)
 script=ROOT/'tools/nec017_unreal_existing_fixture.py'
 shutil.copyfile(script,out/'native-fixture-script.py')
 command=[str(EDITOR),str(uproject),'-run=pythonscript',f'-script={out/"native-fixture-script.py"}','-unattended','-nop4','-nosplash','-NullRHI','-nocef','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={out/"editor.log"}']
 (out/'command.json').write_text(json.dumps(command,indent=2))
 (out/'source-pins.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),script]},indent=2))
 started=time.perf_counter()
 with (out/'native.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,'Native creation failed; retained logs'
 report=json.loads((project/'fixture-created.json').read_bytes());assert report['ok']
 files={p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for base in ['Content','Config','SourceContent'] for p in (project/base).rglob('*') if p.is_file()}
 files[uproject.name]=hashlib.sha256(uproject.read_bytes()).hexdigest()
 for name in ['Content/World.umap','Content/Annex.umap','Content/Crate.uasset','Content/Move.uasset','Content/Tone.uasset']:assert name in files,name
 (out/'pre-adoption-manifest.json').write_text(json.dumps(dict(files=files,fixture=report),indent=2))
 (out/'proof.json').write_text(json.dumps(dict(ok=True,seconds=time.perf_counter()-started,real_native_binary_assets=True,fixture=report,full_nec017_certification=False),indent=2))
 print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]))
