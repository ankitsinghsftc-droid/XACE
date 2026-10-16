"""Retained real-filesystem crash/recovery evidence. Never touches native projects."""
import errno,json,subprocess,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'packages/project-system/tests')]
from test_authoring_transaction import fixture,EVENTS,Crash
from test_authoring_apply import setup
from authoring_transaction_files import sha,load_json
from authoring_apply import apply_prepared
from authoring_saved_pair import MAP,verify_baseline_receipts
from authoring_identity import IdentityMap
from native_adoption import encode


def main(out):
    assert out.resolve().is_relative_to(ROOT/'recovery-evidence/20261016/nec009') and not out.exists();out.mkdir(parents=True)
    cases=[]
    for i,event in enumerate(EVENTS):
        folder=out/f'boundary-{i:02}';folder.mkdir()
        def crash(name):
            if name==event:raise Crash(name)
        c,r=fixture(folder,crash)
        try:c.commit(r,authorize=lambda r:True)
        except Crash:pass
        else:raise AssertionError('fault not reached')
        before=c.status();c,_=fixture(folder,initialize=False);result=c.recover('txn1')
        expected='aborted' if i<EVENTS.index('decision_durable') else 'committed'
        assert result['state']==expected
        assert (folder/'game.cgs.json').read_bytes()==(b'old-cgs' if expected=='aborted' else b'new-cgs')
        assert (folder/'native.scene').read_bytes()==(b'old-native' if expected=='aborted' else b'new-native')
        cases.append(dict(case=event,kind='injected_process_boundary',before=before,result=result['state'],folder=str(folder.relative_to(ROOT))))
    for i,event in enumerate(['decision_durable','published_before_receipt:canonical','baseline_published_before_receipt']):
        folder=out/f'process-{i}';fixture(folder)
        command=[sys.executable,str(ROOT/'packages/project-system/tests/test_authoring_transaction.py')]
        child=subprocess.run([*command,'--crash',str(folder),event],capture_output=True)
        (folder/'crash.log').write_bytes(child.stdout+child.stderr);assert child.returncode==73
        c,_=fixture(folder,initialize=False);assert c.status()['play_build_blocked']
        child=subprocess.run([*command,'--recover',str(folder)],capture_output=True)
        (folder/'restart.log').write_bytes(child.stdout+child.stderr);assert child.returncode==0
        assert load_json(folder/'.xace/authoring-transactions/txn1/state.json')['state']=='committed'
        cases.append(dict(case=event,kind='actual_os_exit_and_fresh_process',exit_code=73,result='committed',folder=str(folder.relative_to(ROOT))))
    for action in ['resume','rollback']:
        folder=out/('independent-edit-'+action)
        def crash(name):
            if name=='published:canonical':raise Crash()
        c,r=fixture(folder,crash)
        try:c.commit(r,authorize=lambda r:True)
        except Crash:pass
        (folder/'game.cgs.json').write_bytes(b'newer-user-edit');c,_=fixture(folder,initialize=False)
        try:c.recover('txn1',action=action)
        except ValueError:pass
        else:raise AssertionError('independent edit overwritten')
        assert (folder/'game.cgs.json').read_bytes()==b'newer-user-edit' and c.status()['play_build_blocked']
        cases.append(dict(case=action,kind='independent_edit_conflict',result='recovery_conflict',newer_work_preserved=True,folder=str(folder.relative_to(ROOT))))
    for engine in ['unity','godot','unreal']:
        for kind in ['adopt','reconcile']:
            folder=out/(engine+'-'+kind);folder.mkdir();c,p,fresh,_=setup(folder,engine,kind)
            result=apply_prepared(c,p,transaction_id='apply1',native_participant_request=dict(write_request=None),authorize=lambda r:True,refresh_preparation=fresh)
            mapping=IdentityMap.from_dict(load_json(folder/MAP));assert verify_baseline_receipts(folder,mapping.baseline)
            cases.append(dict(case=engine+'-'+kind,kind='gde_apply_fixture_gateway',result=result['state'],baseline_verified=True,folder=str(folder.relative_to(ROOT))))
    proof=dict(schema='xace.nec009.transaction_proof.v1',ok=True,cases=cases,durable_boundaries=14,actual_process_restarts=3,independent_edit_conflicts=2,gde_apply_profiles=6,runtime_activation=False,native_editor_launched=False)
    (out/'proof.json').write_bytes(encode(proof));print(json.dumps(dict(ok=True,cases=len(cases))))


if __name__=='__main__':main(Path(sys.argv[1]).resolve())
