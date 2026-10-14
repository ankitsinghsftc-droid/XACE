"""Independent local supervisor: retain completion/failure even when the soak fails."""
import argparse
import ctypes
import datetime
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    command = [sys.executable, '-u', str(root/'tools/xp022_player_soak.py'),
               '--artifacts', str(args.artifacts.resolve()), '--out', str(out/'run'), '--seconds', '7200']
    status = {'schema':'xace.background_soak.v1', 'status':'starting', 'supervisor_pid':os.getpid(),
              'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'command':command}
    def save():
        temporary = out/'status.pending.json'
        temporary.write_text(json.dumps(status, indent=2))
        temporary.replace(out/'status.json')
    save()
    child = None
    # Keep Windows awake for this process lifetime without changing power settings.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        with (out/'stdout.log').open('wb') as stdout, (out/'stderr.log').open('wb') as stderr:
            child = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            status.update(status='running', runner_pid=child.pid); save()
            code = child.wait(timeout=7800)
        report_path = out/'run/report.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else None
        completed = (code == 0 and report is not None and report.get('ok') is True
                     and report.get('full_duration') is True and report.get('elapsed_seconds',0) >= 7200
                     and report.get('rejoined') is True and report.get('authority_exited') is True)
        passed = completed and report.get('authority_budget_met') is True
        # A performance miss must not suppress verification of a complete archive.
        # It still fails the overall gate even when every replay segment verifies.
        if completed:
            archives = list((out/'run/rulesets').glob('recording-*'))
            if len(archives) != 1:
                raise ValueError('expected one authority replay archive')
            status.update(status='verifying_replay', soak_returncode=code); save()
            verify_command = [sys.executable, '-u', str(root/'tools/xp022_archive_verify.py'),
                              '--host', str(args.artifacts.resolve()/'parent/runtime/xace_runtime.exe'),
                              '--archive', str(archives[0]), '--out', str(out/'archive-verification')]
            with (out/'verification.stdout.log').open('wb') as stdout, (out/'verification.stderr.log').open('wb') as stderr:
                child = subprocess.Popen(verify_command,cwd=root,stdout=stdout,stderr=stderr,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                verification_code = child.wait(timeout=1800)
            verification_path = out/'archive-verification/report.json'
            verification = json.loads(verification_path.read_text()) if verification_path.exists() else {}
            passed = (passed and verification_code == 0 and verification.get('ok') is True
                      and verification.get('verified_ticks') == report['authority_ticks'])
            status.update(verification_returncode=verification_code, archive_verification=str(verification_path))
        status.update(status='passed' if passed else 'failed', returncode=code,
                      report=str(report_path) if report else None, certified=False)
    except BaseException:
        (out/'failure.txt').write_text(traceback.format_exc())
        status.update(status='failed', failure='See failure.txt and stderr.log', certified=False)
    finally:
        if child is not None and child.poll() is None:
            subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
            child.wait(timeout=20)
        status.update(elapsed_seconds=time.monotonic()-started,
                      finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        save()
        (out/'final-result.json').write_text(json.dumps(status,indent=2))
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == '__main__':main()
