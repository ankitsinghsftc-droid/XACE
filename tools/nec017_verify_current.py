"""Sequential current-source NEC017 regression and planner measurements."""
from pathlib import Path
import sys,subprocess,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
pins={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sorted((ROOT/'packages/project-system').glob('*.py')),ROOT/'tools/nec017_warm_planner.py']};(out/'source-pins.json').write_text(json.dumps(pins,indent=2))
commands=[[sys.executable,'-B','-m','unittest','discover','-s','packages/project-system/tests','-v'],[sys.executable,'-B','tools/nec017_warm_planner.py',str(out/'warm-planner')]]
results=[]
for index,command in enumerate(commands):
 with (out/(str(index)+'.log')).open('wb') as log:run=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
 results.append(dict(command=command,returncode=run.returncode));(out/'progress.json').write_text(json.dumps(results,indent=2));assert run.returncode==0,results[-1]
(out/'result.json').write_text(json.dumps(dict(commands_succeeded=True,results=results,performance_acceptance='Read warm-planner/measurement.json; successful execution is not a latency pass'),indent=2))
