"""Actual mixed-host epoch transition using digest-only local control commands."""
import argparse,copy,io,json,zipfile,shutil
from pathlib import Path
from tools.xp017_mixed_session_proof import ROOT,stage,scenario,load,write,GODOT,TEMPLATE
from tools.xp008_player_build import prepare_player,export_player
from tools.xp007_package_proof import compile_plan
from tools.world_extensibility_proof import rehash
from playable_package import RuntimeSupport,build_package,digest

def prepare(out):
    out.mkdir(parents=True,exist_ok=True)
    package=stage(out/'build')
    cgs=load(package/'game.cgs.json');runtime=(ROOT/'target/debug/xace_reference_host.exe').read_bytes()
    visuals={str(p.relative_to(package)).replace('\\','/'):p.read_bytes() for p in (package/'presentation').rglob('*') if p.is_file()}
    for name,policy in [('parent','disabled'),('candidate','reversal_shockwave')]:
        current=copy.deepcopy(cgs)
        def set_policy(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=='third_attempt':value[key]=policy
                    else:set_policy(item)
            elif isinstance(value,list):
                for item in value:set_policy(item)
        set_policy(current);rehash(current);plan,compiled=compile_plan(current)
        support=RuntimeSupport(digest(runtime),'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
        archive=build_package(current,plan,runtime,support,package_id='reference.activation',version='1.0.0',presentation_files=visuals)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:bundle.extractall(out/name)
    export_parent(out)

def export_parent(out):
    parent=out/'parent';cgs=load(parent/'game.cgs.json');_,compiled=compile_plan(cgs)
    support=RuntimeSupport(digest((parent/'runtime/xace_runtime.exe').read_bytes()),'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
    player=out/'build/player';prepare_player(parent,support,player)
    shutil.copy2(ROOT/'tools/xp017_player_proof.gd',player/'mixed_player.gd')
    scene=player/'player.tscn';scene.write_text(scene.read_text().replace('res://player.gd','res://mixed_player.gd'))
    export_player(player,out/'build/exported/xace-mixed-proof.exe',GODOT,TEMPLATE)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',action='store_true');parser.add_argument('--out',type=Path,default=ROOT/'target/xp019/run');parser.add_argument('--scenario',choices=['pair','three','four','all'],default='all');args=parser.parse_args()
    build=ROOT/'target/xp019/artifacts'
    if args.stage:prepare(build)
    activation={'parent':build/'parent','candidate':build/'candidate','native':ROOT/'target/xp019/native'}
    choices={'pair':['player','godot'],'three':['unity','godot','unreal'],'four':['unity','godot','unreal','player']}
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={name:scenario(out/name,engines,build/'build',activation) for name,engines in choices.items() if args.scenario in ['all',name]}
    write(out/'proof.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
