import copy, hashlib, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_executor_contract as contracts
from test_native_reconciliation import context
from playable_package import compiled_artifacts


def fixture():
    cgs=context()['current_cgs'];package,_=compiled_artifacts(cgs)
    raw=b'fixture executable bytes; never executed'
    h=hashlib.sha256(raw).hexdigest();sources={'Cargo.lock':'a'*64,'src/lib.rs':'b'*64}
    compatibility=dict(runtime_abi='xace.runtime_executor.v1',numeric_profile='fixed64_y_up_neg_z_v1',simulation_profile='fixed64_60hz.v1',world_versions=[2,3],geometry_profiles=['world.aabb.v1'],snapshot_schema='xace.world_snapshot.v1',replay_schema='xace.epoch_replay.v1',input_schema='xace.input_packet.v1',event_schema='xace.domain_event.v1',platform='windows_x64')
    systems=package.to_sgc_input()
    if not systems:
        # Package fixture is a static world; support may include an unused system.
        systems=[dict(id='custom.graph.v1',phase='Simulation',reads=[10000],writes=[10000],depends_on=[],deterministic=True)]
    r=dict(schema=contracts.SCHEMA,executor_id='creator.graph.v1',source_files=sources,toolchain=dict(rustc_verbose='fixture rustc',rustc_sha256='c'*64,linker_sha256='d'*64,target='x86_64-pc-windows-msvc'),build=dict(command=['cargo','build','--locked','--offline'],environment={},source_digest=contracts.digest(sources),independent_outputs=[dict(build_id=n,executable_sha256=h) for n in ['first','second']]),executable_sha256=h,systems=sorted(systems,key=lambda s:s['id']),capabilities=['custom.graph.v1'],compatibility=compatibility,state_policy='all_gameplay_state_in_snapshot_no_hidden_mutable_state',shipping=dict(player_compilation=False,required_files={'runtime/xace_runtime.exe':h},notices=['NOTICE']))
    return r,raw,package


