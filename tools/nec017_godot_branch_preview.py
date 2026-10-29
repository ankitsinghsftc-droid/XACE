"""Independent native developer branches and immutable Git-pinned merge preview."""
from pathlib import Path
import sys,json,subprocess,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec017_godot_crash import fixture,gateway,host
from native_workspace_fork import review_fork,apply_fork
from native_branch_contribution import capture_contribution,plan_contribution
from authoring_transaction_files import load_json,sha
from authoring_identity import canonical
from tools.world_extensibility_proof import rehash

PATHS=['game.cgs.json','XACEGenerated','addons','project.godot','xace_protocol.gd']
def git(root,*args):
 p=subprocess.run(['git','-c','gc.auto=0','-c','user.name=NEC017 local fixture','-c','user.email=nec017@example.invalid','-C',str(root),*args],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
 assert p.returncode==0,(args,p.stderr.decode(errors='replace'));return p.stdout.decode().strip()
def publish(h,principal):
 opened=h.review.open(principal);assert opened['report']['reviewable'],opened['report']['losses'];a=h.review.approve(principal,opened['token'],opened['proposal_digest']);assert h.apply(principal,a,a['proposal_digest'])['state']=='committed'
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 source=fixture(out/'source');g=gateway(source);h=host(source,g);publish(h,'source')
 git(source,'init','-b','main');git(source,'add','--',*PATHS);git(source,'commit','-m','Shared native baseline');base=git(source,'rev-parse','HEAD')
 branches={}
 for name,branch in [('alice','c'*32),('bob','d'*32)]:
  root=out/name;review=review_fork(h,root,branch,name);apply_fork(h,review,review['review_digest'],name)
  git(root,'init','-b',name);git(root,'fetch',str(source),'main');git(root,'read-tree','FETCH_HEAD');git(root,'update-ref','refs/heads/'+name,base,'0'*40)
  branches[name]=(root,host(root,gateway(root)))
 for index,name in enumerate(['alice','bob']):
  root,current=branches[name];c=load_json(root/'game.cgs.json');c['modes'][0]['actors'][index]['components'][0]['defaults']['position']['x']=(101+index)*1000000;rehash(c);(root/'game.cgs.json').write_bytes(canonical(c));publish(current,name)
  git(root,'add','--',*PATHS);git(root,'commit','-m',name+' independently reviewed native edit')
 bob,bobhost=branches['bob'];checkpoint=git(bob,'rev-parse','HEAD');payload=capture_contribution(bobhost,'bob',checkpoint);(out/'bob-contribution.json').write_bytes(payload)
 alice,alicehost=branches['alice'];before=(alice/'game.cgs.json').read_bytes();preview=plan_contribution(alicehost,payload,sha(payload));(out/'preview.json').write_bytes(canonical(preview));assert preview['report']['reviewable'],preview['report']['losses']
 positions=[a['components'][0]['defaults']['position']['x'] for a in preview['report']['proposed_cgs']['modes'][0]['actors']];assert positions==[101000000,102000000],positions
 assert before==(alice/'game.cgs.json').read_bytes();assert git(alice,'merge-base','HEAD',base)==base and git(bob,'merge-base','HEAD',base)==base
 result=dict(ok=True,real_editor=True,independent_git_branches=True,common_ancestor=base,alice=git(alice,'rev-parse','HEAD'),bob=checkpoint,immutable_contribution=True,both_edits_in_review=True,preview_only=True,full_collaboration_certification=False)
 (out/'proof.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))
