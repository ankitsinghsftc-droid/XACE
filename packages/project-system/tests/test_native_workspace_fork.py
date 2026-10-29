"""Fork approval and preservation refusals; native success has separate editor proof."""
import copy,sys,uuid,unittest
from pathlib import Path
from contextlib import nullcontext,contextmanager
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_native_reconciliation import context
from native_workspace_fork import review_fork,apply_fork,destination_path,_unchanged
from authoring_transaction_files import sha

@contextmanager
def scratch():
 path=ROOT/'evidence/nec017/unit-tests'/uuid.uuid4().hex;path.mkdir(parents=True)
 yield str(path) # Persistent test fixtures; no automatic cleanup.

class WorkspaceForkTests(unittest.TestCase):
 def fixture(self,root):
  source=root/'source';source.mkdir();(source/'.xace').mkdir();(source/'game.cgs.json').write_bytes(b'cgs');(source/'.xace/history.json').write_bytes(b'old')
  c=context();mapping=c['mapping'];rows={};files={'game.cgs.json':sha(b'cgs')};history={'history.json':sha(b'old')}
  host=SimpleNamespace(root=source,gateway=SimpleNamespace(identity={'engine':'godot'}),publication_gate=lambda:nullcontext())
  return host,(mapping,c['current_cgs'],rows,files,history)
 def test_review_preserves_namespace_objects_and_original_baseline(self):
  with scratch() as d:
   root=Path(d);h,data=self.fixture(root);before=copy.deepcopy(data[0].to_dict())
   with patch('native_workspace_fork._source',return_value=data):r=review_fork(h,root/'alice','c'*32,'alice')
   self.assertEqual(data[0].to_dict(),before);self.assertEqual(r['target_mapping']['namespace_id'],before['namespace_id']);self.assertEqual(r['target_mapping']['objects'],before['objects']);self.assertIsNone(r['target_mapping']['baseline']);self.assertFalse((root/'alice').exists())
 def test_wrong_principal_or_changed_review_refuses_before_writing(self):
  with scratch() as d:
   root=Path(d);h,data=self.fixture(root)
   with patch('native_workspace_fork._source',return_value=data):r=review_fork(h,root/'alice','c'*32,'alice')
   with self.assertRaises(ValueError):apply_fork(h,r,r['review_digest'],'bob')
   altered=copy.deepcopy(r);altered['destination']=str(root/'other')
   with self.assertRaises(ValueError):apply_fork(h,altered,r['review_digest'],'alice')
   self.assertFalse((root/'alice').exists());self.assertFalse((root/'other').exists())
 def test_stale_source_and_ancestor_refuse_before_destination_creation(self):
  for changed in ['source','history']:
   with self.subTest(changed=changed),scratch() as d:
    root=Path(d);h,data=self.fixture(root)
    with patch('native_workspace_fork._source',return_value=data):
     r=review_fork(h,root/'alice','c'*32,'alice')
     p=h.root/('game.cgs.json' if changed=='source' else '.xace/history.json');p.write_bytes(b'newer work')
     with self.assertRaises(ValueError):apply_fork(h,r,r['review_digest'],'alice')
    self.assertEqual(p.read_bytes(),b'newer work');self.assertFalse((root/'alice').exists())
 def test_existing_nested_disposable_and_same_branch_refused(self):
  with scratch() as d:
   root=Path(d);h,data=self.fixture(root);(root/'existing').mkdir()
   for target in [root/'existing',h.root/'nested',root/'target'/'fork',root/'build'/'fork']:
    with self.assertRaises(ValueError):destination_path(target,h.root)
   with patch('native_workspace_fork._source',return_value=data),self.assertRaises(ValueError):review_fork(h,root/'alice',data[0].branch_id,'alice')
 def test_pending_recovery_blocks_review(self):
  with scratch() as d:
   root=Path(d);h,data=self.fixture(root)
   def blocked():raise ValueError('pending recovery blocks authoring publication')
   h.publication_gate=blocked
   with self.assertRaisesRegex(ValueError,'pending recovery'):review_fork(h,root/'alice','c'*32,'alice')
   self.assertFalse((root/'alice').exists())
if __name__=='__main__':unittest.main()
