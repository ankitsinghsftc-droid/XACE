"""Build/run the isolated NEC-006 native Unreal fixture, never a user project."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ENGINE=Path('C:/Program Files/Epic Games/UE_5.7/Engine')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--phase',choices=['build','run','reload','interactive','staged'],default='build')
    args=parser.parse_args();out=args.out.resolve();phase=args.phase
    if not out.is_relative_to(ROOT/'evidence/nec010/ue'):raise ValueError('Output must be under evidence/nec010/ue')
    out.mkdir(parents=True,exist_ok=True)
    project=out/'unreal-project';project.mkdir(exist_ok=True)
    plugin=project/'Plugins/XACEAuthoring'
    project_file=project/'NEC006.uproject'
    project_file.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACEAuthoring',Enabled=True)]),indent=2)+'\n')
    (project/'NEC006.fixture').write_text('Explicit isolated native proof fixture\n')
    (project/'Config').mkdir(exist_ok=True)
    (project/'.xace').mkdir(exist_ok=True)
    if not (project/'Config/DefaultEngine.ini').exists(): (project/'Config/DefaultEngine.ini').write_text('[/Script/Engine.RendererSettings]\nr.RayTracing=False\nr.AllowStaticLighting=False\n')
    if phase=='build':
        shutil.copytree(ROOT/'adapters/unreal/Authoring',plugin,dirs_exist_ok=True)
        host=out/'built-plugin/HostProject'
        built_source=out/'built-plugin'
        if (host/'HostProject.uproject').exists():
            built_source=host/'Plugins/XACEAuthoring'
            shutil.copytree(ROOT/'adapters/unreal/Authoring',built_source,dirs_exist_ok=True)
            command=[str(ENGINE/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(ENGINE/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'UnrealEditor','Win64','Development',f'-Project={host/"HostProject.uproject"}',f'-plugin={built_source/"XACEAuthoring.uplugin"}','-nohotreload','-installed',f'-log={out/"build-ubt.log"}']
        else:
            command=[str(ENGINE/'Build/BatchFiles/RunUAT.bat'),'BuildPlugin',f'-Plugin={plugin/"XACEAuthoring.uplugin"}',f'-Package={out/"built-plugin"}','-TargetPlatforms=Win64','-Rocket']
    else:
        if phase=='staged':
            sys.path.insert(0,str(ROOT/'packages/project-system'))
            from unreal_authoring_stage import inventory,stage
            from authoring_identity import canonical
            source_file=project_file;source_inventory=inventory(source_file)
            project=out/'trusted-stage-project'
            if project.exists(): raise ValueError('Existing staged fixture; use fresh output')
            stage(source_file,project,trusted_project=True,expected_inventory_digest=hashlib.sha256(canonical(source_inventory)).hexdigest())
            (project/'.xace').mkdir(exist_ok=True)
            (project/'NEC006.fixture').write_text('Explicit isolated native proof fixture\n')
            project_file=project/'NEC006.uproject'
        if phase=='reload':
            sys.path.insert(0,str(ROOT/'packages/project-system'))
            from unreal_authoring import prepare_identity_map,capture,policy,write_request
            from native_authoring_contract import inspect_capture
            from authoring_identity import canonical
            data=(project/'.xace/native-before.json').read_bytes()
            mapping=prepare_identity_map(data,project_id='nec006-fixture',branch_id='b'*32)
            base=capture(data,mapping,enable_writes=True).admit()
            changed=base.to_dict()['inspection']['capture']
            changed['objects'][f'{2:032x}']['fields']['transform.position']=dict(x='1300',y='1100',z='1200')
            target=inspect_capture(changed,mapping,policy(enable_writes=True)).admit()
            (project/'.xace/python-request.json').write_bytes(write_request(data,base,target,mapping))
            (out/'native-identity-map.json').write_bytes(canonical(mapping.to_dict()))
            (out/'native-base.snapshot.json').write_bytes(base.payload)
        exe=ENGINE/'Binaries/Win64'/('UnrealEditor.exe' if phase=='interactive' else 'UnrealEditor-Cmd.exe')
        command=[str(exe),str(project_file),'-unattended','-nop4','-nosplash','-NullRHI','-NoSound','-NoShaderCompile','-stdout','-FullStdOutLogOutput',f'-abslog={out/(phase+"-engine.log")}']
        if phase=='interactive':
            command.remove('-NullRHI');command.remove('-NoShaderCompile');command += ['-RenderOffscreen','-d3d11']
        command += ['-ExecCmds=XACE.Authoring.Proof interactive'] if phase=='interactive' else ['-run=XaceAuthoringProof',f'-Phase={"capture" if phase=="staged" else phase}']
    old=[out/(phase+s) for s in ['.json','-command.json','-process.log','-engine.log']]
    if any(p.exists() for p in old): raise ValueError('Existing phase evidence; use fresh output')
    if phase=='run' and (project/'Content/Fixture').exists(): raise ValueError('Existing native fixture; use fresh output')
    (out/(phase+'-command.json')).write_text(json.dumps(dict(command=command,cwd=str(ROOT)),indent=2)+'\n')
    with (out/(phase+'-process.log')).open('wb') as log:
        result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1200 if phase=='build' else 240,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError(f'{phase} failed ({result.returncode}); inspect log')
    if phase=='build':
        for folder in ['Binaries','Intermediate']:
            if (built_source/folder).exists():shutil.copytree(built_source/folder,plugin/folder,dirs_exist_ok=True)
        print('Built installed Unreal editor module');return
    report=json.loads((project/f'.xace/proof-{"capture" if phase=="staged" else phase}.json').read_text())
    (out/(phase+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    if not report['ok']:raise RuntimeError('Native proof assertions failed')
    if phase=='staged':
        assert inventory(source_file)==source_inventory
        staged_data=(project/'.xace/native-staged.json').read_bytes()
        assert staged_data==(source_file.parent/'.xace/native-before.json').read_bytes()
        (out/'trusted-stage-proof.json').write_text(json.dumps(dict(ok=True,source_unchanged=True,staged_capture_identical=True,files=len(source_inventory['files'])),indent=2)+'\n')
    if phase=='reload':
        data=(project/'.xace/native-after-python.json').read_bytes();actual=capture(data,mapping,enable_writes=True).admit()
        position=actual.to_dict()['inspection']['normalized'][f'{2:032x}']['fields']['transform.position']
        assert position==dict(x='11000000',y='12000000',z='-13000000')
        assert canonical(json.loads(data))==data
        (out/'native-after.snapshot.json').write_bytes(actual.payload)
        (out/'python-bridge-proof.json').write_text(json.dumps(dict(ok=True,canonical_native_json=True,position=position,base_sha256=base.sha256,after_sha256=actual.sha256),indent=2)+'\n')
    print(json.dumps(dict(ok=True,phase=phase,checks=len(report['cases']),version=report['engine_version'])))


if __name__=='__main__':main()
