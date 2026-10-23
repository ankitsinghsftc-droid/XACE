import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_fidelity as f

def fixture(engine='godot'):
    contract=dict(schema=f.SCHEMA,engine=engine,coordinates=f.COORDINATES[engine],numeric_profile='fixed64_y_up_neg_z_v1',simulation_profile='fixed64_60hz.v1',identities={k:'a'*64 for k in f.IDENTITIES},bindings=[dict(id='walk',role='character.animation',resource_type='AnimationClip',required=True,allow_cosmetic_fallback=False)],inputs=[dict(action='move',native_selector='Move',packet_fields=['move_x'],controller_id=1)],timing_authority='runtime_tick')
    obs=copy.deepcopy(contract);obs.update(schema=f.OBSERVATION,authority_requested_tick=7,packet_tick=7,native_gameplay_feedback=False,bindings=[dict(id='walk',role='character.animation',resource_type='AnimationClip',status='resolved',executed=True)])
    return contract,obs
class FidelityTests(unittest.TestCase):
    def test_all_profiles_require_executed_bindings(self):
        for engine in f.COORDINATES:
            c,o=fixture(engine);self.assertTrue(f.evaluate(c,o,expected_contract_digest=f.digest(c))['ready'])
            o['bindings'][0]['executed']=False;self.assertFalse(f.evaluate(c,o,expected_contract_digest=f.digest(c))['ready'])
    def test_axes_scale_profiles_and_native_timing_refuse(self):
        c,o=fixture()
        for key,value in [('coordinates','centimetres_y_up'),('simulation_profile','native_physics'),('timing_authority','animation_event'),('native_gameplay_feedback',True),('packet_tick',8),('packet_tick',True)]:
            v=copy.deepcopy(o);v[key]=value;self.assertFalse(f.evaluate(c,v,expected_contract_digest=f.digest(c))['ready'])
    def test_stale_input_controller_executable_and_resources_refuse(self):
        c,o=fixture()
        for key in f.IDENTITIES:
            v=copy.deepcopy(o);v['identities'][key]='b'*64;self.assertFalse(f.evaluate(c,v,expected_contract_digest=f.digest(c))['ready'])
        for status in ['missing','unresolved','unsupported','fallback']:
            v=copy.deepcopy(o);v['bindings'][0]['status']=status;self.assertFalse(f.evaluate(c,v,expected_contract_digest=f.digest(c))['ready'])
        v=copy.deepcopy(o);v['inputs'][0]['packet_fields']=['jump'];self.assertFalse(f.evaluate(c,v,expected_contract_digest=f.digest(c))['ready'])
    def test_only_explicit_optional_fallback_and_approved_revision(self):
        c,o=fixture();c['bindings'][0].update(required=False,allow_cosmetic_fallback=True);o['bindings'][0]['status']='fallback'
        self.assertTrue(f.evaluate(c,o,expected_contract_digest=f.digest(c))['ready'])
        old=f.digest(c);c['identities']['presentation']='b'*64
        with self.assertRaises(ValueError):f.evaluate(c,o,expected_contract_digest=old)
        self.assertFalse(f.evaluate(c,o,expected_contract_digest=f.digest(c))['ready'])
        o['identities']['presentation']='b'*64;self.assertTrue(f.evaluate(c,o,expected_contract_digest=f.digest(c))['ready'])
    def test_boolean_controller_is_not_an_integer_identity(self):
        c,o=fixture();o['inputs'][0]['controller_id']=True
        with self.assertRaises(ValueError):f.evaluate(c,o,expected_contract_digest=f.digest(c))
    def test_unknown_and_duplicate_observations_refuse(self):
        c,o=fixture();o['bindings']*=2
        with self.assertRaises(ValueError):f.evaluate(c,o,expected_contract_digest=f.digest(c))
        c,o=fixture();o['extra']=True
        with self.assertRaises(ValueError):f.evaluate(c,o,expected_contract_digest=f.digest(c))
class FidelityGateTests(unittest.TestCase):
    def test_fresh_observation_required_on_every_launch(self):
        c,o=fixture();calls=[]
        def probe():calls.append(1);return copy.deepcopy(o)
        gate=f.NativeFidelityGate(c,expected_contract_digest=f.digest(c),probe=probe)
        self.assertTrue(gate.require_ready(current_cgs_digest='a'*64)['ready'])
        o['identities']['input_config']='b'*64
        with self.assertRaises(ValueError):gate.require_ready(current_cgs_digest='a'*64)
        self.assertEqual(len(calls),2)
    def test_stale_cgs_refused_before_probe_and_caller_cannot_mutate_profile(self):
        c,o=fixture();calls=[]
        def probe():calls.append(1);return o
        gate=f.NativeFidelityGate(c,expected_contract_digest=f.digest(c),probe=probe)
        c['identities']['cgs']='b'*64
        with self.assertRaises(ValueError):gate.require_ready(current_cgs_digest='b'*64)
        self.assertEqual(calls,[])
        self.assertTrue(gate.require_ready(current_cgs_digest='a'*64)['ready'])
if __name__=='__main__':unittest.main()
