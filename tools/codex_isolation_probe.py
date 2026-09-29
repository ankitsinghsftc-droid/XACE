"""Credential-free, no-model AG-029 native permission-profile probe.

Runs only a fixed canary program in a disposable tree. This operator tool is
never exposed to Builder agents and does not activate or certify a runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def isolated_environment(home: Path, temp: Path) -> dict[str, str]:
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    # CODEX_HOME is used only for its documented provider-home purpose, in this
    # credential-free child. The parent's home/config/environment is unchanged.
    env.update(CODEX_HOME=str(home), TEMP=str(temp), TMP=str(temp),
               USERPROFILE=str(home), HOME=str(home), APPDATA=str(home / "roaming"),
               LOCALAPPDATA=str(home / "local"))
    return env


def probe(executable: Path, *, backend: str = "unelevated") -> dict:
    if backend not in {"unelevated", "elevated"}:
        raise ValueError("Unknown Windows sandbox backend")
    base = ROOT / "tmp"
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ag029-isolation-", dir=base) as directory:
        root = Path(directory).resolve()
        capsule, home, temp = (root / name for name in ("capsule", "provider", "temp"))
        for path in (capsule, home, temp):
            path.mkdir()
        allowed_file = capsule / "public.txt"
        denied_file = root / "private.txt"
        auth_canary = home / "auth-canary.txt"
        allowed_file.write_text("synthetic-public", encoding="utf8")
        denied_file.write_text("synthetic-private", encoding="utf8")
        auth_canary.write_text("synthetic-credential", encoding="utf8")
        script = capsule / "canary.py"
        script.write_text(
            "import json,pathlib\n"
            "checks={}\n"
            f"checks['allowed_read']=pathlib.Path({str(allowed_file)!r}).read_text()=='synthetic-public'\n"
            f"for key,path in [('outside_read_denied',{str(denied_file)!r}),('credential_read_denied',{str(auth_canary)!r})]:\n"
            " try: pathlib.Path(path).read_text(); checks[key]=False\n"
            " except PermissionError: checks[key]=True\n"
            " except OSError: checks[key]=False\n"
            f"for key,path in [('capsule_write_denied',{str(capsule / 'write-canary')!r}),('outside_write_denied',{str(root / 'write-canary')!r})]:\n"
            " try: pathlib.Path(path).write_text('synthetic'); checks[key]=False\n"
            " except PermissionError: checks[key]=True\n"
            " except OSError: checks[key]=False\n"
            "print(json.dumps(checks))\n", encoding="utf8")
        quote = lambda path: json.dumps(Path(path).as_posix())
        config = (
            'default_permissions = "xace_capsule"\napproval_policy = "never"\n'
            '[permissions.xace_capsule.filesystem]\n":minimal" = "read"\n'
            f'{quote(capsule)} = "read"\n{quote(Path(sys.executable).parent)} = "read"\n'
            '[permissions.xace_capsule.network]\nenabled = false\n'
            f'[windows]\nsandbox = "{backend}"\n')
        (home / "config.toml").write_text(config, encoding="utf8")
        command = [str(executable), "sandbox", "-P", "xace_capsule", "-C", str(capsule),
                   "--", sys.executable, "-B", str(script)]
        result = subprocess.run(command, env=isolated_environment(home, temp), cwd=capsule,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding="utf8", errors="replace", timeout=60)
        checks = {}
        for line in result.stdout.splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    checks = value
            except ValueError:
                pass
        expected = {"allowed_read", "outside_read_denied", "credential_read_denied",
                    "capsule_write_denied", "outside_write_denied"}
        checks = {key: checks.get(key) is True for key in sorted(expected)}
        error = "none" if result.returncode == 0 else (
            "elevated_backend_required" if "requires the elevated Windows sandbox backend" in result.stderr else
            "elevated_root_read_required" if "requires effective `:root` read access" in result.stderr else
            "deny_read_acl_failure" if "deny-read ACLs" in result.stderr else "sandbox_probe_failed")
        return {"schema": "xace.codex_isolation_probe.v1",
                "runtime_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "backend": backend, "exit_code": result.returncode, "error_code": error, "checks": checks,
                "isolation_verified": result.returncode == 0 and all(checks.values()),
                "real_account_certified": False, "account_calls_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=("unelevated", "elevated"), default="unelevated")
    args = parser.parse_args()
    report = probe(args.executable.resolve(), backend=args.backend)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["isolation_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
