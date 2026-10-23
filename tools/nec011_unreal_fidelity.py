import json,shutil,sys,subprocess,hashlib
from pathlib import Path
import unreal_vertical_slice_certification as old
ROOT=Path(__file__).resolve().parents[1]
def main(out,reuse=None):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists();out.mkdir(parents=True)
    project=out/'project';project.mkdir()
    project_file=project/'NEC011.uproject';project_file.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACE',Enabled=True)])))
    plugin=project/'Plugins/XACE'
    for relative,text in old.unreal_generated_plugin_texts().items():
        path=plugin/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
    for name in (*old.ADAPTER_SOURCE_NAMES,"XaceNativeContractProofCommandlet.h","XaceNativeContractProofCommandlet.cpp","XaceMixedSessionProof.h"):
        destination=plugin/'Source/XACEAdapter'/('Public' if name.endswith('.h') else 'Private')/name
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'adapters/unreal'/name,destination)
    stage=dict(plugin_root=plugin,project_file=project_file);sources={}
    for name in ['NEC011FidelityCommandlet.h','NEC011FidelityCommandlet.cpp']:
        src=ROOT/'tools'/name;shutil.copyfile(src,plugin/'Source/XACEAdapter'/('Public' if name.endswith('.h') else 'Private')/name)
    for p in (plugin/'Source').rglob('*'):
        if p.is_file():sources[p.relative_to(plugin).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    (out/'sources.json').write_text(json.dumps(sources,indent=2))
    exe=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe')
    if reuse is not None:
        assert sources==json.loads((reuse/'sources.json').read_text()),'Cannot reuse binaries built from different source'
        shutil.copytree(reuse/'project/Plugins/XACE/Binaries',plugin/'Binaries')
        (out/'reused-build.json').write_text(json.dumps(dict(source=str(reuse),binaries={p.relative_to(plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (plugin/'Binaries').rglob('*') if p.is_file()}),indent=2))
    else:
        engine=exe.parents[2]
        build=[str(engine/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'UnrealEditor','Win64','Development',f'-Project={project_file}',f'-plugin={plugin/"XACE.uplugin"}','-nohotreload','-installed',f'-log={out/"build-ubt.log"}']
        (out/'build-command.json').write_text(json.dumps(build,indent=2))
        with (out/'build.txt').open('wb') as log:result=subprocess.run(build,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,'Unreal editor compilation failed; retained logs'
    command=[str(exe),str(stage['project_file']),'-run=NEC011Fidelity','-AllowCommandletAudio','-unattended','-nullrhi','-nosplash',f'-XaceReport={out/"proof.json"}',f'-abslog={out/"editor.log"}']
    (out/'command.json').write_text(json.dumps(command,indent=2))
    with (out/'run.txt').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,'Native fidelity proof failed; retained logs'
    report=json.loads((out/'proof.json').read_text());assert report['ok'],report;print(json.dumps(report,indent=2))
    fixture=ROOT/'adapters/tests/fixtures/xp016-contract-v1.json'
    command=[str(exe),str(project_file),'-run=XaceNativeContractProof','-unattended','-nullrhi','-nosplash',f'-XaceFixture={fixture}',f'-XaceReport={out/"contract.json"}',f'-abslog={out/"contract-editor.log"}']
    (out/'contract-command.json').write_text(json.dumps(command,indent=2))
    with (out/'contract-run.txt').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
    assert r.returncode==0,'Native contract regression failed; retained logs'
    report=json.loads((out/'contract.json').read_text(encoding='utf-8-sig'));assert report['ok'],report;print(json.dumps(report,indent=2))

if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve() if len(sys.argv)>2 else None)
