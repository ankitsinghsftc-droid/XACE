"""Actual Godot reviewed fork; retain ancestor history and independent active baseline."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec017_godot_crash import gateway,host,fixture
from native_workspace_fork import review_fork,apply_fork,io_path
from authoring_transaction_files import load_json,sha
from authoring_identity import IdentityMap,canonical
from authoring_saved_pair import MAP,verify_baseline_receipts

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 source=fixture(out/'source');g=gateway(source);h=host(source,g)
 try:review_fork(h,out/'dirty-refused','c'*32,'alice')
 except ValueError as exc:assert 'saved canonical revision differs' in str(exc)
 else:raise AssertionError('dirty source fork admitted')
 assert not (out/'dirty-refused').exists()
 opened=h.review.open('source-developer');approval=h.review.approve('source-developer',opened['token'],opened['proposal_digest']);assert h.apply('source-developer',approval,approval['proposal_digest'])['state']=='committed'
 original={p.relative_to(source).as_posix():sha(p.read_bytes()) for p in (source/'.xace/authoring-transactions').rglob('*') if p.is_file()}
 destination=out/'developer-alice';review=review_fork(h,destination,'c'*32,'alice');(out/'review.json').write_bytes(canonical(review))
 receipt=apply_fork(h,review,review['review_digest'],'alice');(out/'receipt.json').write_bytes(canonical(receipt))
 target=IdentityMap.from_dict(load_json(destination/MAP));old=IdentityMap.from_dict(load_json(source/MAP))
 assert target.branch_id=='c'*32 and old.branch_id=='b'*32 and target.namespace_id==old.namespace_id and target.mapping_digest()==old.mapping_digest()
 assert all(sha((source/p).read_bytes())==v for p,v in original.items())
 assert all(sha((io_path(destination)/receipt['ancestor_history']/p).read_bytes())==v for p,v in review['ancestor_history'].items())
 assert verify_baseline_receipts(destination,target.baseline)
 child=host(destination,gateway(destination));assert not child.status()['play_build_blocked'];assert child.review.open('alice')['report']['noop']
 result=dict(ok=True,real_editor=True,ancestor_history_retained=True,old_journals_unchanged=True,new_branch_same_object_ids=True,fresh_baseline_verified=True,reopened_noop=True,dirty_source_refused=True,full_collaboration_certification=False)
 (out/'proof.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))
