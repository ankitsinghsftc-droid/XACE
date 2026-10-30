"""One diagnostic profile of a 100-object edit using retained native captures."""
from pathlib import Path
import sys,cProfile,pstats
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import nec017_warm_planner as benchmark
out=Path(sys.argv[1]).resolve();original=benchmark.plan_reconciliation

def measured(**kwargs):
 profiler=cProfile.Profile();result=profiler.runcall(original,**kwargs)
 profiler.dump_stats(str(out/'planner.prof'))
 with (out/'profile.txt').open('w') as stream:pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(65)
 print('Diagnostic profile retained; not a certification run',flush=True);raise SystemExit(0)
benchmark.plan_reconciliation=measured
benchmark.main(out)
