"""Creator-built gameplay identity and admission, layered on playable packages.

The host supplies the expected receipt digest out-of-band. A receipt in an
untrusted project cannot authorize its own executable. Verification never runs it.
"""
import copy
import hashlib
from pathlib import Path
from authoring_identity import canonical, require
from playable_package import RuntimeSupport, check_support

SCHEMA = 'xace.native_executor_build.v1'
COMPATIBILITY = {'runtime_abi', 'numeric_profile', 'simulation_profile',
                 'world_versions', 'geometry_profiles', 'snapshot_schema',
                 'replay_schema', 'input_schema', 'event_schema', 'platform'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(canonical(value))


def hash_value(value):
    require(type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'SHA256 required')


def ordered_strings(values):
    require(type(values) is list and values and all(type(v) is str and v and len(v) <= 256 for v in values), 'Nonempty string list required')
    require(values == sorted(set(values)), 'Sorted unique declarations required')


def portable_path(path):
    require(type(path) is str and path and not path.startswith('/') and '\\' not in path and ':' not in path and all(p not in {'','..','.'} for p in path.split('/')), 'Portable source path required')
    reserved={'CON','PRN','AUX','NUL'}|{prefix+str(i) for prefix in ['COM','LPT'] for i in range(1,10)}
    require(all(part==part.rstrip(' .') and part.split('.')[0].upper() not in reserved and not any(ord(c)<32 or c in '<>"|?*' for c in part) for part in path.split('/')), 'Windows-safe portable path required')


def validate(receipt):
    require(type(receipt) is dict and set(receipt) == {'schema','executor_id','source_files','toolchain','build','executable_sha256','systems','capabilities','compatibility','state_policy','shipping'}, 'Invalid executor receipt fields')
    require(receipt['schema'] == SCHEMA, 'Unsupported executor receipt')
    require(type(receipt['executor_id']) is str and receipt['executor_id'].endswith('.v1'), 'Versioned executor identity required')
    files=receipt['source_files']
    require(type(files) is dict and files and len(files) <= 10000, 'Build input inventory required')
    for path,value in files.items():
        require(type(path) is str and path and not path.startswith('/') and '\\' not in path and ':' not in path and all(p not in {'','..','.'} for p in path.split('/')), 'Portable source path required')
        portable_path(path)
        hash_value(value)
    require(len({p.casefold() for p in files})==len(files),'Aliased source paths')
    require('Cargo.lock' in files, 'Locked dependencies required')
    toolchain=receipt['toolchain']
    require(type(toolchain) is dict and set(toolchain)=={'rustc_verbose','rustc_sha256','linker_sha256','target'}, 'Pinned creator toolchain required')
    require(type(toolchain['rustc_verbose']) is str and bool(toolchain['rustc_verbose']), 'Compiler version required')
    hash_value(toolchain['rustc_sha256']);hash_value(toolchain['linker_sha256'])
    require(toolchain['target']=='x86_64-pc-windows-msvc', 'Uncertified creator target')
    build=receipt['build']
    require(type(build) is dict and set(build)=={'command','environment','source_digest','independent_outputs'}, 'Build recipe required')
    require(type(build['command']) is list and build['command'] and all(type(v) is str for v in build['command']), 'Build command required')
    require('--locked' in build['command'] and '--offline' in build['command'], 'Locked offline creator compilation required')
    require(type(build['environment']) is dict and all(type(k) is str and type(v) is str for k,v in build['environment'].items()), 'Explicit build environment required')
    require(build['source_digest']==digest(files), 'Build source inventory changed')
    hash_value(receipt['executable_sha256'])
    outputs=build['independent_outputs']
    require(type(outputs) is list and len(outputs)==2 and all(type(o) is dict and set(o)=={'build_id','executable_sha256'} for o in outputs), 'Two independent build receipts required')
    require(all(type(o['build_id']) is str and o['build_id'] for o in outputs) and outputs[0]['build_id']!=outputs[1]['build_id'], 'Independent build identities required')
    require(all(o['executable_sha256']==receipt['executable_sha256'] for o in outputs), 'Creator compilation is not reproducible')
    systems=receipt['systems']
    require(type(systems) is list and systems and all(type(s) is dict and type(s.get('id')) is str for s in systems), 'Executable system census required')
    require([s['id'] for s in systems]==sorted(set(s['id'] for s in systems)), 'Sorted unique system census required')
    for system in systems:
        required={'id','phase','reads','writes','depends_on','deterministic'}
        require(required<=set(system)<=required|{'display_name','version','description'}, 'Exact SGC system contract required')
        for key in ['display_name','description']:
            if key in system:require(type(system[key]) is str, 'Invalid SGC metadata')
        if 'version' in system:
            require(type(system['version']) is dict and set(system['version'])=={'major','minor'} and all(type(v) is int and v>=0 for v in system['version'].values()), 'Invalid SGC system version')
        require(system['phase'] in ['Initialization','Input','Simulation','PostSimulation','Cleanup'], 'Unsupported execution phase')
        require(system['deterministic'] is True, 'Uncertified nondeterministic executor')
        for key in ['reads','writes']:
            values=system[key];require(type(values) is list and all(type(v) is int and v>0 for v in values) and values==sorted(set(values)), 'Sorted component access required')
        require(type(system['depends_on']) is list and all(type(v) is str and v for v in system['depends_on']) and system['depends_on']==sorted(set(system['depends_on'])) and system['id'] not in system['depends_on'], 'Sorted non-self system dependencies required')
    ordered_strings(receipt['capabilities'])
    compatibility=receipt['compatibility']
    require(type(compatibility) is dict and set(compatibility)==COMPATIBILITY, 'Complete compatibility identity required')
    require(compatibility['runtime_abi']=='xace.runtime_executor.v1' and compatibility['numeric_profile']=='fixed64_y_up_neg_z_v1' and compatibility['simulation_profile']=='fixed64_60hz.v1' and compatibility['platform']=='windows_x64', 'Unsupported runtime profile')
    require(type(compatibility['world_versions']) is list and all(type(v) is int for v in compatibility['world_versions']) and compatibility['world_versions']==sorted(set(compatibility['world_versions'])) and all(type(v) is int and v in (2,3) for v in compatibility['world_versions']) and compatibility['world_versions'], 'Unsupported World contract')
    ordered_strings(compatibility['geometry_profiles'])
    for key in ['snapshot_schema','replay_schema','input_schema','event_schema']:
        require(type(compatibility[key]) is str and compatibility[key].endswith('.v1'), 'Versioned state and wire identity required')
    require(receipt['state_policy']=='all_gameplay_state_in_snapshot_no_hidden_mutable_state', 'Uncertified state policy')
    shipping=receipt['shipping']
    require(type(shipping) is dict and set(shipping)=={'player_compilation','required_files','notices'}, 'Shipping closure required')
    require(shipping['player_compilation'] is False, 'Player compilation forbidden')
    require(type(shipping['required_files']) is dict and shipping['required_files'].get('runtime/xace_runtime.exe')==receipt['executable_sha256'], 'Executable shipping identity missing')
    for path,value in shipping['required_files'].items():portable_path(path);hash_value(value)
    require(len({p.casefold() for p in shipping['required_files']})==len(shipping['required_files']),'Aliased shipping paths')
    ordered_strings(shipping['notices'])
    return copy.deepcopy(receipt)


def admit(receipt, *, expected_receipt_digest, executable, required_capabilities, expected_compatibility, package):
    hash_value(expected_receipt_digest)
    require(digest(receipt)==expected_receipt_digest, 'Receipt differs from trusted host identity')
    value=validate(receipt)
    require(sha(Path(executable).read_bytes())==value['executable_sha256'], 'Executable changed')
    require(type(required_capabilities) in (list,tuple) and all(type(v) is str and v for v in required_capabilities),'Explicit required capability list required')
    require(set(required_capabilities)<=set(value['capabilities']), 'Missing required executor capability')
    require(value['compatibility']==expected_compatibility, 'Executor state/backend compatibility mismatch')
    support=RuntimeSupport(value['executable_sha256'],value['compatibility']['runtime_abi'],tuple(value['systems']),tuple(value['compatibility']['geometry_profiles']),tuple(value['compatibility']['world_versions']))
    check_support(package,support)
    return support


class TrustedExecutor:
    """Host configuration only; never constructed from browser/project requests.

    Rechecks executable bytes and the complete package system contract on every
    planning call. The host pins its independently reviewed receipt digest and
    compatibility identity; a capability string in CGS is never authority.
    """
    def __init__(self, receipt, *, expected_receipt_digest, executable, expected_compatibility):
        import json
        hash_value(expected_receipt_digest)
        require(digest(receipt)==expected_receipt_digest,'Receipt differs from trusted host identity')
        self._receipt=canonical(validate(receipt))
        self._expected=expected_receipt_digest
        self._executable=str(Path(executable).resolve())
        self._compatibility=canonical(expected_compatibility)

    @property
    def receipt_digest(self):return self._expected

    def require_structured_transform(self, package):
        import json
        return admit(json.loads(self._receipt),expected_receipt_digest=self._expected,
                     executable=self._executable,required_capabilities=['native.structured_transform.v1'],
                     expected_compatibility=json.loads(self._compatibility),package=package)
