import base64
import copy
import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from authoring_transaction import AuthoringCoordinator
from authoring_transaction_contract import TransactionRequest
from authoring_transaction_files import FileParticipant,sha,load_json
from authoring_apply import file_change,ACTIVATION,prepare_apply
from native_adoption import digest,encode


class Crash(BaseException):pass


def fixture(root,checkpoint=None,initialize=True,verify=True):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if initialize:
        for name,data in [('game.cgs.json',b'old-cgs'),('native.scene',b'old-native'),('baseline.json',b'old-baseline')]: (root/name).write_bytes(data)
    canonical=FileParticipant(root,name='canonical',allowed_paths=['game.cgs.json'])
    native=FileParticipant(root,name='native-fixture',allowed_paths=['native.scene'])
    baseline=FileParticipant(root,name='baseline',allowed_paths=['baseline.json'])
    request=TransactionRequest('txn1','a'*64,dict(canonical=dict(files=[file_change('game.cgs.json',sha(b'old-cgs'),b'new-cgs')]),native=dict(files=[file_change('native.scene',sha(b'old-native'),b'new-native')])),copy.deepcopy(ACTIVATION))
    coordinator=AuthoringCoordinator(root,dict(canonical=canonical,native=native),verify_pair=lambda m,t:verify and (root/'game.cgs.json').read_bytes()==b'new-cgs' and (root/'native.scene').read_bytes()==b'new-native',baseline_participant=baseline,baseline_request=lambda m,r:dict(files=[file_change('baseline.json',sha(b'old-baseline'),encode(dict(proposal=m['request']['proposal_digest'],receipts=r)))]),checkpoint=checkpoint)
    return coordinator,request


EVENTS=['intent_durable','prepared_before_receipt:canonical','prepared:canonical','prepared_before_receipt:native','prepared:native','decision_durable','published_before_receipt:canonical','published:canonical','published_before_receipt:native','published:native','pair_verified','baseline_prepared','baseline_published_before_receipt','complete_durable']


