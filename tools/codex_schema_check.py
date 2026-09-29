"""Generate protocol evidence without auth/model turns or activating a runtime."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'packages/builder-workspace/server'))
from agent_host.codex_runtime_lifecycle import _probe_stable_app_server, _read_version, _parse_version, _sha256_file
from agent_host.codex_compatibility import PROFILE, validate_schema, version_policy


def inspect(executable):
    version = _parse_version(_read_version(str(executable)))
    documents = _probe_stable_app_server(str(executable))
    fingerprint = hashlib.sha256(json.dumps(documents, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    report = {'schema': 'xace.codex_schema_evidence.v1', 'profile': PROFILE, 'version': version,
              'sha256': _sha256_file(executable), 'schema_fingerprint': fingerprint,
              'document_count': len(documents), 'real_account_certified': False,
              'compatible': False, 'version_admitted': False}
    try:
        version_policy(version); report['version_admitted'] = True
    except ValueError as exc:
        report['version_error'] = str(exc)
    try:
        validate_schema(documents); report['compatible'] = True
    except ValueError as exc:
        report['compatibility_error'] = str(exc)
    return report, documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report, documents = inspect(args.executable.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / (report['schema_fingerprint'] + '.json')).write_text(json.dumps(documents, sort_keys=True), encoding='utf8')
    (args.output / 'evidence.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps(report, indent=2))
    return 0 if report['compatible'] and report['version_admitted'] else 1


if __name__ == '__main__': raise SystemExit(main())
