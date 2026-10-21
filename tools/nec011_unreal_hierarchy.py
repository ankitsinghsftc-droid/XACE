"""Fresh native Unreal parent map and production reconciliation proof."""
import json,shutil,subprocess,sys
from pathlib import Path
from nec011_godot_hierarchy import ROOT,sha,NativeEditorGateway,roundtrip

def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    root=out/'project';root.mkdir(parents=True);project=root/'NEC011.uproject'
    project.write_text(json.dumps(dict(FileVersion=3,EngineAssociation='5.7',Plugins=[dict(Name='XACEAuthoring',Enabled=True)])))
    (root/'Config').mkdir();addon='Plugins/XACEAuthoring';plugin=root/addon
    shutil.copytree(ROOT/'adapters/unreal/Authoring',plugin)
    for name in ['NEC011HierarchyCommandlet.cpp','NEC011HierarchyCommandlet.h']:
        shutil.copyfile(ROOT/'tools'/name,plugin/'Source/XACEAuthoring'/('Public' if name.endswith('.h') else 'Private')/name)
    exe=Path('C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe');engine=exe.parents[2]
    commands=[['build',str(engine/'Binaries/ThirdParty/DotNet/8.0.412/win-x64/dotnet.exe'),str(engine/'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'),'UnrealEditor','Win64','Development',f'-Project={project}',f'-plugin={plugin/"XACEAuthoring.uplugin"}','-nohotreload','-installed',f'-log={out/"build-ubt.log"}'],['fixture',str(exe),str(project),'-run=NEC011Hierarchy','-unattended','-nullrhi','-nosplash',f'-abslog={out/"fixture.log"}']]
    for label,*command in commands:
        (out/(label+'-command.json')).write_text(json.dumps(command,indent=2))
        with (out/(label+'.txt')).open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
        assert r.returncode==0,label+' failed; evidence retained'
    pins={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in plugin.rglob('*') if p.is_file() and 'Intermediate' not in p.parts and p.suffix!='.pdb'}
    (out/'sources.json').write_text(json.dumps(pins,indent=2))
    gateway=NativeEditorGateway(root,engine='unreal',executable=str(exe),executable_sha256=sha(exe.read_bytes()),documents=['/Game/Fixture/World'],source_roots=['Content','Config','Plugins','NEC011.uproject'],plugin_hashes=pins,project_file='NEC011.uproject',trusted_closed_project=True)
    roundtrip(out,root,gateway,'unreal','Content/Fixture/World.umap')
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