class CoordinatorTests(unittest.TestCase):
    def test_success_idempotence_and_activation_separation(self):
        with tempfile.TemporaryDirectory() as d:
            c,r=fixture(d);s=c.commit(r,authorize=lambda r:True);self.assertEqual(s['state'],'committed');self.assertFalse(s['activation']['performed'])
            self.assertEqual(c.commit(r,authorize=lambda r:False),s);self.assertFalse(c.status()['play_build_blocked'])

    def test_crash_at_every_durable_boundary_resume(self):
        for event in EVENTS:
            with self.subTest(event=event),tempfile.TemporaryDirectory() as d:
                def crash(name):
                    if name==event:raise Crash(name)
                c,r=fixture(d,crash)
                with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
                c,_=fixture(d,initialize=False);s=c.recover('txn1')
                expected='aborted' if EVENTS.index(event)<EVENTS.index('decision_durable') else 'committed'
                self.assertEqual(s['state'],expected)
                self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),b'old-cgs' if expected=='aborted' else b'new-cgs')
                self.assertEqual((Path(d)/'native.scene').read_bytes(),b'old-native' if expected=='aborted' else b'new-native')

    def test_real_process_death_and_restart(self):
        for event in ['decision_durable','published_before_receipt:canonical','baseline_published_before_receipt']:
            with self.subTest(event=event),tempfile.TemporaryDirectory() as d:
                fixture(d)
                child=subprocess.run([sys.executable,__file__,'--crash',d,event],capture_output=True)
                self.assertEqual(child.returncode,73,child.stderr)
                child=subprocess.run([sys.executable,__file__,'--recover',d],capture_output=True)
                self.assertEqual(child.returncode,0,child.stderr);self.assertIn(b'committed',child.stdout)

    def test_rollback_after_partial_publication(self):
        with tempfile.TemporaryDirectory() as d:
            def crash(name):
                if name=='published_before_receipt:canonical':raise Crash()
            c,r=fixture(d,crash)
            with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
            c,_=fixture(d,initialize=False);self.assertEqual(c.recover('txn1',action='rollback')['state'],'rolled_back')
            for name,data in [('game.cgs.json',b'old-cgs'),('native.scene',b'old-native'),('baseline.json',b'old-baseline')]:self.assertEqual((Path(d)/name).read_bytes(),data)

    def test_newer_edit_during_rollback_is_preserved_and_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            def crash(name):
                if name=='published:canonical':raise Crash()
            c,r=fixture(d,crash)
            with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
            (Path(d)/'game.cgs.json').write_bytes(b'newer-user-edit');c,_=fixture(d,initialize=False)
            with self.assertRaises(ValueError):c.recover('txn1',action='rollback')
            self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),b'newer-user-edit');self.assertTrue(c.status()['play_build_blocked'])
            self.assertEqual(load_json(Path(d)/'.xace/authoring-transactions/txn1/state.json')['state'],'recovery_conflict')

    def test_newer_baseline_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            def edit(name):
                if name=='pair_verified':(Path(d)/'baseline.json').write_bytes(b'user-baseline')
            c,r=fixture(d,edit)
            with self.assertRaisesRegex(ValueError,'baseline changed'):c.commit(r,authorize=lambda r:True)
            self.assertEqual((Path(d)/'baseline.json').read_bytes(),b'user-baseline');self.assertTrue(c.status()['play_build_blocked'])

    def test_pair_verification_failure_does_not_advance_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            c,r=fixture(d,verify=False)
            with self.assertRaisesRegex(ValueError,'pair'):c.commit(r,authorize=lambda r:True)
            self.assertEqual((Path(d)/'baseline.json').read_bytes(),b'old-baseline');self.assertTrue(c.status()['play_build_blocked'])

    def test_authorization_rechecked_after_staging(self):
        with tempfile.TemporaryDirectory() as d:
            c,r=fixture(d);calls=[]
            def approve(r):calls.append(1);return len(calls)==1
            with self.assertRaisesRegex(ValueError,'approval/source'):c.commit(r,authorize=approve)
            self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),b'old-cgs');self.assertEqual(c.recover('txn1')['state'],'aborted')

    def test_disk_full_and_permission_failure_injected(self):
        import authoring_transaction_files as files
        for error in [OSError(errno.ENOSPC,'disk full'),PermissionError(errno.EACCES,'access denied')]:
            with tempfile.TemporaryDirectory() as d:
                c,r=fixture(d);original=files.durable;failed=[]
                def fail(path,data):
                    if str(path).endswith('.after') and not failed:failed.append(True);raise error
                    return original(path,data)
                with patch.object(files,'durable',side_effect=fail),self.assertRaises(OSError):c.commit(r,authorize=lambda r:True)
                self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),b'old-cgs');self.assertFalse(c.status()['play_build_blocked'])

    @unittest.skipUnless(os.name=='nt','Windows sharing/readonly profile')
    def test_real_readonly_target_refuses_publication(self):
        with tempfile.TemporaryDirectory() as d:
            c,r=fixture(d);path=Path(d)/'game.cgs.json';path.chmod(stat.S_IREAD)
            try:
                with self.assertRaises(OSError):c.commit(r,authorize=lambda r:True)
                self.assertEqual(path.read_bytes(),b'old-cgs');self.assertTrue(c.status()['play_build_blocked'])
            finally:path.chmod(stat.S_IWRITE|stat.S_IREAD)
            c,_=fixture(d,initialize=False);self.assertEqual(c.recover('txn1')['state'],'committed')

    def test_corrupt_stage_and_manifest_block_recovery(self):
        for name in ['canonical/0.after','manifest.json']:
            with tempfile.TemporaryDirectory() as d:
                def crash(event):
                    if event=='decision_durable':raise Crash()
                c,r=fixture(d,crash)
                with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
                (Path(d)/'.xace/authoring-transactions/txn1'/name).write_bytes(b'corrupt')
                c,_=fixture(d,initialize=False)
                with self.assertRaises(ValueError):c.recover('txn1')
                self.assertTrue(c.status()['play_build_blocked'])

    def test_pending_recovery_blocks_other_transactions(self):
        with tempfile.TemporaryDirectory() as d:
            def crash(event):
                if event=='decision_durable':raise Crash()
            c,r=fixture(d,crash)
            with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
            c,_=fixture(d,initialize=False);other=TransactionRequest('txn2',r.proposal_digest,r.participant_requests,r.activation_record)
            with self.assertRaisesRegex(ValueError,'pending recovery'):c.commit(other,authorize=lambda r:True)

    def test_path_escape_and_reused_id_refused(self):
        with tempfile.TemporaryDirectory() as d:
            c,r=fixture(d)
            bad=copy.deepcopy(r);bad.participant_requests['canonical']['files'][0]['path']='../escape'
            with self.assertRaises(ValueError):c.commit(bad,authorize=lambda r:True)
            with self.assertRaises(ValueError):c.commit(r,authorize=lambda r:True)

    def test_gde_apply_prepares_versioned_copy(self):
        from test_native_reconciliation import context,engine_edit
        from native_reconciliation_plan import plan_reconciliation
        from test_native_adoption import inputs,plan
        for kind in ['reconcile','adopt']:
            with tempfile.TemporaryDirectory() as d:
                if kind=='reconcile':c=context();engine_edit(c);proposal=plan_reconciliation(**c)
                else:
                    data,mapping,cgs,selected,choices=inputs();proposal=plan(data,mapping,cgs,selected,choices)
                    c=dict(native_inventory=data,mapping=mapping,current_cgs=cgs,selection=selected,choices=choices,expected_source_digest=sha(data),expected_cgs_digest=digest(cgs),trusted_project=True)
                current=c['current_cgs'];(Path(d)/'game.cgs.json').write_bytes(encode(current));before=encode(current)
                prepared=prepare_apply(proposal,context=c,transaction_id='txn1',project_root=Path(d))
                old=current['metadata']['version'].split('.');old[-1]=str(int(old[-1])+1)
                self.assertEqual(prepared['cgs']['cgs']['metadata']['version'],'.'.join(old));self.assertEqual(encode(current),before)
                self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),before)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--crash':
        def die(event):
            if event==sys.argv[3]:os._exit(73)
        c,r=fixture(sys.argv[2],die,initialize=False);c.commit(r,authorize=lambda r:True)
    elif len(sys.argv)>1 and sys.argv[1]=='--recover':
        c,_=fixture(sys.argv[2],initialize=False);print(json.dumps(c.recover('txn1')))
    else:unittest.main()
