"""Read-only XP-022 seal verification; writes only a fresh NEC report.

Recovery default verifies the new persistent seal and its committed receipt.
--allow-master-update permits only MASTER_PLAN.md and AGENT_PROGRESS.md changes.
The reconstructed historical verifier is retained for provenance, not executed.
This does not reseal XP-022 or declare external release certification.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def child(root, name):
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), 'path escaped inventory root')
    return path


def verify_historical(allow_master_update=False):
    baseline = json.loads((BASE / 'baseline.json').read_text())
    source = json.loads((BASE / 'source-manifest.json').read_text())
    require(baseline['engineering_gates_passed'] and not baseline['release_certified'],
            'unexpected engineering/release boundary')
    require(sha(ROOT / 'docs/evidence/xp022-engineering-candidate.json') == sha(BASE / 'baseline.json'),
            'engineering candidate receipt changed')
    for root, rows in [(BASE, baseline['sealed_files']), (ROOT, baseline['reports'])]:
        for row in rows:
            path = child(root, row['path'])
            require(sha(path) == row['sha256'], 'changed sealed evidence: ' + str(path))
            require(path.stat().st_size == row['bytes'], 'changed size: ' + str(path))
    computed = hashlib.sha256(json.dumps(source['files'], sort_keys=True,
                              separators=(',', ':')).encode()).hexdigest()
    require(computed == source['working_tree_sha256'] == baseline['working_tree_sha256'],
            'source inventory digest mismatch')
    deviations = []
    with zipfile.ZipFile(BASE / 'source.zip') as archive:
        expected = {row['path'] for row in source['files'] if row['sha256'] is not None}
        require(set(archive.namelist()) == expected and len(archive.namelist()) == len(expected),
                'source archive inventory mismatch')
        for row in source['files']:
            if row['sha256'] is not None:
                require(hashlib.sha256(archive.read(row['path'])).hexdigest() == row['sha256'],
                        'source archive content mismatch: ' + row['path'])
            path = child(ROOT, row['path'])
            actual = sha(path) if path.is_file() else None
            if actual != row['sha256']:
                require(allow_master_update and row['path'] == 'MASTER_PLAN.md',
                        'frozen implementation changed: ' + row['path'])
                deviations.append(dict(path=row['path'], baseline_sha256=row['sha256'],
                                       current_sha256=actual, reason='NEC-001 live master-plan addendum'))
    for native in baseline['native_assemblies']:
        require(sha(child(ROOT, native['path'])) == native['sha256'], 'native assembly changed')
    release = ROOT / 'target/xp022/final-certification/release-v2'
    manifest = json.loads((release / 'distribution.json').read_text())
    trust = json.loads((release / 'distribution.trust.json').read_text())
    require(sha(release / 'distribution.json') == trust['manifest_sha256'], 'release trust mismatch')
    require(sha(release / 'XACE Play.exe') == trust['broker_sha256'], 'broker mismatch')
    with zipfile.ZipFile(BASE / 'unsigned-release.zip') as archive:
        expected = {row['path'] for row in manifest['files']} | {'distribution.json', 'distribution.trust.json'}
        require(set(archive.namelist()) == expected and len(archive.namelist()) == len(expected),
                'release ZIP inventory mismatch')
        for row in manifest['files']:
            path = child(release, row['path'])
            require(sha(path) == row['sha256'] and path.stat().st_size == row['size'], 'release byte mismatch')
        for name in expected:
            require(hashlib.sha256(archive.read(name)).hexdigest() == sha(child(release, name)),
                    'release ZIP content mismatch')
    require(sha(release / 'package/runtime/xace_runtime.exe') == baseline['runtime_sha256'], 'runtime mismatch')
    require(manifest['gameplay_hash'] == baseline['gameplay_hash'], 'gameplay mismatch')
    artifacts = ROOT / 'target/xp022/final-artifacts'
    hosts = json.loads((ROOT / 'target/xp022/final-certification/hosts-final/proof.json').read_text())
    for name, digest in hosts['pins'].items():
        require(sha(child(artifacts, name)) == digest, 'handoff executable changed')
    require(hosts['ok'] and all(hosts['results'][name]['ok'] for name in ['pair', 'four']), 'host proof failed')
    native_versions = {}
    for engine in ['unity', 'godot', 'unreal']:
        proof = json.loads((ROOT / f'target/xp022/final-certification/native-v2/{engine}.json').read_text())
        require(proof['ok'] and len(proof['cases']) == 15 and all(c['ok'] for c in proof['cases']),
                'native conformance proof failed')
        native_versions[engine] = proof['version']
    # Full before/after inventory of the seal and detailed certification tree.
    protected = []
    for folder in [BASE, ROOT / 'target/xp022/final-certification']:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                protected.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path)))
    return dict(schema='xace.nec001.seal_check.v1', ok=True,
                baseline_manifest_sha256=sha(BASE / 'baseline.json'),
                baseline_working_tree_sha256=computed, source_entries=len(source['files']),
                sealed_files=len(baseline['sealed_files']), reports=len(baseline['reports']),
                distribution_files=len(manifest['files']), native_versions=native_versions,
                runtime_sha256=baseline['runtime_sha256'], live_source_deviations=deviations,
                protected_files=protected, release_certified=False)


def verify(allow_master_update=False):
    """Recovery adaptation: verify the new seal; never impersonate original evidence."""
    receipt = json.loads((ROOT / 'docs/recovery/evidence/xp022-closeout-20261015/baseline-receipt.json').read_text())
    require(sha(BASE / 'baseline.json') == receipt['sha256'], 'recovery baseline receipt mismatch')
    baseline = json.loads((BASE / 'baseline.json').read_text())
    require(baseline['schema'] == 'xace.recovery_baseline.v1' and not baseline['original_seal'], 'not a recovery baseline')
    require(baseline['local_engineering_gates'] == 'passed', 'engineering gates not passed')
    protected = []
    for row in baseline['files']:
        p = child(BASE, row['path'])
        require(p.is_file() and sha(p) == row['sha256'] and p.stat().st_size == row['bytes'], 'changed sealed file: ' + row['path'])
        protected.append(dict(path=str(p), sha256=sha(p)))
    protected.append(dict(path=str(BASE / 'baseline.json'), sha256=sha(BASE / 'baseline.json')))
    source = json.loads((BASE / 'source-manifest.json').read_text())
    deviations = []
    with zipfile.ZipFile(BASE / 'source.zip') as archive:
        require(sorted(archive.namelist()) == sorted(r['path'] for r in source['files']), 'source inventory mismatch')
        for row in source['files']:
            require(hashlib.sha256(archive.read(row['path'])).hexdigest() == row['sha256'], 'archived source changed')
            p = child(ROOT, row['path']); actual = sha(p) if p.is_file() else None
            if actual != row['sha256']:
                require(allow_master_update and row['path'] in ['MASTER_PLAN.md', 'AGENT_PROGRESS.md'], 'frozen implementation changed: ' + row['path'])
                deviations.append(dict(path=row['path'], baseline_sha256=row['sha256'], current_sha256=actual))
    with zipfile.ZipFile(BASE / 'unsigned-release.zip') as archive:
        manifest = json.loads(archive.read('distribution.json')); trust = json.loads(archive.read('distribution.trust.json'))
        require(hashlib.sha256(archive.read('distribution.json')).hexdigest() == trust['manifest_sha256'], 'distribution trust mismatch')
        require(set(archive.namelist()) == {r['path'] for r in manifest['files']} | {'distribution.json','distribution.trust.json'}, 'release inventory mismatch')
        for row in manifest['files']:
            raw = archive.read(row['path'])
            require(len(raw) == row['size'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'distribution bytes changed')
        require(hashlib.sha256(archive.read('package/runtime/xace_runtime.exe')).hexdigest() == baseline['host_sha256'], 'host mismatch')
    return dict(schema='xace.nec001.recovery_seal_check.v1', ok=True, original_seal=False,
                baseline_manifest_sha256=receipt['sha256'], source_checkpoint=source['source_checkpoint'],
                source_entries=len(source['files']), sealed_files=len(baseline['files']), distribution_files=len(manifest['files']),
                runtime_sha256=baseline['host_sha256'], live_source_deviations=deviations,
                protected_files=protected, release_certified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-master-update', action='store_true')
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    require(out.is_relative_to((ROOT / 'recovery-evidence/20261015/nec001').resolve()), 'output must be under persistent NEC001 recovery evidence')
    require(not out.exists(), 'choose a fresh report filename')
    result = verify(args.allow_master_update)
    if args.compare:
        previous = json.loads(args.compare.read_text())
        require(result['protected_files'] == previous['protected_files'], 'protected evidence changed during NEC')
        require(result['baseline_manifest_sha256'] == previous['baseline_manifest_sha256'], 'baseline changed')
        result['protected_before_after_equal'] = True
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'protected_files'}, indent=2))


if __name__ == '__main__':
    main()
