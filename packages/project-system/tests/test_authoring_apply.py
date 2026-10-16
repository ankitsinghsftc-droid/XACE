"""Coordinator integration; native gateway below is an explicitly labelled fixture."""
import copy
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system'),str(Path(__file__).parent)]
from test_authoring_transaction import fixture,Crash
from test_native_reconciliation import context,engine_edit
from native_reconciliation_plan import plan_reconciliation
from native_adoption import digest,encode
from authoring_apply import prepare_apply,apply_prepared,file_change
from authoring_transaction import AuthoringCoordinator
from authoring_transaction_files import FileParticipant,sha,load_json
from authoring_native_participant import NativeParticipant
from authoring_saved_pair import SavedPair,verify_baseline_receipts,MAP,CGS,NATIVE
from authoring_identity import IdentityMap


class FixtureGateway:
    """Real filesystem, fixture inventory; not an installed-editor certification."""
    def __init__(self,root,engine='unity'):
        self.root=Path(root);self.identity=dict(engine=engine,profile='test-fixture-v1',root=str(self.root))
        self.files=FileParticipant(root,name='fixture-native',allowed_paths=['native.json'])
    def prepare(self,transaction_id,request):
        directory=self.root/'.fixture-stages'/transaction_id
        before=(self.root/'native.json').read_bytes()
        token=self.files.prepare(transaction_id,dict(files=[file_change('native.json',sha(before),before)]),directory)
        row=dict(state='prepared',token=token)
        return dict(directory=str(directory),approval_digest=digest(row),receipt=row)
    def inspect(self,prepared):
        observed=self.files.inspect(prepared['receipt']['token'],Path(prepared['directory']))
        # A no-write native observation has equal before/after bytes. The gateway
        # durably tracks whether commit acknowledged the independently recaptured source.
        if observed=='after':return 'after' if (Path(prepared['directory'])/'ack').exists() else 'before'
        return observed
    def commit(self,prepared):
        self.files.publish(prepared['receipt']['token'],Path(prepared['directory']))
        (Path(prepared['directory'])/'ack').write_text('verified')
    def recover(self,prepared):
        self.files.restore(prepared['receipt']['token'],Path(prepared['directory']))
        (Path(prepared['directory'])/'ack').unlink(missing_ok=True)


def setup(root,engine='unity',kind='reconcile'):
    root=Path(root)
    if kind=='reconcile':
        ctx=context(engine);engine_edit(ctx);proposal=plan_reconciliation(**ctx)
    else:
        from test_native_adoption import inputs,plan
        data,mapping,cgs,selected,choices=inputs(engine)
        ctx=dict(native_inventory=data,mapping=mapping,current_cgs=cgs,selection=selected,choices=choices,
                 expected_source_digest=sha(data),expected_cgs_digest=digest(cgs),trusted_project=True)
        proposal=plan(data,mapping,cgs,selected,choices)
    (root/'game.cgs.json').write_bytes(encode(ctx['current_cgs']))
    (root/'native.json').write_bytes(ctx['native_inventory'])
    def fresh():return prepare_apply(proposal,context=ctx,transaction_id='apply1',project_root=root)
    prepared=fresh();mapping=IdentityMap.from_dict(prepared['target_mapping'])
    pair=SavedPair(root,mapping=mapping,expected_cgs=prepared['cgs']['cgs'],expected_normalized=prepared['expected_normalized'],recapture=lambda:(root/'native.json').read_bytes())
    coordinator=AuthoringCoordinator(root,dict(canonical=FileParticipant(root,name='canonical',allowed_paths=['game.cgs.json']),native=NativeParticipant(FixtureGateway(root,engine))),verify_pair=pair.verify,baseline_participant=pair.participant,baseline_request=pair.baseline_request)
    return coordinator,prepared,fresh,pair


