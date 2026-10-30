"""Native edit rebase in a fresh reviewed fork with protected prior Git refs."""
from pathlib import Path
import sys,json,importlib,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec017_godot_branch_merge import git,publish
from native_workspace_fork import review_fork,apply_fork
from native_branch_contribution import capture_contribution
from authoring_transaction_files import load_json,sha
from authoring_identity import canonical,IdentityMap
from authoring_saved_pair import MAP,verify_baseline_receipts
from tools.world_extensibility_proof import rehash

def main(out,engine,source_proof):
 out=out.resolve();source_proof=source_proof.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert source_proof.is_relative_to(ROOT/'evidence/nec017');assert load_json(source_proof/'proof.json')['ok'];out.mkdir(parents=True)
 module=importlib.import_module('tools.nec017_'+engine+'_crash');source=source_proof/'alice';g=module.gateway(source);h=module.host(source,g);root=out/'rebased-developer'
 review=review_fork(h,root,'e'*32,'rebased-developer');apply_fork(h,review,review['review_digest'],'rebased-developer')
 (root/'.gitattributes').write_bytes(b'* -text\n');base=git(source,'rev-parse','HEAD');git(root,'init','-b','rebased');git(root,'fetch',str(source),'alice');git(root,'read-tree','FETCH_HEAD');git(root,'update-ref','refs/heads/rebased',base,'0'*40)
 current=module.host(root,module.gateway(root));before_mapping=IdentityMap.from_dict(load_json(root/MAP));c=load_json(root/'game.cgs.json');c['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']=303000000;rehash(c);(root/'game.cgs.json').write_bytes(canonical(c));publish(current,'rebased-developer')
 paths=['game.cgs.json',*current.gateway.sources];git(root,'add','--',*paths);git(root,'commit','-m','Native edit before reviewed rebase');old=git(root,'rev-parse','HEAD');git(root,'branch','protected-before-rebase',old)
 original=capture_contribution(current,'rebased-developer',old);(out/'before-contribution.json').write_bytes(original)
 files=current.gateway._files();files['game.cgs.json']=sha((root/'game.cgs.json').read_bytes());native_identity=IdentityMap.from_dict(load_json(root/MAP)).to_dict()
 tree=git(root,'rev-parse',base+'^{tree}');alternate=git(root,'commit-tree',tree,'-p',base,'-m','Alternate upstream checkpoint without native changes')
 # All prior work remains reachable through protected-before-rebase. This is
 # a new test repository, not any original/recovery implementation repository.
 git(root,'rebase','--keep-empty','--onto',alternate,base,'rebased');new=git(root,'rev-parse','HEAD');assert new!=old and git(root,'rev-parse','protected-before-rebase')==old
 assert all(sha((root/name).read_bytes())==value for name,value in files.items())
 assert IdentityMap.from_dict(load_json(root/MAP)).to_dict()==native_identity
 try:capture_contribution(current,'rebased-developer',old)
 except ValueError as exc:assert 'HEAD changed' in str(exc)
 else:raise AssertionError('old rebase checkpoint accepted')
 refreshed=capture_contribution(current,'rebased-developer',new);(out/'after-contribution.json').write_bytes(refreshed)
 m=IdentityMap.from_dict(load_json(root/MAP));assert m.namespace_id==before_mapping.namespace_id and m.mapping_digest()==before_mapping.mapping_digest() and verify_baseline_receipts(root,m.baseline)
 assert current.review.open('rebased-developer')['report']['noop']
 result=dict(ok=True,engine=engine,actual_git_rebase=True,old_checkpoint=old,new_checkpoint=new,protected_prior_ref='protected-before-rebase',source_workspace_unchanged=True,native_and_canonical_bytes_preserved=True,identity_and_baseline_preserved=True,old_export_checkpoint_refused=True,reopened_noop=True,full_nec017_certification=False)
 (out/'proof.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)
if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]))