class ExecutorAdmissionTests(unittest.TestCase):
    def test_admission_reuses_package_support_without_execution(self):
        r,raw,package=fixture()
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'candidate.exe';exe.write_bytes(raw)
            support=contracts.admit(r,expected_receipt_digest=contracts.digest(r),executable=exe,required_capabilities=['custom.graph.v1'],expected_compatibility=r['compatibility'],package=package)
            self.assertEqual(support.executable_sha256,hashlib.sha256(raw).hexdigest())
            exe.write_bytes(raw+b'changed')
            with self.assertRaisesRegex(ValueError,'Executable changed'):
                contracts.admit(r,expected_receipt_digest=contracts.digest(r),executable=exe,required_capabilities=[],expected_compatibility=r['compatibility'],package=package)

    def test_untrusted_receipt_capability_and_state_mismatch_refuse(self):
        r,raw,package=fixture()
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'candidate.exe';exe.write_bytes(raw)
            args=dict(expected_receipt_digest=contracts.digest(r),executable=exe,required_capabilities=[],expected_compatibility=r['compatibility'],package=package)
            for change in [dict(expected_receipt_digest='0'*64),dict(required_capabilities=['missing.v1']),dict(expected_compatibility={})]:
                with self.assertRaises(ValueError):contracts.admit(r,**{**args,**change})

    def test_nonreproducible_or_changed_build_refuses(self):
        r,_,_=fixture()
        mutations=[lambda v:v['build']['independent_outputs'][1].update(executable_sha256='f'*64),lambda v:v['build']['independent_outputs'][1].update(build_id='first'),lambda v:v['source_files'].update({'src/lib.rs':'f'*64}),lambda v:v['build'].update(command=['cargo','build']),lambda v:v['shipping'].update(player_compilation=True),lambda v:v.update(state_policy='hidden_state')]
        for mutation in mutations:
            v=copy.deepcopy(r);mutation(v)
            with self.assertRaises(ValueError):contracts.validate(v)

    def test_real_factory_system_metadata_is_retained(self):
        import json
        from playable_package import compiled_artifacts
        root=Path(__file__).resolve().parents[3]
        cgs=json.loads((root/'examples/nec011-echo/fixtures/game.cgs.json').read_text())
        package,_=compiled_artifacts(cgs);r,_,_=fixture();r['systems']=package.to_sgc_input()
        checked=contracts.validate(r)
        self.assertEqual(checked['systems'],r['systems'])
        r['systems'][0]['version']['major']='1'
        with self.assertRaises(ValueError):contracts.validate(r)

    def test_malformed_scheduling_and_shipping_refuse(self):
        r,_,_=fixture()
        changes=[lambda v:v['systems'][0].update(phase='Render'),lambda v:v['systems'][0].update(depends_on=[v['systems'][0]['id']]),lambda v:v['compatibility'].update(world_versions=None),lambda v:v['shipping']['required_files'].update({'../escape':'a'*64}),lambda v:v['shipping']['required_files'].update({'runtime/CON.exe':'a'*64}),lambda v:v['shipping']['required_files'].update({'Runtime/XACE_Runtime.exe':v['executable_sha256']})]
        for change in changes:
            v=copy.deepcopy(r);change(v)
            with self.assertRaises(ValueError):contracts.validate(v)

    def test_structured_host_admission_is_pinned_and_rechecked(self):
        r,raw,package=fixture()
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'candidate.exe';exe.write_bytes(raw)
            def admission(value):return contracts.TrustedExecutor(value,expected_receipt_digest=contracts.digest(value),executable=exe,expected_compatibility=value['compatibility'])
            with self.assertRaisesRegex(ValueError,'capability'):admission(r).require_structured_transform(package)
            r['capabilities'].append('native.structured_transform.v1');r['capabilities'].sort()
            trusted=admission(r);self.assertEqual(trusted.require_structured_transform(package).executable_sha256,contracts.sha(raw))
            r['capabilities'].clear()  # caller mutation cannot change pinned bytes
            trusted.require_structured_transform(package)
            exe.write_bytes(raw+b'changed')
            with self.assertRaisesRegex(ValueError,'Executable changed'):trusted.require_structured_transform(package)

    def test_reconciliation_keeps_gate_without_exact_host_contract(self):
        from test_native_reconciliation import refresh
        from native_reconciliation_plan import plan_reconciliation
        c=context();c['current_cgs']['modes'][0]['systems']=[dict(id='creator.translation.v1',phase='Simulation',reads=[1],writes=[1],depends_on=[],deterministic=True)];refresh(c)
        self.assertFalse(plan_reconciliation(**c).to_dict()['reviewable'])
        package,_=compiled_artifacts(c['current_cgs']);r,raw,_=fixture();r['systems']=package.to_sgc_input();r['capabilities']=['native.structured_transform.v1']
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'host.exe';exe.write_bytes(raw)
            trusted=contracts.TrustedExecutor(r,expected_receipt_digest=contracts.digest(r),executable=exe,expected_compatibility=r['compatibility'])
            c['trusted_executor']=trusted;result=plan_reconciliation(**c).to_dict()
            self.assertTrue(result['reviewable'],result['losses']);self.assertEqual(result['identities']['executor_receipt'],contracts.digest(r))
            exe.write_bytes(raw+b'changed');result=plan_reconciliation(**c).to_dict()
            self.assertFalse(result['reviewable']);self.assertIn('uncertified_structured_transform_system',[v['code'] for v in result['losses']])

    def test_source_paths_and_duplicate_contracts_refuse(self):
        r,_,_=fixture()
        for path in ['../secret','C:/secret','dir\\secret','/absolute']:
            v=copy.deepcopy(r);v['source_files'][path]='a'*64
            with self.assertRaises(ValueError):contracts.validate(v)
        v=copy.deepcopy(r);v['systems']*=2
        with self.assertRaises(ValueError):contracts.validate(v)

if __name__=='__main__':unittest.main()
