"""Run inside the disposable AG-029 image; no credentials or hosted models."""
import json
from pathlib import Path
import subprocess
import sys


def main():
    root = Path('/provider/probe')
    root.mkdir()
    capsule = root / 'capsule'
    capsule.mkdir()
    (capsule / 'public').write_text('public-canary')
    private = root / 'private'
    private.write_text('synthetic-private')
    script = capsule / 'check.py'
    script.write_text(
        "import json,pathlib\nchecks={}\n"
        f"checks['allowed_read']=pathlib.Path({str(capsule / 'public')!r}).read_text()=='public-canary'\n"
        f"try: pathlib.Path({str(private)!r}).read_text(); checks['outside_read_denied']=False\n"
        "except (PermissionError,FileNotFoundError): checks['outside_read_denied']=True\n"
        f"try: pathlib.Path({str(capsule / 'write')!r}).write_text('x'); checks['write_denied']=False\n"
        "except OSError as e: checks['write_denied']=e.errno in (1,13,30)\n"
        "print(json.dumps(checks))\n")
    Path('/provider/config.toml').write_text(
        'default_permissions="xace_capsule"\napproval_policy="never"\n'
        '[permissions.xace_capsule.filesystem]\n":minimal"="read"\n'
        f'"{capsule}"="read"\n'
        '"/opt/codex"="read"\n'
        '[permissions.xace_capsule.network]\nenabled=false\n')
    result = subprocess.run(['codex', 'sandbox', '-P', 'xace_capsule', '-C', str(capsule),
                             '--', sys.executable, '-B', str(script)],
                            capture_output=True, text=True, timeout=30)
    print(json.dumps({'schema':'xace.ag029_container_probe.v1', 'exit_code':result.returncode,
                      'stdout':result.stdout[-4000:], 'stderr':result.stderr[-4000:],
                      'account_calls_performed':False, 'real_account_certified':False}))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
