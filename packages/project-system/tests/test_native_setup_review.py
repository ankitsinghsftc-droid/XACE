import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from authoring_identity import canonical,IdentityMap
from authoring_saved_pair import MAP,verify_baseline_receipts
from native_setup_plan import NativeSetupPlan
from native_setup_review import NativeSetupReview
from native_materialization import NativeMaterializationHost

class Gateway:
    def __init__(self,root):self.root=root;self.identity=dict(engine='godot',profile='setup-filesystem-test',root=str(root));self.fail=False
    def capture(self):
        if self.fail:raise ValueError('injected native reopen failure')
        return (self.root/'native.json').read_bytes()

def fixture(root):
    evidence=ROOT/'docs/evidence/nec010-native-generators-20261018'
    cgs=json.loads((evidence/'godot-source.cgs.json').read_text());(root/'game.cgs.json').write_bytes(canonical(cgs))
    plan=NativeSetupPlan((evidence/'godot-setup-plan.json').read_bytes())
    native=canonical(json.loads((evidence/'godot-create.json').read_text())['result']['inventory'])
    stage=dict(plan=plan,native_inventory=native,files={'native.json':native})
    gateway=Gateway(root);host=NativeMaterializationHost(root,lambda:None,gateway)
    return host,NativeSetupReview(host,lambda _:copy.deepcopy(stage)),stage

class SetupReviewTests(unittest.TestCase):
    def approve(self,review):
        opened=review.open('operator');approved=review.approve('operator',opened['token'],opened['proposal_digest']);return opened,approved
    def apply(self,review,approved):return review.apply('operator',approved['token'],approved['proposal_digest'],approved['approval'])
    def test_review_separate_apply_and_handoff_to_normal_host(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,review,stage=fixture(root);opened,approved=self.approve(review)
            self.assertFalse((root/'native.json').exists());self.assertEqual(opened['report']['files'][0]['operation'],'create')
            self.assertEqual(self.apply(review,approved)['state'],'committed')
            self.assertFalse(host.status()['play_build_blocked'])
            mapping=IdentityMap.from_dict(json.loads((root/MAP).read_text()));self.assertTrue(verify_baseline_receipts(root,mapping.baseline))
            with self.assertRaises(ValueError):self.apply(review,approved)
    def test_fresh_host_recovers_failed_reopen_without_review_memory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,review,_=fixture(root);_,approved=self.approve(review);host.gateway.fail=True
            with self.assertRaises(ValueError):self.apply(review,approved)
            self.assertFalse((root/MAP).exists());pending=host.status()['pending'];self.assertEqual(len(pending),1)
            restarted=NativeMaterializationHost(root,lambda:None,Gateway(root));result=restarted.recover(pending[0]['transaction_id'])
            self.assertEqual(result['state'],'committed');self.assertFalse(restarted.status()['play_build_blocked'])
    def test_foreign_operator_or_missing_approval_cannot_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,review,_=fixture(root);opened=review.open('operator')
            with self.assertRaises(ValueError):review.apply('operator',opened['token'],opened['proposal_digest'],'wrong')
            approved=review.approve('operator',opened['token'],opened['proposal_digest'])
            with self.assertRaises(ValueError):review.apply('other',approved['token'],approved['proposal_digest'],approved['approval'])
            self.assertFalse((root/'native.json').exists())
    def test_changed_stage_invalidates_approval(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,review,stage=fixture(root);_,approved=self.approve(review);stage['files']['extra.txt']=b'new code'
            with self.assertRaisesRegex(ValueError,'changed'):self.apply(review,approved)
            self.assertFalse((root/'native.json').exists())
    def test_newer_published_content_is_retained_during_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,review,_=fixture(root);_,approved=self.approve(review);host.gateway.fail=True
            with self.assertRaises(ValueError):self.apply(review,approved)
            tx=host.status()['pending'][0]['transaction_id'];(root/'native.json').write_bytes(b'creator edit')
            with self.assertRaises(ValueError):host.recover(tx,action='rollback')
            self.assertEqual((root/'native.json').read_bytes(),b'creator edit');self.assertTrue(host.status()['play_build_blocked'])
    def test_unknown_historical_participant_still_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,review,_=fixture(root);_,approved=self.approve(review);result=self.apply(review,approved)
            journal=root/'.xace/authoring-transactions'/result['transaction_id'];manifest=json.loads((journal/'manifest.json').read_text())
            manifest['participants']['native']['schema']='unregistered';(journal/'manifest.json').write_bytes(canonical(manifest))
            self.assertTrue(host.status()['play_build_blocked'])
if __name__=='__main__':unittest.main()
