from pathlib import Path
import sys,subprocess,json
ROOT=Path(__file__).resolve().parents[1];out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True);fixture=out/'native';results=[]
for phase in ['run','reload','play','privilege']:
 command=[sys.executable,'-B','tools/nec005_godot_proof.py','--out',str(fixture),'--phase',phase]
 with (out/(phase+'.log')).open('wb') as f:run=subprocess.run(command,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
 results.append(dict(phase=phase,returncode=run.returncode));(out/'progress.json').write_text(json.dumps(results,indent=2));assert run.returncode==0,results[-1]
(out/'proof.json').write_text(json.dumps(dict(ok=True,results=results),indent=2))
