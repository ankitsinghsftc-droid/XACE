"""Read-only AG-030 evidence admission; no provider calls or approval override."""
from datetime import date
import hashlib
import json
from pathlib import Path

HOST = 'docs/evidence/codex-ag029-host.json'
ISOLATION = 'docs/evidence/codex-ag029-isolation.json'
SETUP = 'docs/evidence/codex-ag030-setup.json'
REVIEW = 'docs/evidence/codex-ag030-review.json'
AGENT = 'packages/builder-workspace/server/agent_host'
CHECKS = (
    'signed_in', 'available', 'provider_managed', 'turn_completed', 'no_error_events',
    'preview_delivered', 'proposal_persisted', 'tool_calls_persisted', 'events_persisted',
    'missing_approval_denied', 'approval_handoff', 'real_gde_handoff', 'real_sgc_handoff',
    'discard_persisted', 'resume_same_thread', 'fork_new_thread', 'fork_lineage',
    'compaction_accepted', 'compaction_completed', 'cancel_cleanup',
    'recovery_turn_completed', 'recovery_marker', 'resume_after_owned_outage',
    'rate_limit_state_available', 'source_unchanged',
)
AREAS = {'isolation', 'auth', 'mcp', 'proposal_approval', 'persistence_recovery',
         'setup', 'compatibility', 'api_byok', 'privacy', 'upstream_support'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def production_hashes(root):
    server = root / 'packages/builder-workspace/server'
    paths = list(server.glob('*.py')) + list((server / 'agent_host').glob('*.py'))
    paths += list((root / 'packages/builder-workspace/src').rglob('*.ts'))
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate evidence field')
        value[key] = item
    return value


def read_record(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Evidence must be repository-local')
    if path.stat().st_size > 256_000:
        raise ValueError('Evidence too large')
    value = json.loads(path.read_text(encoding='utf8'), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError('Invalid evidence')
    return value


def validate_evidence(root: Path, *, today=None):
    """Fixed repository records, source hashes and accountable review, not flags.

    Local hashes establish integrity, not a publisher signature or protection
    against a maintainer maliciously rewriting both evidence and gate code.
    """
    blockers = []
    configurations = []
    today = today or date.today()
    try:
        host = read_record(root, HOST)
        if (host.get('schema') != 'xace.ag029_host_backend_proof.v1'
                or host.get('real_account_certified') is not True
                or any(host.get(key) is not True for key in CHECKS)
                or type(host.get('model_count')) is not int or host['model_count'] < 1
                or host.get('errors') != [] or host.get('status_codes') != []):
            raise ValueError('Incomplete live scenarios')
        expected = {p.relative_to(root).as_posix() for p in (root / AGENT).glob('*.py')}
        hashes = host.get('artifact_hashes', {})
        normalized = {p.replace('\\', '/'): h for p, h in hashes.items()}
        if not expected or len(normalized) != len(hashes) or set(normalized) != expected:
            raise ValueError('Incomplete build identity')
        if any(digest(root / path) != value for path, value in normalized.items()):
            raise ValueError('Stale build identity')
    except (OSError, ValueError, TypeError, AttributeError):
        blockers.append('ag029_real_runtime_account_evidence_invalid')
    try:
        isolation = read_record(root, ISOLATION)
        rows = isolation.get('checks', [])
        expected_checks = {
            'probe.py': {'allowed_read', 'outside_read_denied', 'write_denied'},
            'native_probe.py': {'private_content_hidden', 'private_file_unchanged',
                                'tool_roundtrip_observed', 'turn_completed'},
        }
        if (isolation.get('schema') != 'xace.codex_container_preflight.v1'
                or isolation.get('synthetic_preflight_passed') is not True
                or isolation.get('account_calls_performed') is not False
                or len(rows) != 2 or {r.get('probe') for r in rows} != set(expected_checks)):
            raise ValueError('Invalid isolation evidence')
        for row in rows:
            if (row.get('passed') is not True or row.get('exit_code') != 0
                    or any(row.get('checks', {}).get(k) is not True for k in expected_checks[row['probe']])):
                raise ValueError('Incomplete isolation evidence')
        hashes = isolation.get('artifact_hashes', {})
        if set(hashes) != {'Dockerfile', 'seccomp.json', 'probe.py', 'native_probe.py'}:
            raise ValueError('Missing isolation artifacts')
        if any(digest(root / 'tools/ag029_container' / name) != value for name, value in hashes.items()):
            raise ValueError('Stale isolation artifacts')
        if digest(root / AGENT / 'container_seccomp.json') != hashes['seccomp.json']:
            raise ValueError('Different production isolation policy')
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        blockers.append('ag029_isolation_evidence_invalid')
    try:
        setup = read_record(root, SETUP)
        if (setup.get('schema') != 'xace.codex_setup_acceptance.v1'
                or setup.get('provider_calls_performed') is not False
                or setup.get('image_id') != isolation.get('image_id')
                or any(setup.get(key) is not True for key in (
                    'checks_passed', 'missing_operator_header_denied', 'missing_consent_denied',
                    'protected_build_started', 'build_completed', 'backend_ready', 'device_flow_selected'))):
            raise ValueError('Real setup proof missing')
    except (OSError, ValueError, TypeError, AttributeError, UnboundLocalError):
        blockers.append('terminal_free_setup_evidence_invalid')
    try:
        review = read_record(root, REVIEW)
        if review.get('schema') != 'xace.codex_completion_review.v1':
            raise ValueError('Review schema missing')
        age = (today - date.fromisoformat(review['reviewed_at'])).days
        if not 0 <= age <= 30 or review.get('reviewed_areas') != sorted(AREAS):
            raise ValueError('Review stale or incomplete')
        if (review.get('evidence_sha256') != {p: digest(root / p) for p in (HOST, ISOLATION, SETUP)}
                or review.get('image_id') != isolation.get('image_id')):
            raise ValueError('Review does not bind this evidence')
        if review.get('reviewer') == '' or not isinstance(review.get('reviewer'), str):
            raise ValueError('Accountable review required')
        if review.get('source_sha256') != production_hashes(root):
            raise ValueError('Reviewed Builder source changed')
        issues = review.get('issues')
        if not isinstance(issues, list) or not issues:
            raise ValueError('An empty inventory is not a defect review')
        identifiers = [issue.get('id') for issue in issues]
        if len(set(identifiers)) != len(identifiers) or 'upstream_support' not in identifiers:
            raise ValueError('Required risk review missing or duplicated')
        for issue in issues:
            if issue.get('severity') not in {'P0', 'P1', 'P2', 'P3'} or not issue.get('id'):
                raise ValueError('Invalid defect review')
            if issue.get('id') != 'upstream_support' and issue.get('status') == 'resolved' and issue.get('evidence'):
                continue
            if issue['severity'] in {'P0', 'P1'}:
                blockers.append('unresolved_' + issue['id'])
            elif not (issue.get('status') == 'accepted' and issue.get('accepted_by')
                      and issue.get('acceptance_reference') and issue.get('rationale')
                      and issue.get('mitigation')):
                blockers.append('risk_acceptance_pending_' + issue['id'])
        if review.get('terminal_free_setup_verified') is not True:
            blockers.append('terminal_free_setup_not_verified')
        if review.get('review_complete') is not True:
            blockers.append('integration_defect_and_residual_risk_signoff_pending')
        if not blockers:
            configurations = [{'platform': 'windows_x64', 'backend': 'docker_desktop_wsl2',
                'codex_version': '0.155.1', 'image_id': review['image_id'],
                'account_scope': 'AG-029 opted-in ChatGPT account; entitlement remains provider-authoritative'}]
    except (OSError, ValueError, TypeError, AttributeError, KeyError, UnboundLocalError):
        blockers.append('integration_defect_and_residual_risk_signoff_pending')
    return {'blockers': sorted(set(blockers)), 'configurations': configurations}
