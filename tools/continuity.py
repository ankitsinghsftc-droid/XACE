"""Explicit, offline continuity CLI. Requests are data; no embedded commands run."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'packages/project-system'))
from continuity_contract import ArchiveRequest,SourceRoot,Dependency,Checkpoint,Prerequisite,Omission,canonical
from continuity_archive import create_archive,verify_archive,restore_archive
from continuity_detach import review_detach,apply_detach

def request(path):
    p=Path(path).absolute();v=json.loads(p.read_text(encoding='utf-8'))
    roots=tuple(SourceRoot(r['key'],r['role'],(p.parent/r['path']).absolute()) for r in v['roots'])
    return ArchiveRequest(v['project_id'],roots,tuple(Dependency(**r) for r in v['dependencies']),tuple(Checkpoint(**r) for r in v['checkpoints']),tuple(Prerequisite(**r) for r in v['prerequisites']),tuple(Omission(**r) for r in v.get('omissions',[])),v.get('reviewed_declared_closure',False))
def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='op',required=True)
    c=sub.add_parser('create');c.add_argument('request');c.add_argument('output',type=Path);c.add_argument('--allow-incomplete',action='store_true')
    for name in ['verify','restore','review-detach']:
        p=sub.add_parser(name);p.add_argument('archive',type=Path);p.add_argument('--sha256',required=True)
        if name!='verify':p.add_argument('destination',type=Path)
        if name=='restore':p.add_argument('--allow-incomplete',action='store_true')
        if name=='review-detach':
            p.add_argument('--mode',choices=['retain-runtime','remove-adapter'],default='retain-runtime');p.add_argument('--native-root');p.add_argument('--engine',choices=['godot','unity','unreal'])
    p=sub.add_parser('apply-detach');p.add_argument('archive',type=Path);p.add_argument('review',type=Path);p.add_argument('--approve',required=True)
    a=parser.parse_args()
    if a.op=='create':value=create_archive(request(a.request),a.output,allow_incomplete=a.allow_incomplete)
    elif a.op=='verify':value=verify_archive(a.archive,a.sha256)
    elif a.op=='restore':value=restore_archive(a.archive,a.sha256,a.destination,allow_incomplete=a.allow_incomplete)
    elif a.op=='review-detach':value=review_detach(a.archive,a.sha256,a.destination,mode=a.mode,native_root=a.native_root,engine=a.engine)
    else:value=apply_detach(a.archive,json.loads(a.review.read_text(encoding='utf-8')),a.approve)
    print(json.dumps(value,indent=2,sort_keys=True))
if __name__=='__main__':main()
