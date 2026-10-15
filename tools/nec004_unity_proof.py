"""Run NEC-004 in a fresh, isolated trusted Unity fixture; never stage user projects."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UNITY = Path('C:/Program Files/Unity/Hub/Editor/6000.4.9f1/Editor/Unity.exe')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--phase', choices=['run', 'reload', 'play'], default='run')
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / 'recovery-evidence/20261015/nec004'):
        raise ValueError('Proof output must be under recovery-evidence/20261015/nec004')
    out.mkdir(parents=True, exist_ok=True)
    previous = [out / (args.phase + suffix) for suffix in ('.json', '-command.json', '-editor.log', '-process.log')]
    if any(p.exists() for p in previous):
        history = out / 'history' / str(len(list((out / 'history').glob('*'))) + 1)
        history.mkdir(parents=True)
        for path in previous:
            if path.exists():
                shutil.copy2(path, history / path.name)
    project = out / 'unity-project'
    for relative in ['Assets/XaceAuthoring', 'Packages', 'ProjectSettings', '.xace']:
        (project / relative).mkdir(parents=True, exist_ok=True)
    source = ROOT / 'adapters/unity/Authoring'
    for path in source.rglob('*'):
        if path.is_file():
            destination = project / 'Assets/XaceAuthoring' / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    (project / 'Packages/manifest.json').write_text(json.dumps({'dependencies': {
        'com.unity.modules.physics': '1.0.0', 'com.unity.modules.audio': '1.0.0',
        'com.unity.modules.animation': '1.0.0', 'com.unity.modules.jsonserialize': '1.0.0'}}, indent=2))
    (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.4.9f1\n')
    if args.phase == 'reload':
        sys.path.insert(0,str(ROOT/'packages/project-system'))
        from unity_authoring import prepare_identity_map, capture, policy, write_request
        from native_authoring_contract import inspect_capture
        from authoring_identity import canonical
        native=(project/'.xace/nec004-reload-expected.json').read_bytes()
        mapping=prepare_identity_map(native,project_id='nec004-native-fixture',branch_id='b'*32)
        base=capture(native,mapping,enable_writes=True).admit()
        desired=base.to_dict()['inspection']['capture']
        desired['objects'][f'{3:032x}']['fields']['transform.position']=dict(x='11',y='12',z='13')
        target=inspect_capture(desired,mapping,policy(enable_writes=True)).admit()
        request=write_request(native,base,target,mapping)
        (project/'.xace/nec004-python-request.json').write_bytes(request)
        (out/'python-write-request.json').write_bytes(request)
        (out/'native-identity-map.json').write_bytes(canonical(mapping.to_dict()))
        (out/'native-base.snapshot.json').write_bytes(base.payload)
    report = out / (args.phase + '.json')
    goldens=json.loads((ROOT/'packages/project-system/tests/fixtures/native_authoring_golden.json').read_text())
    golden_path=out/'unity-writer-golden.json'
    golden_path.write_text(json.dumps([r for r in goldens if r['engine']=='unity' and r['kind'] in {'position','rotation'} and not r.get('reject')],indent=2))
    command = [str(UNITY), '-batchmode', '-nographics', '-projectPath', str(project),
        '-executeMethod', 'Xace.Authoring.Editor.UnityAuthoringProof.' + {'run':'Run','reload':'Reload','play':'Play'}[args.phase],
        '-logFile', str(out / (args.phase + '-editor.log')), '-necReport', str(report), '-necGolden',str(golden_path)]
    (out / (args.phase + '-command.json')).write_text(json.dumps(command, indent=2))
    with (out / (args.phase + '-process.log')).open('wb') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=900,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError(f'Unity failed ({result.returncode}); inspect {out / (args.phase + "-editor.log")}')
    evidence = json.loads(report.read_text(encoding='utf-8-sig'))
    assert evidence['ok'], evidence
    if args.phase == 'reload':
        after=(project/'.xace/nec004-python-after.json').read_bytes()
        actual=capture(after,mapping,enable_writes=True).admit()
        fields=actual.to_dict()['inspection']['normalized'][f'{3:032x}']['fields']
        assert fields['transform.position']==dict(x='11000000',y='12000000',z='-13000000')
        assert canonical(json.loads(after))==after
        (out/'native-after.snapshot.json').write_bytes(actual.payload)
        (out/'python-bridge-proof.json').write_text(json.dumps(dict(ok=True,canonical_native_json=True,
            rows=len(mapping.objects),base_sha256=base.sha256,after_sha256=actual.sha256,
            position=fields['transform.position']),indent=2)+'\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
