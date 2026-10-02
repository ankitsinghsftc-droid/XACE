"""Authoring-time release assembly. Recipient launch never invokes build tools."""
from pathlib import Path
import json,sys,shutil,subprocess,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from tools.xp008_player_build import export_player
from playable_package import digest
TEMPLATE_SHA256='91724f15024a3a545e28ccd83134403d31ce2323a38e51c95e4dfa282f732ab6'
GODOT_VERSION='4.6.3.stable.official.7d41c59c4'

def assemble(project,out,godot,template,broker):
    project=Path(project).resolve();out=Path(out).resolve()
    if out.exists():raise ValueError('Choose a new release output directory')
    if digest(Path(template).read_bytes())!=TEMPLATE_SHA256:raise ValueError('Export template checksum mismatch')
    version=subprocess.check_output([str(godot),'--version'],text=True).strip()
    if version!=GODOT_VERSION:raise ValueError('Export editor version mismatch')
    out.mkdir(parents=True)
    export_player(project,out/'xace-player.exe',godot,template)
    shutil.copy2(broker,out/'XACE Play.exe')
    shutil.copy2(project/'admission.json',out/'admission.json')
    # Query the actual pinned engine; include complete engine and dependency notices.
    notice_script=project/'release_notices.gd'
    notice_script.write_text('extends SceneTree\nfunc _initialize():\n\tvar file=FileAccess.open(OS.get_cmdline_user_args()[0],FileAccess.WRITE)\n\tfile.store_string(Engine.get_license_text()+"\\n"+JSON.stringify(Engine.get_copyright_info(),"  ")+"\\n"+JSON.stringify(Engine.get_license_info(),"  "))\n\tquit()\n')
    result=subprocess.run([str(godot),'--headless','--path',str(project),'--script',str(notice_script),'--',str(out/'GODOT_NOTICES.txt')],capture_output=True,text=True,timeout=20)
    if result.returncode or 'SCRIPT ERROR' in result.stdout+result.stderr:raise RuntimeError(result.stdout+result.stderr)
    notice_script.unlink()
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--offline','--format-version','1'],cwd=ROOT))
    notices=['XACE Player distribution. Workspace crates declare MIT.','Godot license and bundled components: GODOT_NOTICES.txt','Rust dependency declarations and supplied license files follow.']
    for package in sorted(metadata['packages'],key=lambda p:(p['name'],p['version'])):
        notices.append('\n'+package['name']+' '+package['version']+' '+str(package.get('license')))
        folder=Path(package['manifest_path']).parent
        if not folder.is_relative_to(ROOT):
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.name.upper().startswith(('LICENSE','COPYING','COPYRIGHT','NOTICE')):
                    notices.append(path.name+'\n'+path.read_text(encoding='utf8',errors='replace'))
    (out/'NOTICES.txt').write_text('\n'.join(notices),encoding='utf8')
    (out/'README.txt').write_text('XACE Player - Windows x86_64\n\nExtract the entire release folder, then open XACE Play.exe.\nKeep the Player, package, checksums and notices together.\nThe launcher verifies and installs into LocalAppData/XACE/Player.\nClose the game window to exit. No engine editor or developer tools required.\n\nThis is an unsigned local release; obtain it from a trusted publisher.\nDeclared target: Windows 10/11 x86_64, OpenGL 3.3-compatible graphics.\nClean-machine compatibility is not yet certified.\n',encoding='utf8')
    manifest=json.loads((out/'package/playable.manifest.json').read_text())
    records=[]
    for path in sorted(out.rglob('*')):
        if path.is_file() and not path.name.endswith('.export.log'):
            data=path.read_bytes();records.append({'path':path.relative_to(out).as_posix(),'sha256':digest(data),'size':len(data)})
    distribution={'schema':'xace.player.distribution.v1','platform':'windows-x86_64','version':'0.1.0','gameplay_hash':manifest['gameplay_hash'],'cgs_hash':manifest['gameplay']['cgs_hash'],'files':records}
    raw=json.dumps(distribution,sort_keys=True,separators=(',',':')).encode();(out/'distribution.json').write_bytes(raw)
    trust={'schema':'xace.player.distribution_trust.v1','manifest_sha256':digest(raw),'broker_sha256':digest((out/'XACE Play.exe').read_bytes()),'godot_version':version,'template_sha256':TEMPLATE_SHA256}
    (out/'distribution.trust.json').write_text(json.dumps(trust,indent=2))
    archive=out.with_suffix('.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(out.rglob('*')):
            if path.is_file() and not path.name.endswith('.export.log'):z.write(path,path.relative_to(out))
    return {**trust,'bytes':sum(r['size'] for r in records),'zip_bytes':archive.stat().st_size,'directory':str(out)}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ['project','out','godot','template','broker']:parser.add_argument('--'+option,required=True)
    args=parser.parse_args()
    print(json.dumps(assemble(args.project,args.out,args.godot,args.template,args.broker),indent=2))
