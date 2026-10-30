"""Independent native developer branches and immutable Git-pinned merge preview."""
from pathlib import Path
import sys,json,subprocess,copy,os
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec017_unity_crash import fixture,gateway,host
from native_workspace_fork import review_fork,apply_fork
from native_branch_contribution import capture_contribution,plan_contribution
from native_branch_merge import review_branch_merge,apply_branch_merge
from authoring_transaction_files import load_json,sha
from authoring_identity import canonical
from tools.world_extensibility_proof import rehash

PATHS=['game.cgs.json', 'Assets', 'Packages', 'ProjectSettings']
def git(root,*args):
 p=subprocess.run(['git','-c','gc.auto=0','-c','user.name=NEC017 local fixture','-c','user.email=nec017@example.invalid','-C',str(root),*args],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
 assert p.returncode==0,(args,p.stderr.decode(errors='replace'));return p.stdout.decode().strip()
def publish(h,principal):
 opened=h.review.open(principal);assert opened['report']['reviewable'],opened['report']['losses'];a=h.review.approve(principal,opened['token'],opened['proposal_digest']);assert h.apply(principal,a,a['proposal_digest'])['state']=='committed'
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();out.mkdir(parents=True)
 source=fixture(out/'source');g=gateway(source);h=host(source,g);publish(h,'source')
 (source/'.gitattributes').write_bytes(b'* -text\n');git(source,'init','-b','main');git(source,'add','--',*PATHS,'.gitattributes');git(source,'commit','-m','Shared native baseline');base=git(source,'rev-parse','HEAD')
 branches={}
 for name,branch in [('alice','c'*32),('bob','d'*32)]:
  root=out/name;review=review_fork(h,root,branch,name);apply_fork(h,review,review['review_digest'],name)
  (root/'.gitattributes').write_bytes((source/'.gitattributes').read_bytes());git(root,'init','-b',name);git(root,'fetch',str(source),'main');git(root,'read-tree','FETCH_HEAD');git(root,'update-ref','refs/heads/'+name,base,'0'*40)
  branches[name]=(root,host(root,gateway(root)))
 for index,name in enumerate(['alice','bob']):
  root,current=branches[name];c=load_json(root/'game.cgs.json');c['modes'][0]['actors'][index]['components'][0]['defaults']['position']['x']=(101+index)*1000000;rehash(c);(root/'game.cgs.json').write_bytes(canonical(c));publish(current,name)
  git(root,'add','--',*PATHS);git(root,'commit','-m',name+' independently reviewed native edit')
 bob,bobhost=branches['bob'];checkpoint=git(bob,'rev-parse','HEAD');payload=capture_contribution(bobhost,'bob',checkpoint);(out/'bob-contribution.json').write_bytes(payload)
 alice,alicehost=branches['alice'];before=(alice/'game.cgs.json').read_bytes();preview=plan_contribution(alicehost,payload,sha(payload));(out/'preview.json').write_bytes(canonical(preview));assert preview['report']['reviewable'],preview['report']['losses']
 positions=[a['components'][0]['defaults']['position']['x'] for a in preview['report']['proposed_cgs']['modes'][0]['actors']];assert positions==[101000000,102000000],positions
 assert before==(alice/'game.cgs.json').read_bytes();assert git(alice,'merge-base','HEAD',base)==base and git(bob,'merge-base','HEAD',base)==base
 def record_merge(root,bobroot,right,expected_left):
  git(root,'fetch',str(bobroot),'bob');assert git(root,'rev-parse','FETCH_HEAD')==right
  git(root,'add','--',*PATHS);tree=git(root,'write-tree');merged=git(root,'commit-tree',tree,'-p',expected_left,'-p',right,'-m','Explicit reviewed native semantic merge')
  git(root,'update-ref','refs/heads/alice',merged,expected_left);assert git(root,'rev-list','--parents','-n','1','HEAD').split()==[merged,expected_left,right]
  return merged
 left=git(alice,'rev-parse','HEAD');review=review_branch_merge(alicehost,payload,'alice');result=apply_branch_merge(alicehost,payload,review,'alice',review['review_digest']);assert result['state']=='committed'
 first=record_merge(alice,bob,checkpoint,left)
 # Conflicting same-actor edit remains in Bob's independent branch.
 c=load_json(bob/'game.cgs.json');c['modes'][0]['actors'][0]['components'][0]['defaults']['position']['x']=202000000;rehash(c);(bob/'game.cgs.json').write_bytes(canonical(c));publish(bobhost,'bob')
 git(bob,'add','--',*PATHS);git(bob,'commit','-m','Bob conflicting independent edit');right=git(bob,'rev-parse','HEAD');conflicting=capture_contribution(bobhost,'bob',right)
 blocked=review_branch_merge(alicehost,conflicting,'alice');assert not blocked['report']['reviewable'];before=(alice/'game.cgs.json').read_bytes()
 try:apply_branch_merge(alicehost,conflicting,blocked,'alice',blocked['review_digest'])
 except ValueError:pass
 else:raise AssertionError('unresolved merge published')
 assert before==(alice/'game.cgs.json').read_bytes()
 choices={item['id']:'engine' for item in blocked['report']['merge']['conflicts']};assert choices
 approved=review_branch_merge(alicehost,conflicting,'alice',resolutions=choices);assert approved['report']['reviewable']
 (out/'conflicting-contribution.json').write_bytes(conflicting);(out/'approved-conflict.json').write_bytes(canonical(approved));(out/'blocked-review.json').write_bytes(canonical(blocked))
 with (out/'crash-child.log').open('wb') as log:child=subprocess.run([sys.executable,'-B',__file__,'--crash',str(out)],stdout=log,stderr=subprocess.STDOUT,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW)
 assert child.returncode==73,child.returncode
 reopened=host(alice,gateway(alice));tid='merge-'+approved['review_digest'][:32];assert reopened.status()['play_build_blocked'];state=reopened.recover(tid);assert state['state']=='committed' and reopened.recover(tid)==state and not reopened.status()['play_build_blocked']
 second=record_merge(alice,bob,right,first);assert git(bob,'rev-parse','HEAD')==right
 final=load_json(alice/'game.cgs.json');assert [a['components'][0]['defaults']['position']['x'] for a in final['modes'][0]['actors']]==[202000000,102000000]
 assert reopened.review.open('alice')['report']['noop']
 result=dict(ok=True,real_editor=True,independent_git_branches=True,common_ancestor=base,alice=second,bob=right,first_merge=first,immutable_contribution=True,both_edits_merged=True,conflict_refused_until_explicit_choice=True,process_death_after_native_publication=73,idempotent_recovery=True,contributor_unchanged=True,reopened_noop=True,scope='Two independent local developer principals and Git branches; not an external-human usability certification',full_nec017_certification=False)
 (out/'proof.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)

def crash(out):
 root=out/'alice';h=host(root,gateway(root));original=h._coordinator
 def coordinator(*args,**kwargs):
  c=original(*args,**kwargs)
  def checkpoint(event):
   if event=='published_before_receipt:native':os._exit(73)
  c.checkpoint=checkpoint;return c
 h._coordinator=coordinator;payload=(out/'conflicting-contribution.json').read_bytes();review=load_json(out/'approved-conflict.json');apply_branch_merge(h,payload,review,'alice',review['review_digest']);raise AssertionError('crash boundary not reached')

if __name__=='__main__':
 if sys.argv[1]=='--crash':crash(Path(sys.argv[2]))
 else:main(Path(sys.argv[1]))
