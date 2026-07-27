"""
Run XACE with Godot as the first official live-engine path.

What this starts:
- xace_runtime on port 7777 with control on 7778
- builder_server.py on port 8765
- Vite builder UI on port 5173
- Godot 4 project under adapters/godot

Stop everything with Ctrl+C in this terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = REPO_ROOT / "projects" / "zombie_chase"
PROJECT_SYSTEM = REPO_ROOT / "packages" / "project-system"
GODOT_PROJECT = REPO_ROOT / "adapters" / "godot"
RUNTIME_TARGET = REPO_ROOT / "target-codex-xace-godot-dev"
RUNTIME_BIN = RUNTIME_TARGET / "debug" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server" / "builder_server.py"
BUILDER_WORKSPACE = REPO_ROOT / "packages" / "builder-workspace"


def main() -> int:
    args = parse_args()
    project_dir = Path(args.project).resolve()
    cgs_path = project_dir / "game.cgs.json"
    ensure_project(project_dir, cgs_path, args.template, args.force_template)
    cgs_hash = load_cgs_hash(cgs_path)

    godot_bin = "" if args.no_godot else find_godot(args.godot_bin)
    runtime_bin = Path(args.runtime_bin).resolve() if args.runtime_bin else RUNTIME_BIN
    resolve_ports(args)

    godot_project_dir = Path(args.godot_project).resolve()
    commands = build_commands(args, project_dir, godot_project_dir, cgs_path, cgs_hash, runtime_bin, godot_bin)
    if args.dry_run:
        print_plan(commands, project_dir, godot_project_dir, cgs_hash, godot_bin)
        return 0

    if (not args.runtime_bin and args.build_runtime) or not runtime_bin.exists():
        run_checked([
            "cargo",
            "build",
            "-p",
            "xace-runtime-core",
            "--bin",
            "xace_runtime",
            "--target-dir",
            str(RUNTIME_TARGET),
        ], REPO_ROOT)

    processes: list[subprocess.Popen[Any]] = []
    try:
        print_banner(project_dir, godot_project_dir, cgs_hash, godot_bin)
        for label, command, cwd, env in commands:
            print(f"[xace] starting {label}: {' '.join(command)}")
            processes.append(subprocess.Popen(command, cwd=str(cwd), env=env))
            time.sleep(0.8 if label == "runtime" else 0.3)
        print("")
        print("XACE is running.")
        if not args.no_builder:
            print(f"Builder UI: http://localhost:{args.vite_port}")
            print(f"Builder API: http://localhost:{args.builder_port}")
        print(f"Godot should connect to runtime port {args.runtime_port}.")
        print("Press Ctrl+C here to stop everything.")
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise SystemExit(process.returncode or 0)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[xace] stopping...")
        return 0
    finally:
        stop_processes(processes)


def parse_args() -> argparse.Namespace:
    sys.path.insert(0, str(PROJECT_SYSTEM))
    from project_templates import list_template_ids  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Run XACE + Godot local dev loop.")
    parser.add_argument("--project", default=str(DEFAULT_PROJECT), help="XACE project directory.")
    parser.add_argument("--template", default="horror_chase", choices=list_template_ids(include_aliases=True))
    parser.add_argument("--force-template", action="store_true", help="Overwrite project/game.cgs.json.")
    parser.add_argument("--runtime-bin", default="", help="Existing xace_runtime binary to use.")
    parser.add_argument("--build-runtime", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--runtime-port", type=int, default=7777)
    parser.add_argument("--control-port", type=int, default=7778)
    parser.add_argument("--builder-port", type=int, default=8765)
    parser.add_argument("--vite-port", type=int, default=5173)
    parser.add_argument("--godot-bin", default="", help="Path to Godot executable.")
    parser.add_argument("--godot-project", default=str(GODOT_PROJECT), help="Godot project folder to launch.")
    parser.add_argument("--no-godot", action="store_true", help="Do not launch Godot; run headless.")
    parser.add_argument("--no-builder", action="store_true", help="Do not launch builder server/UI.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without starting them.")
    return parser.parse_args()


def resolve_ports(args: argparse.Namespace) -> None:
    args.runtime_port = available_port(args.runtime_port, "runtime")
    args.control_port = available_port(args.control_port, "runtime control")
    if not args.no_builder:
        args.builder_port = available_port(args.builder_port, "builder server")
        args.vite_port = available_port(args.vite_port, "builder UI")


def available_port(preferred: int, label: str) -> int:
    if preferred <= 0:
        chosen = reserve_free_port()
        print(f"[xace] {label} port auto-selected: {chosen}")
        return chosen
    if port_is_free(preferred):
        return preferred
    chosen = preferred + 1
    while chosen < preferred + 100:
        if port_is_free(chosen):
            print(f"[xace] {label} port {preferred} is busy; using {chosen}")
            return chosen
        chosen += 1
    raise SystemExit(f"No free port found for {label} near {preferred}")


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def reserve_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_project(project_dir: Path, cgs_path: Path, template: str, force: bool) -> None:
    if cgs_path.exists() and not force:
        return
    sys.path.insert(0, str(PROJECT_SYSTEM))
    from project_creator import CreateProjectRequest, ProjectCreator  # noqa: PLC0415

    default_name = "Zombie Chase" if template in {"zombie_chase", "horror_chase"} else "XACE Project"
    ProjectCreator().create_project(CreateProjectRequest(
        project_dir=str(project_dir),
        name=default_name,
        engine_type="godot",
        template_id=template,
        force=True,
    ))


def load_cgs_hash(cgs_path: Path) -> str:
    with cgs_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return str(data.get("metadata", {}).get("cgs_hash", ""))


def find_godot(explicit: str) -> str:
    if explicit:
        return str(Path(explicit).resolve())
    env_bin = os.environ.get("GODOT_BIN", "")
    if env_bin:
        return env_bin
    for name in ["godot", "godot4", "Godot", "Godot_v4.3-stable_win64.exe", "Godot_v4.2-stable_win64.exe"]:
        found = shutil.which(name)
        if found:
            return found
    for root in [Path("C:/Program Files"), Path.home() / "Downloads"]:
        if not root.exists():
            continue
        matches = [match for match in root.rglob("Godot*.exe") if match.is_file()]
        console_matches = [match for match in matches if match.name.endswith("_console.exe")]
        if console_matches:
            return str(console_matches[0])
        if matches:
            return str(matches[0])
    return ""


def build_commands(
    args: argparse.Namespace,
    project_dir: Path,
    godot_project_dir: Path,
    cgs_path: Path,
    cgs_hash: str,
    runtime_bin: Path,
    godot_bin: str,
) -> list[tuple[str, list[str], Path, dict[str, str] | None]]:
    commands: list[tuple[str, list[str], Path, dict[str, str] | None]] = []
    runtime_command = [
        str(runtime_bin),
        "--cgs",
        str(cgs_path),
        "--port",
        str(args.runtime_port),
        "--control-port",
        str(args.control_port),
        "--start-paused",
    ]
    if args.no_godot:
        runtime_command.append("--no-wait")
    commands.append(("runtime", runtime_command, REPO_ROOT, None))

    if not args.no_builder:
        commands.append((
            "builder server",
            [
                sys.executable,
                str(BUILDER_SERVER),
                "--project",
                str(project_dir),
                "--dev",
                "--port",
                str(args.builder_port),
                "--runtime-control-port",
                str(args.control_port),
                "--model-provider",
                "auto",
            ],
            REPO_ROOT,
            None,
        ))
        vite_env = os.environ.copy()
        vite_env["VITE_WS_URL"] = f"ws://localhost:{args.builder_port}/ws"
        vite_env["VITE_BUILDER_PORT"] = str(args.builder_port)
        vite_env["VITE_PROJECT_ID"] = str(project_dir)
        commands.append((
            "builder UI",
            ["npm.cmd" if os.name == "nt" else "npm", "run", "dev", "--", "--port", str(args.vite_port)],
            BUILDER_WORKSPACE,
            vite_env,
        ))

    if not args.no_godot:
        if not godot_bin:
            raise SystemExit(
                "Godot executable not found. Pass --godot-bin C:/path/to/Godot.exe "
                "or set GODOT_BIN."
            )
        commands.append((
            "godot",
            [
                godot_bin,
                "--path",
                str(godot_project_dir),
                "--",
                f"--xace-host=127.0.0.1",
                f"--xace-port={args.runtime_port}",
                f"--xace-cgs-hash={cgs_hash}",
            ],
            godot_project_dir,
            None,
        ))
    return commands


def print_plan(
    commands: list[tuple[str, list[str], Path, dict[str, str] | None]],
    project_dir: Path,
    godot_project_dir: Path,
    cgs_hash: str,
    godot_bin: str,
) -> None:
    print_banner(project_dir, godot_project_dir, cgs_hash, godot_bin)
    for label, command, cwd, _env in commands:
        print(f"[{label}] cwd={cwd}")
        print(" ".join(command))


def print_banner(project_dir: Path, godot_project_dir: Path, cgs_hash: str, godot_bin: str) -> None:
    print("=" * 64)
    print("XACE Godot Dev Loop")
    print(f"XACE project: {project_dir}")
    print(f"Godot project: {godot_project_dir}")
    print(f"CGS hash: {cgs_hash}")
    print(f"Godot: {godot_bin or 'not found'}")
    print("=" * 64)


def run_checked(command: list[str], cwd: Path) -> None:
    print(f"[xace] {' '.join(command)}")
    subprocess.run(command, cwd=str(cwd), check=True)


def stop_processes(processes: list[subprocess.Popen[Any]]) -> None:
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        process.terminate()
    deadline = time.monotonic() + 5.0
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        remaining = max(0.1, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
