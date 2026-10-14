"""Run one reviewed historical gate with fresh persistent output and pinned binaries."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
BASE=Path(os.environ.get('XACE_RECOVERY_EVIDENCE',str(ROOT/'recovery-evidence/20261012/xp022'))).resolve();ART=BASE/'artifacts'
from tools.xp017_mixed_session_proof import GODOT,TEMPLATE
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('gate',choices=['sockets','hosts','process-faults','replay-faults','debugger','player-input','presentation','launch','invite','relay','smoke'])
a=p.parse_args();out=BASE/a.gate;assert not out.exists(),'Never overwrite prior evidence'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
os.environ['XACE_PROOF_HOST']=str(BASE/'pinned-binaries/xace_reference_host.exe')
os.environ['XACE_PROOF_RELAY']=str(BASE/'pinned-binaries/xace-session-relay.exe')
command=[sys.executable,'-B','-m'];extra=[]
if a.gate in ['sockets','hosts']:
 module='tools.xp022_final_proofs';extra=['--artifacts',str(ART),'--mode',a.gate,'--unreal-project',str(ROOT/'recovery-evidence/20261012/xp019/native/target-codex-task66-unreal-vertical-slice/XaceTask66.uproject')]
elif a.gate in ['process-faults','smoke']:
 module='tools.xp022_process_faults' if a.gate=='process-faults' else 'tools.xp022_player_soak';extra=['--artifacts',str(ART)]
 if a.gate=='smoke':extra+=['--seconds','60']
elif a.gate=='replay-faults':
 module='tools.xp022_certification';extra=['--host',os.environ['XACE_PROOF_HOST'],'--recording',str(BASE/'hosts/four/replay.json')]
elif a.gate=='debugger':
 module='tools.xp021_debugger_proof';extra=['--recording',str(BASE/'hosts/four/replay.json'),'--package',str(ART/'parent'),'--current-host',os.environ['XACE_PROOF_HOST']]
elif a.gate in ['player-input','presentation']:
 module='tools.xp008_player_proof' if a.gate=='player-input' else 'tools.xp009_player_proof';extra=['--godot',str(GODOT),'--template',str(TEMPLATE)]
else:
 module={'launch':'tools.xp010_launch_proof','invite':'tools.xp014_session_proof','relay':'tools.xp015_relay_proof'}[a.gate];extra=['--release',str(BASE/'release')]
command += [module,'--out',str(out)]+extra
logs=BASE/'gate-logs';logs.mkdir(exist_ok=True);started=time.monotonic()
with (logs/(a.gate+'.log')).open('xb') as log:
 result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1200,creationflags=subprocess.CREATE_NO_WINDOW)
passed=result.returncode==(2 if a.gate=='replay-faults' else 0)
if a.gate=='replay-faults':passed=passed and json.loads((out/'report.json').read_text())['local_subset_ok']
(logs/(a.gate+'.json')).write_text(json.dumps(dict(fresh_recovery_evidence=True,original_evidence_recovered=False,command=command,returncode=result.returncode,passed=passed,elapsed_seconds=time.monotonic()-started),indent=2))
assert passed,str(logs/(a.gate+'.log'))
print(a.gate+' passed',flush=True)
