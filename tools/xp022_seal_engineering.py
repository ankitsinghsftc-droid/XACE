"""Verify retained XP-022 gates and seal a local engineering review baseline.

This does not approve external release gates, move Git refs or start NEC.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from tools.xp022_certification import ROOT, sha, source_identity

HOST_SHA = '09825d6ebcc914a84dd0f3fb8000f0f3fbee3ec5810cfb1cc388a1466773cbe6'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    assert not out.exists(),'choose a fresh baseline directory'
    base=ROOT/'target/xp022/final-certification'
    artifacts=ROOT/'target/xp022/final-artifacts'
    release=base/'release-v2'
    evidence=[]
    def record(path):
        evidence.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),bytes=path.stat().st_size))
    def load(name):
        path=base/name;record(path)
        return json.loads(path.read_text(encoding='utf-8-sig'))
    ok_reports=['player-input/proof.json','presentation/proof.json','hosts-final/proof.json',
                'admission-final/proof.json','sockets/xp012_socket_proof/proof.json',
                'invite-v2/proof.json','relay/proof.json','debugger/proof.json',
                'process-faults-final/proof.json','native-v2/godot.json','native-v2/unity.json','native-v2/unreal.json']
    reports={name:load(name) for name in ok_reports}
    assert all(value['ok'] is True for value in reports.values())
    assert reports['presentation/proof.json']['full_suite']
    assert reports['player-input/proof.json']['render_fps_projection_digests_equal']
    assert reports['process-faults-final/proof.json']['host_sha256']==HOST_SHA
    assert reports['debugger/proof.json']['host_sha256']==HOST_SHA
    for name,digest in reports['hosts-final/proof.json']['pins'].items():assert sha(artifacts/name)==digest
    for name in ['pair','four']:assert reports['hosts-final/proof.json']['results'][name]['ok']
    launch=load('launch-v3/proof.json')
    assert launch['development_tools_absent_from_child_path']
    assert all(value is True for key,value in launch['results'].items() if key!='startup_ms')
    recovery=load('sockets/xp013_socket_proof/proof.json')
    assert recovery['recovery']['matches_authority'] and recovery['dropped_baseline']['fenced_after_timeout']
    faults=load('replay-faults/report.json')
    assert faults['local_subset_ok'] and all(c['ok'] for c in faults['cases']) and faults['host_sha256']==HOST_SHA
    for name in ['hardware.json','player-performance.json','packaging-v2.json','relay/relay-identity.json']:load(name)
    for name in ['reference-tests.log','world-extensibility-tests.log']:
        path=base/name;record(path);raw=path.read_bytes()
        content=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8')
        if name=='reference-tests.log':
            assert sum(map(int,re.findall(r'test result: ok\. (\d+) passed',content)))==23
            assert not re.search(r'test result: FAILED',content)
        else:assert 'Ran 8 tests' in content and content.strip().endswith('OK')
    soak=ROOT/'target/xp022/independent-fixed-20261008-042759'
    final=json.loads((soak/'final-result.json').read_text())
    assert final['status']=='passed' and final['verification_returncode']==final['soak_returncode']==0
    report=json.loads((soak/'run/report.json').read_text())
    replay=json.loads((soak/'archive-verification/report.json').read_text())
    assert report['host_sha256']==HOST_SHA and report['full_duration'] and report['authority_p95_ms']<16.7
    assert replay['ok'] and replay['verified_ticks']==report['authority_ticks']==202271
    for path in [soak/'final-result.json',soak/'run/report.json',soak/'archive-verification/report.json',ROOT/'docs/evidence/xp022-closeout-20261008.json']:record(path)
    # Recheck every distribution byte and ZIP member; exclude only authoring logs
    # and the manifest/trust envelope from the manifest's self-inventory.
    manifest=load('release-v2/distribution.json');trust=load('release-v2/distribution.trust.json')
    assert sha(release/'distribution.json')==trust['manifest_sha256']
    assert sha(release/'XACE Play.exe')==trust['broker_sha256']
    names=set()
    for entry in manifest['files']:
        path=(release/entry['path']).resolve();assert path.is_relative_to(release.resolve())
        assert entry['path'] not in names;names.add(entry['path'])
        assert path.stat().st_size==entry['size'] and sha(path)==entry['sha256']
    expected=names|{'distribution.json','distribution.trust.json'}
    actual={p.relative_to(release).as_posix() for p in release.rglob('*') if p.is_file() and not p.name.endswith('.export.log')}
    assert actual==expected and not any(n.endswith('.import') for n in actual)
    assert {'NOTICES.txt','GODOT_NOTICES.txt','README.txt'}<=names
    assert all((release/n).stat().st_size>100 for n in ['NOTICES.txt','GODOT_NOTICES.txt'])
    with zipfile.ZipFile(release.with_suffix('.zip')) as archive:
        assert set(archive.namelist())==expected
        for name in expected:assert hashlib.sha256(archive.read(name)).hexdigest()==sha(release/name)
    for name in ['runtime/xace_runtime.exe','game.cgs.json','execution_plan.json','world.json','world.manifest.json','compiled_schema.json']:
        assert sha(release/'package'/name)==sha(artifacts/'parent'/name),name
    original=json.loads((artifacts/'parent/playable.manifest.json').read_text())
    cleaned=json.loads((release/'package/playable.manifest.json').read_text())
    assert original['gameplay_hash']==cleaned['gameplay_hash'] and sha(release/'package/runtime/xace_runtime.exe')==HOST_SHA
    old=json.loads((ROOT/'target/xp022/closeout-source-20261008.json').read_text())
    prefixes=('packages/','apps/xace-player/','adapters/','examples/reference-mechanic/src/')
    for row in old['files']:
        if row['path'].startswith(prefixes):assert sha(ROOT/row['path'])==row['sha256'],row['path']
    # Exact native reader assemblies used by final installed-host tests.
    native=[]
    projects=[artifacts/'build/target-codex-task65-unity-vertical-slice',ROOT/'target/xp019/native/target-codex-task66-unreal-vertical-slice']
    for project in projects:
        for path in sorted(project.rglob('*.dll')):
            if path.name in ['XACE.Adapter.Unity.dll','XACE.Adapter.Unity.Editor.dll','UnrealEditor-XACEAdapter.dll']:
                native.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path)))
    assert {Path(item['path']).name for item in native}=={'XACE.Adapter.Unity.dll','XACE.Adapter.Unity.Editor.dll','UnrealEditor-XACEAdapter.dll'},'incomplete native assembly inventory'
    identity=source_identity(ROOT)
    # This output report is excluded to avoid a self-referential source digest.
    identity['files']=[r for r in identity['files'] if r['path']!='docs/evidence/xp022-engineering-candidate.json']
    identity['working_tree_sha256']=hashlib.sha256(json.dumps(identity['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    out.mkdir(parents=True)
    for index,item in enumerate(native):
        name=f"native-{index}-"+Path(item['path']).name
        shutil.copy2(ROOT/item['path'],out/name)
        item['sealed_copy']=name
    (out/'source-manifest.json').write_text(json.dumps(identity,indent=2)+'\n')
    with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for row in identity['files']:
            if row['sha256'] is not None:archive.write(ROOT/row['path'],row['path'])
    shutil.copy2(release.with_suffix('.zip'),out/'unsigned-release.zip')
    relay=json.loads((base/'relay/relay-identity.json').read_text())
    relay_path=Path(relay['executable']);assert sha(relay_path)==relay['sha256']
    shutil.copy2(relay_path,out/'xace-session-relay.exe')
    result=dict(schema='xace.xp022.engineering_baseline.v1',date='2026-10-08',
        engineering_gates_passed=True,baseline_status='sealed_for_engineering_review',
        release_certified=False,roadmap_amendment='proposed_pending_owner_approval',nec_started=False,
        source_revision=identity['revision'],working_tree_sha256=identity['working_tree_sha256'],
        runtime_sha256=HOST_SHA,gameplay_hash=cleaned['gameplay_hash'],
        baseline_directory=out.relative_to(ROOT).as_posix(),native_assemblies=native,
        production_source_unchanged_since_soak=True,
        artifact_scope='Windows installed-host/loopback/local TLS; original release acceptance remains open',
        production_fault_scope='Observable pre/post durable decision kills, failed migration/admission, slow consumer and transport/package faults; precise internal failpoints are separate test-build evidence',
        deferred_release_gates=['REL-01','REL-02','REL-03','REL-04','REL-05'],
        reports=evidence,sealed_files=[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in sorted(out.iterdir()) if p.is_file()])
    (out/'baseline.json').write_text(json.dumps(result,indent=2)+'\n')
    (ROOT/'docs/evidence/xp022-engineering-candidate.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['reports','native_assemblies','sealed_files']},indent=2))


if __name__=='__main__':main()
