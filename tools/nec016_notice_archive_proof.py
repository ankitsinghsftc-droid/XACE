from pathlib import Path
import json,sys,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from continuity_contract import *
from continuity_archive import create_archive,restore_archive,verify_archive,file_hash,MANIFEST
from tools.continuity_notices import verify_notices

def main(out):
 out=out.resolve();require(out.is_relative_to(ROOT/'evidence/nec016') and not out.exists(),'fresh durable output required');out.mkdir(parents=True)
 prior=ROOT/'evidence/nec016/20261028/restore-c';notices=ROOT/'evidence/nec016/20261028/notices-a';notice=verify_notices(notices)
 old=json.loads((prior/'independent'/MANIFEST).read_bytes())
 paths={r['key']:prior/'inputs'/r['key'] for r in old['roots']};paths['runtime']=ROOT/'evidence/nec014/20261025/export-final-g/project/release';paths['notices']=notices
 request=ArchiveRequest(old['project_id'],tuple(SourceRoot(r['key'],r['role'],paths[r['key']]) for r in old['roots']),(Dependency('pinned native notice inventory','payload/notices/notices.manifest.json'),),tuple(Checkpoint(r['path'],r['sha256']) for r in old['checkpoints']),tuple(Prerequisite(**r) for r in old['prerequisites']),tuple(Omission(**r) for r in old['omissions']),True)
 archive=out/'continuity.zip';receipt=create_archive(request,archive);restored=out/'independent';restoration=restore_archive(archive,receipt['archive_sha256'],restored)
 fresh=verify_archive(archive,receipt['archive_sha256']);before={r['path']:r for r in old['files'] if r['role']!='notices'};after={r['path']:r for r in fresh['files'] if r['role']!='notices'};require(before==after,'non-notice content drift')
 verify_notices(restored/'payload/notices')
 # The exact code/runtime/native bytes retain the prior real independent rebuild
 # proof. Add notices to a NEW shipped artifact without mutating that proof.
 shipping=out/'shipping';shutil.copytree(ROOT/'evidence/nec016/20261028/network-b/build/shipping',shipping);shutil.copytree(notices,shipping/'NOTICES')
 result=dict(schema='xace.nec016.notice_archive_proof.v1',ok=True,declared_private_engineering_closure_complete=True,public_redistribution_approved=False,notice_packages=len(notice['packages']),notice_files=len(notice['files']),archive=receipt,restore=restoration,all_non_notice_archive_bytes_unchanged=True,independent_rebuild_proof='evidence/nec016/20261028/restore-c/proof.json',network_denied_binary_proof='evidence/nec016/20261028/network-b/firewall-run/result.json',shipping_files={p.relative_to(shipping).as_posix():file_hash(p) for p in shipping.rglob('*') if p.is_file()})
 (out/'proof.json').write_bytes(canonical(result));print(json.dumps({k:v for k,v in result.items() if k!='shipping_files'}))
if __name__=='__main__':main(Path(sys.argv[1]))
