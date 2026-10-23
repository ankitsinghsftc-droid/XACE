"""NEC011 creator-side readiness contract for NEC012 native host admission.

An observation must come from the host's native probe, never browser declarations.
The independently approved digest pins the profile and required bindings. This is
an evidence validator; it neither executes engines nor grants shipping certification.
"""
import copy
from authoring_identity import canonical,require,exact
from authoring_transaction_files import sha
SCHEMA='xace.native_fidelity_contract.v1'
OBSERVATION='xace.native_fidelity_observation.v1'
COORDINATES={'unity':'metres_y_up_positive_z','godot':'metres_y_up_negative_z','unreal':'centimetres_z_up_positive_x'}
IDENTITIES={'cgs','world','executor','input_config','controller','presentation'}
def digest(value):return sha(canonical(value))
def _hash(value):require(type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value),'SHA256 identity required')
def validate(contract):
    exact(contract,{'schema','engine','coordinates','numeric_profile','simulation_profile','identities','bindings','inputs','timing_authority'})
    require(contract['schema']==SCHEMA and contract['engine'] in COORDINATES,'fidelity contract engine/version')
    require(contract['coordinates']==COORDINATES[contract['engine']],'wrong native axes/scale')
    require(contract['numeric_profile']=='fixed64_y_up_neg_z_v1' and contract['simulation_profile']=='fixed64_60hz.v1','unsupported numeric/backend profile')
    require(contract['timing_authority']=='runtime_tick','native timing cannot govern gameplay')
    exact(contract['identities'],IDENTITIES)
    for value in contract['identities'].values():_hash(value)
    require(type(contract['bindings']) is list and len(contract['bindings'])<=4096,'binding bounds')
    names=[]
    for binding in contract['bindings']:
        exact(binding,{'id','role','resource_type','required','allow_cosmetic_fallback'})
        require(all(type(binding[k]) is str and binding[k] for k in ['id','role','resource_type']),'explicit resource identity/role/type required')
        require(type(binding['required']) is bool and type(binding['allow_cosmetic_fallback']) is bool,'binding flags')
        require(not(binding['required'] and binding['allow_cosmetic_fallback']),'required binding cannot use cosmetic fallback');names.append(binding['id'])
    require(names==sorted(set(names)),'sorted unique bindings required')
    require(type(contract['inputs']) is list and len(contract['inputs'])<=256,'input bounds')
    names=[]
    for binding in contract['inputs']:
        exact(binding,{'action','native_selector','packet_fields','controller_id'})
        require(type(binding['action']) is str and binding['action'] and type(binding['native_selector']) is str and binding['native_selector'],'explicit input mapping required')
        fields=binding['packet_fields'];require(type(fields) is list and fields and all(type(v) is str and v for v in fields) and fields==sorted(set(fields)),'sorted packet fields required')
        require(type(binding['controller_id']) is int and binding['controller_id']>0,'explicit controller required');names.append(binding['action'])
    require(names==sorted(set(names)),'sorted unique actions required')
    return copy.deepcopy(contract)
def evaluate(contract,observation,*,expected_contract_digest):
    """Fail closed on stale native config, absent resources and unauthorized timing."""
    _hash(expected_contract_digest);require(digest(contract)==expected_contract_digest,'unapproved fidelity contract')
    value=validate(contract)
    exact(observation,{'schema','engine','coordinates','numeric_profile','simulation_profile','identities','bindings','inputs','timing_authority','authority_requested_tick','packet_tick','native_gameplay_feedback'})
    require(observation['schema']==OBSERVATION,'fidelity observation version')
    exact(observation['identities'],IDENTITIES)
    for identity in observation['identities'].values():_hash(identity)
    # Reuse the strict input declaration types; Python bool must not alias controller 1.
    observed_inputs=copy.deepcopy(value);observed_inputs['inputs']=observation['inputs'];validate(observed_inputs)
    reasons=[]
    for key in ['engine','coordinates','numeric_profile','simulation_profile','identities','timing_authority','inputs']:
        if observation[key]!=value[key]:reasons.append('mismatch:'+key)
    tick=observation['authority_requested_tick'];packet=observation['packet_tick']
    if type(tick) is not int or type(packet) is not int or tick<0 or packet!=tick:reasons.append('invalid_input_timing')
    if observation['native_gameplay_feedback'] is not False:reasons.append('unauthorized_native_gameplay_feedback')
    require(type(observation['bindings']) is list,'binding observations required')
    rows={}
    for row in observation['bindings']:
        exact(row,{'id','role','resource_type','status','executed'})
        require(type(row['id']) is str and row['id'] not in rows,'duplicate native binding observation');rows[row['id']]=row
    if set(rows)!=set(b['id'] for b in value['bindings']):reasons.append('binding_set_mismatch')
    for binding in value['bindings']:
        row=rows.get(binding['id'])
        if row is None:continue
        playable=row['status']=='resolved' or (row['status']=='fallback' and binding['allow_cosmetic_fallback'] and not binding['required'])
        if row['role']!=binding['role'] or row['resource_type']!=binding['resource_type'] or not playable or row['executed'] is not True:reasons.append('binding_not_ready:'+binding['id'])
    return dict(schema='xace.native_fidelity_readiness.v1',ready=not reasons,blocking_reasons=sorted(reasons),contract_digest=expected_contract_digest,observation_digest=digest(observation),shipping_certified=False)


class NativeFidelityGate:
    """Host-installed, approved profile plus fresh native observation per launch.

    The probe is trusted creator configuration, never supplied by a web request.
    Native build/shipping admission remains a separate gate.
    """
    def __init__(self, contract, *, expected_contract_digest, probe):
        require(callable(probe), 'fresh native fidelity probe required')
        _hash(expected_contract_digest)
        require(digest(contract) == expected_contract_digest, 'unapproved fidelity contract')
        self._contract = canonical(validate(contract))
        self._digest = expected_contract_digest
        self._probe = probe

    def require_ready(self, *, current_cgs_digest):
        import json
        contract = json.loads(self._contract)
        require(contract['identities']['cgs'] == current_cgs_digest,
                'Native fidelity approval is stale for current CGS')
        observation = self._probe()
        report = evaluate(contract, observation, expected_contract_digest=self._digest)
        require(report['ready'], 'Native fidelity blocks Play: ' + ', '.join(report['blocking_reasons']))
        return report
