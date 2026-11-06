"""Sequential current-source NEC017 regression and planner measurements."""
from pathlib import Path
import sys,subprocess,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
sources=sorted(set([*sorted((ROOT/'packages/project-system').rglob('*.py')),*sorted((ROOT/'packages/schema-factory/src').rglob('*.py')),*sorted((ROOT/'packages/gde/src').rglob('*.py')),ROOT/'tools/cgs_schema_validate.py',ROOT/'tools/nec017_warm_planner.py',Path(__file__).resolve()]))
pins={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources};(out/'source-pins.json').write_text(json.dumps(pins,indent=2))
commands=[[sys.executable,'-B','-m','unittest','discover','-s','packages/project-system/tests','-v'],[sys.executable,'-B','-m','pytest','packages/schema-factory/src/tests','-q','-p','no:cacheprovider'],[sys.executable,'-B','tools/nec017_warm_planner.py',str(out/'warm-planner')]]
regressions_only='--regressions-only' in sys.argv
if regressions_only:commands=commands[:2]
results=[]
for index,command in enumerate(commands):
 with (out/(str(index)+'.log')).open('wb') as log:run=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
 results.append(dict(command=command,returncode=run.returncode));(out/'progress.json').write_text(json.dumps(results,indent=2));assert run.returncode==0,results[-1]
changed=[name for name,expected in pins.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected]
(out/'source-stability.json').write_text(json.dumps(dict(unchanged=not changed,changed=changed),indent=2));assert not changed,'Source changed during verification; retained run is not a current-source pass'
(out/'result.json').write_text(json.dumps(dict(commands_succeeded=True,results=results,performance_acceptance='Not rerun: regressions-only mode' if regressions_only else 'Read warm-planner/measurement.json; successful execution is not a latency pass'),indent=2))
