"""Branch publication must require exact explicit approval before writes."""
import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from native_branch_merge import apply_branch_merge
from authoring_identity import digest
from authoring_transaction_files import sha

class MergeApprovalTests(unittest.TestCase):
 def review(self,**changes):
  value=dict(principal='alice',contribution_sha256=sha(b'payload'),resolutions=None,report=dict(reviewable=True,noop=False));value.update(changes);value['review_digest']=digest(value);return value
 def test_wrong_principal_or_modified_approval_never_prepares(self):
  review=self.review()
  with patch('native_branch_merge._prepare') as prepare:
   with self.assertRaises(ValueError):apply_branch_merge(None,b'payload',review,'bob',review['review_digest'])
   altered=copy.deepcopy(review);altered['resolutions']={'conflict':'engine'}
   with self.assertRaises(ValueError):apply_branch_merge(None,b'payload',altered,'alice',review['review_digest'])
   prepare.assert_not_called()
 def test_changed_contribution_never_prepares(self):
  review=self.review()
  with patch('native_branch_merge._prepare') as prepare,self.assertRaises(ValueError):apply_branch_merge(None,b'other',review,'alice',review['review_digest'])
  prepare.assert_not_called()
 def test_receiver_drift_never_prepares(self):
  review=self.review()
  with patch('native_branch_merge.review_branch_merge',return_value={'changed':True}),patch('native_branch_merge._prepare') as prepare:
   with self.assertRaisesRegex(ValueError,'stale'):apply_branch_merge(None,b'payload',review,'alice',review['review_digest'])
   prepare.assert_not_called()
 def test_unresolved_conflict_never_prepares(self):
  review=self.review(report=dict(reviewable=False,noop=False))
  with patch('native_branch_merge.review_branch_merge',return_value=review),patch('native_branch_merge._prepare') as prepare:
   with self.assertRaisesRegex(ValueError,'unresolved'):apply_branch_merge(None,b'payload',review,'alice',review['review_digest'])
   prepare.assert_not_called()
 def test_noop_does_not_advance_baseline_or_activate_runtime(self):
  review=self.review(report=dict(reviewable=True,noop=True))
  with patch('native_branch_merge.review_branch_merge',return_value=review),patch('native_branch_merge._prepare') as prepare:
   result=apply_branch_merge(None,b'payload',review,'alice',review['review_digest']);self.assertEqual(result,dict(state='noop',files_written=False,runtime_activation=False));prepare.assert_not_called()
if __name__=='__main__':unittest.main()
