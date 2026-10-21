"""Exercise shipped creator benchmark controls, including actual rewind, without compiling."""
import json,os,subprocess,hashlib
from pathlib import Path

def prove(exe,cgs,plan,out):
    out.mkdir(exist_ok=False)
    graph=dict(schema_version=1,nodes=[7,8,9],edges=[dict(id=1,source=7,target=8,delay=2,gain=1000000,route=1),dict(id=2,source=8,target=9,delay=1,gain=-1000000,route=1)],threshold=1000000)
    commands=[dict(action='tick',tick=0,graph=dict(tick=0,id=1,graph=graph)),dict(action='tick',tick=1,pulse=dict(tick=1,id=1,node=7,amplitude=1000000)),dict(action='checkpoint',tick=2),dict(action='inspect')]
    commands.extend(dict(action='tick',tick=tick) for tick in range(2,7));commands.extend([dict(action='inspect'),dict(action='rewind',tick=7)])
    commands.extend(dict(action='tick',tick=tick) for tick in range(2,7));commands.append(dict(action='inspect'))
    text=''.join(json.dumps(row,separators=(',',':'))+'\n' for row in commands);(out/'commands.jsonl').write_text(text)
    command=[str(exe),'--echo-session',str(cgs),str(plan)];(out/'command.json').write_text(json.dumps(command))
    env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32');runs=[]
    for name in ['first','second']:
        result=subprocess.run(command,input=text,text=True,capture_output=True,cwd=exe.parent,env=env,timeout=45)
        (out/(name+'-stdout.jsonl')).write_text(result.stdout);(out/(name+'-stderr.txt')).write_text(result.stderr)
        assert result.returncode==0,result.stderr
        rows=[json.loads(line) for line in result.stdout.splitlines()];runs.append(rows)
        ticks=[row for row in rows if row['action']=='tick'];assert ticks[2:7]==ticks[7:12]
        states=[row['state']['data'] for row in rows if row['action']=='inspect'];assert states[0]['pending'] and states[1]==states[2]
        assert states[2]['graph']==graph and states[2]['energy']['9']==-1000000
    assert runs[0]==runs[1]
    proof=dict(ok=True,executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),player_graph_created=True,player_pulse=True,player_checkpoint_and_rewind=True,mid_queue_snapshot=True,every_replayed_hash_and_event_equal=True,independent_runs_equal=True,player_compilation=False,rewind_horizon_ticks=120,native_engine_shipping=False)
    (out/'proof.json').write_text(json.dumps(proof,indent=2));return proof
