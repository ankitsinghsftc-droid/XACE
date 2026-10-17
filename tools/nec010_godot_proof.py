"""Installed Godot editor proof in a dedicated trusted NEC-005 fixture only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GODOT = Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--phase', choices=['run', 'reload', 'play', 'privilege'], default='run')
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT/'evidence/nec010/20261017'):
        raise ValueError('Output must be under evidence/nec010/20261017')
    out.mkdir(parents=True, exist_ok=True)
    project = out/'godot-project'
    source = ROOT/'adapters/godot/authoring'
    dest = project/'addons/xace_authoring'
    dest.mkdir(parents=True, exist_ok=True)
    phase = args.phase
    old = [out/(phase+s) for s in ['.json', '-command.json', '-editor.log']]
    old += [project/('proof-'+phase+'.json')]
    if any(p.exists() for p in old):
        raise ValueError('Existing proof evidence; choose a fresh persistent output directory')
    for p in source.iterdir():
        if p.is_file(): shutil.copyfile(p, dest/p.name)
    # Only the fixture enables the explicitly invoked proof subclass.
    (dest/'plugin.cfg').write_text((source/'plugin.cfg').read_text().replace('script="authoring_plugin.gd"', 'script="native_proof.gd"'))
    (project/'project.godot').write_text('''config_version=5
[application]
config/name="NEC005 Native Authoring Proof"
[editor_plugins]
enabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")
[input]
move={"deadzone": 0.5, "events": []}
jump={"deadzone": 0.5, "events": []}
[rendering]
renderer/rendering_method="gl_compatibility"
''', encoding='utf-8')
    # Existing Player/editor runtime protocol is copied byte-for-byte for proof;
    # no authoring methods or privileges are added to it.
    shutil.copyfile(ROOT/'adapters/godot/xace_protocol.gd', project/'xace_protocol.gd')
    golden = json.loads((ROOT/'packages/project-system/tests/fixtures/native_authoring_golden.json').read_text())
    (project/'godot-golden.json').write_text(json.dumps([g for g in golden if g['engine']=='godot' and g['kind'] in {'position','rotation'} and g.get('losses')==[] and not g.get('reject')]))
    if phase == 'reload':
        sys.path.insert(0, str(ROOT/'packages/project-system'))
        from godot_authoring import prepare_identity_map, capture, policy, write_request
        from native_authoring_contract import inspect_capture
        from authoring_identity import canonical
        native = (project/'native-before.json').read_bytes()
        mapping = prepare_identity_map(native, project_id='nec005-fixture', branch_id='b'*32)
        base = capture(native, mapping, enable_writes=True).admit()
        changed = base.to_dict()['inspection']['capture']
        changed['objects'][f'{4:032x}']['fields']['transform.position'] = dict(x='11', y='12', z='13')
        target = inspect_capture(changed, mapping, policy(enable_writes=True)).admit()
        (project/'python-request.json').write_bytes(write_request(native,base,target,mapping))
        (out/'native-identity-map.json').write_bytes(canonical(mapping.to_dict()))
        (out/'native-base.snapshot.json').write_bytes(base.payload)
    command = [str(GODOT), '--headless', '--editor', '--path', str(project), '--', '--nec005-phase='+phase]
    if phase == 'privilege':
        command = [str(GODOT), '--headless', '--path', str(project), '--script', 'addons/xace_authoring/runtime_privilege_proof.gd']
    (out/(phase+'-command.json')).write_text(json.dumps(dict(command=command, cwd=str(ROOT), executable_sha256=hashlib.sha256(GODOT.read_bytes()).hexdigest()),indent=2)+'\n')
    try:
        result = subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=150,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/(phase+'-editor.log')).write_bytes(result.stdout)
    except subprocess.TimeoutExpired as exc:
        (out/(phase+'-editor.log')).write_bytes(exc.stdout or b'')
        raise
    report_path = project/('proof-'+phase+'.json')
    if not report_path.exists():
        raise RuntimeError('Editor did not emit proof; inspect log')
    shutil.copyfile(report_path,out/(phase+'.json'))
    report = json.loads(report_path.read_text())
    if result.returncode or not report['ok'] or b'SCRIPT ERROR:' in result.stdout:
        raise RuntimeError('Native proof failed; inspect report and editor log')
    if phase == 'reload':
        actual = (project/'native-after-python.json').read_bytes()
        snapshot = capture(actual,mapping,enable_writes=True).admit()
        position = snapshot.to_dict()['inspection']['normalized'][f'{4:032x}']['fields']['transform.position']
        assert position == dict(x='11000000',y='12000000',z='13000000')
        assert canonical(json.loads(actual)) == actual
        (out/'native-after.snapshot.json').write_bytes(snapshot.payload)
        (out/'python-bridge-proof.json').write_text(json.dumps(dict(ok=True,canonical_native_json=True,position=position,base_sha256=base.sha256,after_sha256=snapshot.sha256),indent=2)+'\n')
    print(json.dumps(dict(ok=True,phase=phase,checks=len(report['cases']),version=report['engine_version'])))


if __name__ == '__main__': main()
