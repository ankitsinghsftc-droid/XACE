"""Compile the isolated echo benchmark through existing Factory and persisted SGC."""
import copy,hashlib,importlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages')]
from tools.xp005_reference_proof import fixture
from tools.cgs_schema_validate import compute_cgs_hash

def compile_fixture(out,sgc):
    cgs=fixture();mode=cgs['modes'][0];actor=copy.deepcopy(mode['actors'][2]);actor.update(id='graph',actor_type='WORLD_OBJECT',control_type='NONE')
    actor['components']=[c for c in actor['components'] if c['type_id'] in (1,2)]
    state=dict(last_tick=None,next_sequence=0,last_input=None,energy={},pending=[])
    config=dict(schema_version=1,nodes=[1,2,3],edges=[dict(id=1,source=1,target=2,delay=2,gain=1000000,route=1),dict(id=2,source=2,target=3,delay=1,gain=-1000000,route=1)],threshold=1000000)
    input_=dict(pulse=dict(tick=0,id=1,node=1,amplitude=1000000))
    schemas=[]
    for tid,name,value in [(10020,'GCL_ECHO_STATE_V1',state),(10021,'GCL_ECHO_CONFIG_V1',config),(10022,'GCL_ECHO_INPUT_V1',input_)]:
        defaults=dict(data=value);schemas.append(dict(type_id=tid,name=name,source='gcl',defaults=defaults));actor['components'].append(dict(type_id=tid,name=name,defaults=copy.deepcopy(defaults)))
    cgs['component_schemas']=schemas;cgs['global_systems']=[];mode['actors']=[actor]
    mode['systems']=[dict(id='nec011.echo_graph.v1',phase='Simulation',reads=[10020,10021,10022],writes=[10020],depends_on=[],deterministic=True)]
    mode['world']['contract']['objects']=[dict(id='graph',actor_id='graph',kind='anchor',capabilities=[])]
    mode['world']['contract']['capability_declarations']=[]
    cgs['metadata']['name']='NEC011 delayed echo graph';cgs['metadata']['cgs_hash']=compute_cgs_hash(cgs)
    factory=importlib.import_module('schema-factory.src.portable_compilation');package=factory.compile_portable_cgs(cgs)
    envelope=dict(systems=package.to_sgc_input(),schema_version=package.schema_version,cgs_hash=package.cgs_hash,plan_version=1)
    r=subprocess.run([str(sgc)],input=json.dumps(envelope),capture_output=True,text=True,check=True);plan=json.loads(r.stdout)
    out.mkdir(exist_ok=False)
    files={'game.cgs.json':json.dumps(cgs,indent=2).encode(),'execution_plan.json':json.dumps(plan,indent=2).encode(),'world.json':package.world_contract.content_bytes,'world.manifest.json':package.world_contract.manifest_bytes}
    for name,data in files.items():(out/name).write_bytes(data)
    (out/'compilation.json').write_text(json.dumps(dict(ok=True,cgs_hash=package.cgs_hash,plan_hash=plan['plan_hash'],sgc_sha256=hashlib.sha256(sgc.read_bytes()).hexdigest(),files={n:hashlib.sha256(b).hexdigest() for n,b in files.items()}),indent=2))
if __name__=='__main__':compile_fixture(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