class ApplyTests(unittest.TestCase):
    def test_real_gde_apply_baseline_and_reconciliation_receipt_all_profiles(self):
        for engine in ['unity','godot','unreal']:
            for kind in ['adopt','reconcile']:
                with self.subTest(engine=engine,kind=kind),tempfile.TemporaryDirectory() as d:
                    c,p,fresh,pair=setup(d,engine,kind)
                    result=apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request=None),authorize=lambda r:True,refresh_preparation=fresh)
                    self.assertEqual(result['state'],'committed');self.assertFalse(result['activation']['performed'])
                    mapping=IdentityMap.from_dict(load_json(Path(d)/MAP))
                    self.assertTrue(verify_baseline_receipts(d,mapping.baseline))
                    self.assertFalse(c.require_ready()['play_build_blocked'])
                    self.assertEqual(mapping.mapping_digest(),pair.mapping.mapping_digest())
                    self.assertEqual(load_json(Path(d)/CGS),p['cgs']['cgs'])
                    self.assertEqual(mapping.baseline.native_snapshot_digest,sha((Path(d)/NATIVE).read_bytes()))
                    # Saved baseline is a historical ancestor, not the current CGS.
                    (Path(d)/'game.cgs.json').write_bytes(b'independent later work')
                    self.assertTrue(verify_baseline_receipts(d,mapping.baseline))
                    with self.assertRaises(ValueError):c.recover('apply1')

    def test_fresh_review_check_cannot_be_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            c,p,fresh,_=setup(d);old=(Path(d)/'game.cgs.json').read_bytes()
            changed=copy.deepcopy(p);changed['source_digest']='c'*64
            with self.assertRaisesRegex(ValueError,'regenerate review'):
                apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request=None),authorize=lambda r:True,refresh_preparation=lambda:changed)
            self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),old)
            self.assertFalse(c.journal.exists())

    def test_native_request_must_equal_review(self):
        with tempfile.TemporaryDirectory() as d:
            c,p,fresh,_=setup(d)
            with self.assertRaisesRegex(ValueError,'differs from reviewed'):
                apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request={'unexpected':True}),authorize=lambda r:True,refresh_preparation=fresh)

    def test_fresh_pair_rejects_native_drift_and_preserves_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            c,p,fresh,_=setup(d)
            def drift(event):
                if event=='published:native':(Path(d)/'native.json').write_bytes(b'newer edit')
            c.checkpoint=drift
            with self.assertRaises(ValueError):
                apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request=None),authorize=lambda r:True,refresh_preparation=fresh)
            self.assertFalse((Path(d)/MAP).exists());self.assertEqual((Path(d)/'native.json').read_bytes(),b'newer edit')
            with self.assertRaisesRegex(ValueError,'blocks Play/build'):c.require_ready()

    def test_native_gateway_rejects_bad_prepared_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'native.json').write_bytes(b'old');gateway=FixtureGateway(root);participant=NativeParticipant(gateway)
            with patch.object(gateway,'prepare',return_value=dict(directory=d,approval_digest='a'*64,receipt={'state':'prepared'})):
                with self.assertRaisesRegex(ValueError,'approval mismatch'):participant.prepare('t',{},root/'stage')

    def test_postdecision_journal_disk_full_recovers_without_receipt(self):
        import authoring_transaction as module
        with tempfile.TemporaryDirectory() as d:
            c,r=fixture(d);original=module.atomic_json;failed=[]
            def fail(path,data):
                if data.get('receipts',{}).get('canonical') and not failed:
                    failed.append(True);raise OSError(errno.ENOSPC,'disk full after canonical publication')
                return original(path,data)
            with patch.object(module,'atomic_json',side_effect=fail),self.assertRaises(OSError):c.commit(r,authorize=lambda r:True)
            self.assertTrue(c.status()['play_build_blocked'])
            c,_=fixture(d,initialize=False);self.assertEqual(c.recover('txn1')['state'],'committed')

    def test_rollback_restart_at_each_boundary(self):
        for stop in ['rollback_decision','baseline_restored','restored:native','restored:canonical','rollback_complete']:
            with self.subTest(stop=stop),tempfile.TemporaryDirectory() as d:
                def crash(event):
                    if event=='baseline_published_before_receipt':raise Crash()
                c,r=fixture(d,crash)
                with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
                def rollback_crash(event):
                    if event==stop:raise Crash()
                c,_=fixture(d,rollback_crash,initialize=False)
                with self.assertRaises(Crash):c.recover('txn1',action='rollback')
                c,_=fixture(d,initialize=False)
                self.assertEqual(c.recover('txn1',action='rollback')['state'],'rolled_back')
                self.assertEqual((Path(d)/'game.cgs.json').read_bytes(),b'old-cgs')
                self.assertEqual((Path(d)/'native.scene').read_bytes(),b'old-native')
                self.assertEqual((Path(d)/'baseline.json').read_bytes(),b'old-baseline')

    def test_created_file_rollback_retains_bytes_and_detects_race(self):
        import authoring_transaction_files as module
        for race in [False,True]:
            with self.subTest(race=race),tempfile.TemporaryDirectory() as d:
                root=Path(d);p=FileParticipant(root,name='new',allowed_paths=['new.json']);stage=root/'stage'
                token=p.prepare('t',dict(files=[file_change('new.json',None,b'owned')]),stage);p.publish(token,stage)
                original=os.rename
                def rename(src,dst):
                    Path(src).write_bytes(b'newer');return original(src,dst)
                if race:
                    with patch.object(module.os,'rename',side_effect=rename),self.assertRaises(ValueError):p.restore(token,stage)
                    self.assertEqual(p.inspect(token,stage),'conflict')
                    self.assertEqual((stage/'0.created-rollback').read_bytes(),b'newer')
                else:
                    p.restore(token,stage);self.assertEqual(p.inspect(token,stage),'before')
                    self.assertEqual((stage/'0.created-rollback').read_bytes(),b'owned')

    def test_file_partial_publication_and_rollback(self):
        import authoring_transaction_files as module
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'a').write_bytes(b'a');(root/'b').write_bytes(b'b')
            p=FileParticipant(root,name='multi',allowed_paths=['a','b']);stage=root/'stage'
            token=p.prepare('t',dict(files=[file_change(k,sha(k.encode()),b'changed') for k in ['a','b']]),stage)
            original=module.replace_owned
            def fail(path,*args):
                if path.name=='b':raise PermissionError('second document denied')
                return original(path,*args)
            with patch.object(module,'replace_owned',side_effect=fail),self.assertRaises(PermissionError):p.publish(token,stage)
            self.assertEqual(p.inspect(token,stage),'partial');p.restore(token,stage)
            self.assertEqual(p.inspect(token,stage),'before')

    def test_windows_replace_retains_actual_racing_image(self):
        import authoring_transaction_files as module
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'document';path.write_bytes(b'old')
            p=FileParticipant(root,name='race',allowed_paths=['document']);stage=root/'stage'
            token=p.prepare('t',dict(files=[file_change('document',sha(b'old'),b'owned')]),stage)
            original=module.durable
            def race(target,data):
                original(target,data)
                if target.name.endswith('.publish'):path.write_bytes(b'newer independent work')
            with patch.object(module,'durable',side_effect=race),self.assertRaisesRegex(ValueError,'concurrent replacement'):
                p.publish(token,stage)
            self.assertEqual((stage/'0.displaced').read_bytes(),b'newer independent work')
            self.assertEqual(p.inspect(token,stage),'conflict')
            with self.assertRaises(ValueError):p.restore(token,stage)

    def test_native_conflict_never_invokes_publication_or_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'native.json').write_bytes(b'old');gateway=FixtureGateway(root);p=NativeParticipant(gateway)
            token=p.prepare('t',{},root/'stage');(root/'native.json').write_bytes(b'user edit')
            with patch.object(gateway,'commit') as commit,patch.object(gateway,'recover') as recover:
                with self.assertRaises(ValueError):p.publish(token,root/'stage')
                with self.assertRaises(ValueError):p.restore(token,root/'stage')
                commit.assert_not_called();recover.assert_not_called()

    def test_verifier_configuration_is_bound_to_decision_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            c,p,fresh,pair=setup(d)
            def crash(event):
                if event=='decision_durable':raise Crash()
            c.checkpoint=crash
            with self.assertRaises(Crash):
                apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request=None),authorize=lambda r:True,refresh_preparation=fresh)
            pair.mapping.branch_id='c'*32;c.checkpoint=lambda e:None
            with self.assertRaisesRegex(ValueError,'verifier differs'):c.recover('apply1')
            with self.assertRaisesRegex(ValueError,'blocks Play/build'):
                with c.publication_gate():self.fail('mixed revision admitted')

    def test_readiness_gate_serializes_other_project_writer(self):
        import subprocess
        import time
        with tempfile.TemporaryDirectory() as d:
            c,_=fixture(d);marker=Path(d)/'lock-held'
            code="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from cgs_persistence import CGSPersistence\nwith CGSPersistence(Path(sys.argv[2])).cgs_write_lock():Path(sys.argv[3]).write_text('acquired')"
            with c.publication_gate():
                child=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'packages/builder-workspace/server'),d,str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    time.sleep(.5);self.assertFalse(marker.exists());self.assertIsNone(child.poll())
                except BaseException:child.kill();child.communicate();raise
            stdout,stderr=child.communicate(timeout=10)
            self.assertEqual(child.returncode,0,stderr);self.assertEqual(marker.read_text(),'acquired')

    def test_saved_mapping_drift_rejects_prepare(self):
        with tempfile.TemporaryDirectory() as d:
            c,p,fresh,pair=setup(d)
            (Path(d)/MAP).write_bytes(encode(pair.mapping.to_dict()))
            with self.assertRaisesRegex(ValueError,'saved identity mapping differs'):fresh()

    def test_baseline_snapshot_must_match_durable_verification_record(self):
        with tempfile.TemporaryDirectory() as d:
            c,p,fresh,_=setup(d)
            apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request=None),authorize=lambda r:True,refresh_preparation=fresh)
            mapping=IdentityMap.from_dict(load_json(Path(d)/MAP));folder=c.journal/'apply1'
            manifest=load_json(folder/'manifest.json');manifest['request']['verification_record']['normalized_digest']='d'*64
            (folder/'manifest.json').write_bytes(encode(manifest));state=load_json(folder/'state.json');state['manifest_digest']=digest(manifest)
            (folder/'state.json').write_bytes(encode(state))
            with self.assertRaisesRegex(ValueError,'saved-pair contract'):verify_baseline_receipts(d,mapping.baseline)

    def test_restore_claim_does_not_replace_actual_before_verification(self):
        with tempfile.TemporaryDirectory() as d:
            def crash(event):
                if event=='published:canonical':raise Crash()
            c,r=fixture(d,crash)
            with self.assertRaises(Crash):c.commit(r,authorize=lambda r:True)
            c,_=fixture(d,initialize=False)
            with patch.object(c.participants['canonical'],'restore',return_value={'state':'before'}):
                with self.assertRaisesRegex(ValueError,'rollback verification'):c.recover('txn1',action='rollback')
            self.assertTrue(c.status()['play_build_blocked'])


if __name__=='__main__':unittest.main()
