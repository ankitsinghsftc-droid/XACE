"""Fresh native authoring regression using source-verified existing editor binaries."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main(out,reuse):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    source=reuse/'project/Plugins/XACEAuthoring'
    inventory={}
    for p in (ROOT/'adapters/unreal/Authoring').rglob('*'):
        if p.is_file():
            relative=p.relative_to(ROOT/'adapters/unreal/Authoring')
            assert p.read_bytes()==(source/relative).read_bytes(),relative
            inventory[relative.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    out.mkdir(parents=True);project=out/'project';project.mkdir()
    plugin=project/'Plugins/XACEAuthoring'
    shutil.copytree(source/'Source',plugin/'Source')
    shutil.copytree(source/'Binaries',plugin/'Binaries')
    shutil.copyfile(source/'XACEAuthoring.uplugin',plugin/'XACEAuthoring.uplugin')
    (out/'sources.json').write_text(json.dumps(inventory,indent=2))
    (out/'binary-identities.json').write_text(json.dumps({p.relative_to(plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (plugin/'Binaries').rglob('*') if p.is_file()},indent=2))
    pf=project/'NEC006.uproject';pf.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACEAuthoring',Enabled=True)])))
    (project/'NEC006.fixture').write_text('Isolated regression fixture')
    (project/'.xace').mkdir();(project/'Config').mkdir()
    (project/'Config/DefaultEngine.ini').write_text('[/Script/Engine.RendererSettings]\nr.RayTracing=False\nr.AllowStaticLighting=False\n')
    sys.path.insert(0,str(ROOT/'packages/project-system'))
    from unreal_authoring import prepare_identity_map,capture,policy,write_request
    from native_authoring_contract import inspect_capture
    from authoring_identity import canonical
    reports={}
    for phase in ['run','reload','interactive']:
        if phase=='reload':
            data=(project/'.xace/native-before.json').read_bytes()
            mapping=prepare_identity_map(data,project_id='nec006-fixture',branch_id='b'*32)
            base=capture(data,mapping,enable_writes=True).admit()
            changed=base.to_dict()['inspection']['capture']
            changed['objects'][f'{2:032x}']['fields']['transform.position']=dict(x='1300',y='1100',z='1200')
            target=inspect_capture(changed,mapping,policy(enable_writes=True)).admit()
            (project/'.xace/python-request.json').write_bytes(write_request(data,base,target,mapping))
        engine=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64')
        command=[str(engine/('UnrealEditor.exe' if phase=='interactive' else 'UnrealEditor-Cmd.exe')),str(pf),'-unattended','-nop4','-nosplash','-NoSound',f'-abslog={out/(phase+"-engine.log")}']
        command+=['-RenderOffscreen','-d3d11','-ExecCmds=XACE.Authoring.Proof interactive'] if phase=='interactive' else ['-NullRHI','-NoShaderCompile','-run=XaceAuthoringProof',f'-Phase={phase}']
        (out/(phase+'-command.json')).write_text(json.dumps(command,indent=2))
        with (out/(phase+'.log')).open('wb') as log:
            r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        assert r.returncode==0,(phase,r.returncode)
        raw=(project/f'.xace/proof-{phase}.json').read_bytes();(out/(phase+'.json')).write_bytes(raw)
        report=json.loads(raw);assert report['ok'];reports[phase]=len(report['cases'])
        if phase=='reload':
            data=(project/'.xace/native-after-python.json').read_bytes()
            actual=capture(data,mapping,enable_writes=True).admit()
            assert actual.to_dict()['inspection']['normalized'][f'{2:032x}']['fields']['transform.position']==dict(x='11000000',y='12000000',z='-13000000')
            assert canonical(json.loads(data))==data
    result=dict(ok=True,checks=reports,source_verified=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
