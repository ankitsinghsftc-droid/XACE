"""Explicit opt-in, bounded AG-029 real-account candidate check (not release certification)."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

from codex_container_preflight import ROOT, IMAGE


REQUIRED_CHECKS = (
    'available','native_mcp','diagnostic_marker_observed','diagnostics_turn_completed',
    'streamed_deltas_observed','resume_same_thread','fork_new_thread','fork_parent_recorded',
    'cancel_requested_after_start','cancel_cleanup','resume_after_cancel','recovery_marker_observed',
    'compaction_accepted','compaction_completed','proposal_preview_created','proposal_persisted',
    'proposal_source_unchanged','approval_missing_denied','approval_wrong_denied','approval_gate_accepted',
    'rejection_clears_preview','owned_transport_outage','resume_after_outage','rate_limit_state_available',
    'provider_managed_billing',
)


def evaluate(report):
    missing = [key for key in REQUIRED_CHECKS if report.get(key) is not True]
    if report.get('auth_state') != 'signed_in': missing.append('auth_state')
    if report.get('recovery_terminal') != 'turn_completed': missing.append('recovery_terminal')
    if report.get('failure_code'): missing.append('failure_code')
    return {'candidate_scenarios_passed':not missing,'missing_or_failed_checks':missing}


BUILDER_IMAGE = 'sha256:a6a41c62440efcd715b09361b90c28cae4a13efe8d229f21db136ce013d1f2d2'
BUILDER_CHECKS = ('events_persisted','turn_completed','no_error_events','preview_delivered',
    'pending_preview','source_unchanged_before_approval','proposal_persisted','tool_calls_persisted',
    'discard_acknowledged','discard_cleared_pending','discard_persisted','source_unchanged_after_discard')


def command(docker):
    directory = ROOT / 'tools/ag029_container'
    return [str(docker),'run','--rm','--name','xace-ag029-live-probe','--read-only',
            '--cap-drop','ALL','--security-opt','no-new-privileges',
            '--security-opt',f'seccomp={directory / "seccomp.json"}',
            '--pids-limit','256','--memory','2g',
            '--mount','type=volume,source=xace-ag029-provider,target=/provider',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=256m',
            '--mount',f'type=bind,source={ROOT / "packages"},target=/xace/packages,readonly',
            '--mount',f'type=bind,source={directory / "xace_probe.py"},target=/probe.py,readonly',
            '--entrypoint','python',IMAGE,'/probe.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--real-account',action='store_true',required=True)
    parser.add_argument('--builder-router',action='store_true')
    args = parser.parse_args()
    paths = ['tools/ag029_container/xace_probe.py','tools/ag029_container/seccomp.json',
             'packages/builder-workspace/server/agent_host/codex_linux_profile.py',
             'packages/builder-workspace/server/agent_host/codex_adapter.py']
    if args.builder_router:
        paths.extend(['tools/ag029_container/builder_probe.py','tools/ag029_container/BuilderDockerfile',
                      'packages/builder-workspace/server/agent_host/event_stream.py'])
    before = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    launch = command(args.docker)
    if args.builder_router:
        launch = [arg.replace('xace-ag029-live-probe','xace-ag029-builder-probe')
                  .replace(IMAGE,BUILDER_IMAGE)
                  .replace('source='+str(ROOT/'tools/ag029_container/xace_probe.py')+',target=/probe.py,readonly',
                           'source='+str(ROOT/'tools/ag029_container')+',target=/probes,readonly')
                  .replace('/probe.py','/probes/builder_probe.py') for arg in launch]
    result = subprocess.run(launch,capture_output=True,text=True,encoding='utf8',timeout=600)
    report = {}
    for line in result.stdout.splitlines():
        try:
            value = json.loads(line)
            if value.get('schema') == ('xace.ag029_builder_probe.v1' if args.builder_router else 'xace.ag029_live_probe.v1'): report = value
        except (ValueError, AttributeError): pass
    # Persist check results, never account labels, tokens, raw provider output,
    # full events or raw errors. This report cannot activate any runtime.
    safe = {k:v for k,v in report.items() if isinstance(v,(bool,int)) or
            k in {'schema','profile','auth_state','selected_model','failure_code','failure_type',
                  'recovery_terminal','provider_managed_accounting','cancellation_events'}}
    safe.update({'image_id':BUILDER_IMAGE if args.builder_router else IMAGE,'artifact_hashes':before,'exit_code':result.returncode,
                 'recorded_at':datetime.now(timezone.utc).isoformat(),
                 'source_unchanged':all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest
                                        for p,digest in before.items()),
                 'real_account_certified':False,'runtime_activated':False})
    if args.builder_router:
        missing = [key for key in BUILDER_CHECKS if report.get(key) is not True]
        safe.update(candidate_scenarios_passed=not missing,missing_or_failed_checks=missing)
    else:
        safe.update(evaluate(report))
    safe['candidate_scenarios_passed'] = safe['candidate_scenarios_passed'] and safe['source_unchanged'] and result.returncode == 0
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(safe,indent=2,sort_keys=True)+'\n',encoding='utf8')
    print(json.dumps(safe,indent=2,sort_keys=True))
    return 0 if safe['candidate_scenarios_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
