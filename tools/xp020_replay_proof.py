"""Proof G: real accepted inputs, historical epochs and independent offline forks."""
import argparse,json,subprocess
from pathlib import Path
from tools.xp019_activation_proof import prepare
from tools.xp017_mixed_session_proof import ROOT,scenario,load,write

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',action='store_true');parser.add_argument('--out',type=Path,default=ROOT/'recovery-evidence/xp020/proof');parser.add_argument('--artifacts',type=Path,default=ROOT/'recovery-evidence/xp020/artifacts');parser.add_argument('--unreal-project',type=Path,default=ROOT/'recovery-evidence/xp019/native/target-codex-task66-unreal-vertical-slice/XaceTask66.uproject');args=parser.parse_args()
    artifacts=args.artifacts.resolve()
    if args.stage:prepare(artifacts)
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    matrix=scenario(out/'live',['unity','godot','unreal','player'],artifacts/'build',args.unreal_project.resolve(),{'parent':artifacts/'parent','candidate':artifacts/'candidate','record_replay':True})
    bundle=load(out/'live/replay.json');assert sum(len(t['inputs']) for t in bundle['bundle']['ticks'])>0
    reports={}
    for name,end in [('before',7),('at',8),('after',39),('repeat',39),('rewind',7)]:
        report=out/(name+'.json')
        command=[str(artifacts/'parent/runtime/xace_runtime.exe'),'--epoch-replay-in',str(out/'live/replay.json'),'--epoch-replay-report',str(report),'--epoch-replay-through-tick',str(end)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/(name+'.log')).write_text(result.stdout+result.stderr)
        assert result.returncode==0,(name,result.stderr[-2000:])
        reports[name]=load(report);assert reports[name]['ok'] and reports[name]['verified_ticks']==end+1 and reports[name]['presentation_effects_emitted']==0
    result={'schema':'xace.xp020.proof.v1','ok':True,'scope':'Windows only, local actual four-host recording; offline replay forks','live':matrix,'replays':reports,'accepted_input_packets':sum(len(t['inputs']) for t in bundle['bundle']['ticks'])}
    write(out/'proof.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
