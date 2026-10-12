"""Real approved Builder/GDE/Factory/SGC artifacts -> isolated Rust candidate proof.

No activation, native editor launch, provider call or write to the active project.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import importlib
import zipfile
import io
from tools.xp006_authoring_proof import ROOT, run
from tools.xp007_package_proof import compile_plan
from tools.world_extensibility_proof import rehash
from playable_package import RuntimeSupport,build_package,digest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=ROOT/'target/xp018/proof')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    authored=asyncio.run(run(out/'authored'))
    # Approval credentials are only used in the in-process Builder flow.
    authored['variants']={k:{n:v[n] for n in ('cgs_hash','world_hash')} for k,v in authored['variants'].items()}
    env=os.environ.copy();env['XACE_CANDIDATE_FIXTURE_ROOT']=str(out/'authored');env['XACE_CANDIDATE_REPORT']=str(out/'runtime-proof.json')
    with (out/'runtime-tests.log').open('w') as log:
        result=subprocess.run(['cargo','test','-p','xace-reference-mechanic','--test','candidate','--offline','--','--nocapture'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('Candidate proof failed: '+str(out/'runtime-tests.log'))
    # Recompile the same approved configurations for the live EngineInputSystem
    # host profile; no recording system is installed into the live session.
    live=out/'live';live.mkdir(exist_ok=True)
    subprocess.run(['cargo','build','-p','xace-reference-mechanic','--example','candidate_session','--offline','--quiet'],cwd=ROOT,env=env,check=True)
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--no-deps','--format-version','1','--offline'],cwd=ROOT,env=env))
    executable=Path(metadata['target_directory'])/'debug/examples'/('candidate_session.exe' if os.name=='nt' else 'candidate_session')
    runtime=executable.read_bytes()
    for name,source in [('parent',out/'authored'),('candidate',out/'authored/reversal_shockwave')]:
        cgs=json.loads((source/'game.cgs.json').read_text())
        cgs['global_systems']=[{'id':'EngineInputSystem','phase':'Input','reads':[],'writes':[6],'depends_on':[],'deterministic':True}]
        cgs['modes'][0]['systems']=[s for s in cgs['modes'][0]['systems'] if s['id']!='reference.recorded_input.v1']
        for system in cgs['modes'][0]['systems']:
            system['depends_on']=['EngineInputSystem' if dependency=='reference.recorded_input.v1' else dependency for dependency in system.get('depends_on',[])]
        cgs['modes'][0]['world']['contract']=importlib.import_module('schema-factory.src.world_contract_v3').migrate_v2_source(cgs['modes'][0]['world']['contract'])
        rehash(cgs);plan,compiled=compile_plan(cgs)
        support=RuntimeSupport(digest(runtime),'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
        settings={'schema':'xace.player.controls.v1','controller_id':1,'instructions':'Reference proof','bindings':[{'action':'Jump','positive':32,'kind':'button'}]}
        archive=build_package(cgs,plan,runtime,support,package_id='reference.candidate',version='1.0.0',presentation_files={'presentation/player/settings.json':json.dumps(settings).encode()})
        with zipfile.ZipFile(io.BytesIO(archive)) as package:package.extractall(live/name)
    with (out/'live-tests.log').open('w') as log:
        result=subprocess.run(['cargo','run','-p','xace-reference-mechanic','--example','candidate_session','--offline','--',str(live)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError('Live isolation proof failed: '+str(out/'live-tests.log'))
    evidence={'schema':'xace.xp018.end_to_end_proof.v1','ok':True,'authoring':authored,'candidate':json.loads((out/'runtime-proof.json').read_text()),'live_isolation':json.loads((live/'live-proof.json').read_text()),'scope':'isolated preparation only; no active epoch transition'}
    (out/'proof.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'ok':True,'proof':str(out/'proof.json')},indent=2))

if __name__=='__main__':main()
