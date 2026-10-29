"""Contribution integrity and real Git provenance, independent of native proof."""
import copy,json,sys,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_reconciliation import context
from test_native_workspace_fork import scratch
from native_branch_contribution import decode_contribution,verify_git_checkpoint,SCHEMA
from authoring_transaction_files import sha
from authoring_identity import canonical

def contribution():
 c=context();mapping=copy.deepcopy(c['mapping']);mapping.branch_id='d'*32
 return dict(schema=SCHEMA,profile='native.sibling_transform_merge.v1',principal='bob',checkpoint='a'*40,engine=mapping.engine,project_id=mapping.project_id,namespace_id=mapping.namespace_id,branch_id=mapping.branch_id,mapping=mapping.to_dict(),cgs=copy.deepcopy(c['current_cgs']),rows=c['baseline'].to_dict()['inspection']['normalized'],files={},ancestor=dict(mapping=c['mapping'].to_dict(),cgs=copy.deepcopy(c['baseline_cgs']),snapshot=json.loads(c['baseline'].payload)))

class ContributionTests(unittest.TestCase):
 def test_valid_and_payload_identity(self):
  value=contribution();data=canonical(value);self.assertEqual(decode_contribution(data,sha(data)),value)
  with self.assertRaises(ValueError):decode_contribution(data,'0'*64)
 def test_rows_cannot_hide_different_canonical_transform(self):
  value=contribution();key=next(k for k,r in value['rows'].items() if 'transform.position' in r['fields']);value['rows'][key]['fields']['transform.position']['x']='999000000';data=canonical(value)
  with self.assertRaisesRegex(ValueError,'projection'):decode_contribution(data,sha(data))
 def test_foreign_identity_and_duplicate_keys(self):
  value=contribution();value['namespace_id']='e'*32;data=canonical(value)
  with self.assertRaises(ValueError):decode_contribution(data,sha(data))
  data=b'{"schema":"forged",'+canonical(contribution())[1:]
  with self.assertRaisesRegex(ValueError,'duplicate'):decode_contribution(data,sha(data))
 def test_non_transform_work_is_not_silently_omitted(self):
  from tools.world_extensibility_proof import rehash
  value=contribution();value['cgs']['metadata']['name']='Unmerged game work';rehash(value['cgs']);data=canonical(value)
  with self.assertRaisesRegex(ValueError,'non-transform'):decode_contribution(data,sha(data))
 def test_git_blob_not_just_claimed_commit(self):
  with scratch() as d:
   root=Path(d);path=root/'source.txt';path.write_bytes(b'checked in')
   def git(*args):
    result=subprocess.run(['git','-c','gc.auto=0','-c','user.name=NEC017 fixture','-c','user.email=nec017@example.invalid','-C',str(root),*args],capture_output=True,check=True);return result.stdout.decode().strip()
   git('init','-b','main');git('add','source.txt');git('commit','-m','Baseline');commit=git('rev-parse','HEAD');verify_git_checkpoint(root,commit,{'source.txt':sha(path.read_bytes())})
   path.write_bytes(b'uncommitted work')
   with self.assertRaisesRegex(ValueError,'uncommitted'):verify_git_checkpoint(root,commit,{'source.txt':sha(path.read_bytes())})
   (root/'untracked.txt').write_bytes(b'new')
   with self.assertRaisesRegex(ValueError,'not checkpointed'):verify_git_checkpoint(root,commit,{'untracked.txt':sha(b'new')})
if __name__=='__main__':unittest.main()
