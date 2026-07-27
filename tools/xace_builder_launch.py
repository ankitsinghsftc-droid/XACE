"""
Start XACE Builder with one command.

This launcher is the local product-style wrapper around the Builder backend,
the built Builder UI, and the optional live runtime. A packaged desktop shell
can wrap the same behavior later.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_SERVER = REPO_ROOT / "packages" / "builder-workspace" / "server" / "builder_server.py"
BUILDER_WORKSPACE = REPO_ROOT / "packages" / "builder-workspace"
PROJECT_SYSTEM = REPO_ROOT / "packages" / "project-system"
STATIC_DIR = REPO_ROOT / "packages" / "builder-server" / "dist"
LAUNCHER_TARGET = REPO_ROOT / "target-xace-launcher"
RUNTIME_BIN = LAUNCHER_TARGET / "debug" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime")
STATE_ENV = "XACE_LAUNCHER_STATE"
REQUIRED_RUNTIME_FLAGS = (
    "--engine-clients",
    "--control-port",
    "--live-engine-accept",
    "--start-paused",
)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state_file = resolve_state_file(args)
    project_dir = resolve_project_dir(args, state_file)
    builder_port, control_port, runtime_port, vite_port = resolve_ports(args)
    log_dir = resolve_log_dir(args, state_file)
    runtime_bin = resolve_runtime_bin(args)

    if args.ui_build in {"auto", "always"} and not args.dev_ui:
        if args.ui_build == "always" or not (STATIC_DIR / "index.html").exists():
            if args.dry_run:
                print_command("build Builder UI", npm_command() + ["run", "build"], BUILDER_WORKSPACE)
            else:
                run_checked("build Builder UI", npm_command() + ["run", "build"], BUILDER_WORKSPACE)
    if not args.dev_ui and not (STATIC_DIR / "index.html").exists() and args.ui_build == "never":
        raise SystemExit("Built Builder UI was not found. Run without --ui-build never, or use --dev-ui.")

    runtime_ready = runtime_supports_launcher_args(runtime_bin) if args.runtime else True
    if args.runtime and (args.runtime_build == "always" or not runtime_ready):
        if args.runtime_build == "never":
            raise SystemExit(
                "xace_runtime is missing or too old for live Builder launch. "
                "Enable runtime build, use a newer --runtime-bin, or start with --no-runtime."
            )
        if args.dry_run:
            print_command(
                "build runtime",
                [
                    "cargo",
                    "build",
                    "-p",
                    "xace-runtime-core",
                    "--bin",
                    "xace_runtime",
                    "--target-dir",
                    str(LAUNCHER_TARGET),
                ],
                REPO_ROOT,
            )
        else:
            run_checked(
                "build runtime",
                [
                    "cargo",
                    "build",
                    "-p",
                    "xace-runtime-core",
                    "--bin",
                    "xace_runtime",
                    "--target-dir",
                    str(LAUNCHER_TARGET),
                ],
                REPO_ROOT,
            )
        runtime_bin = RUNTIME_BIN
        if not args.dry_run and not runtime_supports_launcher_args(runtime_bin):
            raise SystemExit(
                f"Built runtime is not compatible with the Builder launcher: {runtime_bin}"
            )

    plan = build_launch_plan(args, project_dir, state_file, runtime_bin, builder_port, control_port, runtime_port, vite_port)
    url = f"http://127.0.0.1:{vite_port}" if args.dev_ui else f"http://127.0.0.1:{builder_port}"

    if args.dry_run:
        print_banner(project_dir, url, log_dir, state_file)
        for item in plan:
            print_command(item["label"], item["command"], item["cwd"])
        return 0

    log_dir.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[Any]] = []
    log_handles: list[Any] = []
    try:
        print_banner(project_dir, url, log_dir, state_file)
        for item in plan:
            log_path = log_dir / f"{item['name']}.log"
            print(f"[xace] starting {item['label']}")
            print(f"[xace] log: {log_path}")
            handle = log_path.open("w", encoding="utf-8")
            log_handles.append(handle)
            process = subprocess.Popen(
                item["command"],
                cwd=str(item["cwd"]),
                env=item.get("env"),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            processes.append(process)
            time.sleep(float(item.get("settle_seconds", 0.4)))

        wait_for_http(f"http://127.0.0.1:{builder_port}/api/project", timeout_seconds=30.0)
        if args.dev_ui:
            wait_for_http(url, timeout_seconds=30.0)

        if args.open_browser:
            webbrowser.open(url, new=2)

        print("")
        print("XACE Builder is running.")
        print(f"Open this in your browser: {url}")
        print(f"Active project: {project_dir}")
        if args.runtime:
            print(f"Runtime control: 127.0.0.1:{control_port}")
        print("Close this window or press Ctrl+C here to stop XACE.")

        while True:
            for index, process in enumerate(processes):
                code = process.poll()
                if code is not None:
                    label = plan[index]["label"]
                    print(f"[xace] {label} stopped with code {code}.")
                    return int(code or 0)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[xace] stopping...")
        return 0
    finally:
        stop_processes(processes)
        for handle in log_handles:
            try:
                handle.close()
            except OSError:
                pass


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start XACE Builder, UI, and optional runtime.")
    parser.add_argument("--project", default="", help="XACE project folder to open.")
    parser.add_argument("--host", default="127.0.0.1", help="Builder server bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Builder server port.")
    parser.add_argument("--strict-port", action="store_true", help="Fail instead of choosing the next free port.")
    parser.add_argument("--runtime-port", type=int, default=7777, help="Runtime engine bridge port.")
    parser.add_argument("--runtime-control-port", type=int, default=7778, help="Runtime control port.")
    parser.add_argument("--vite-port", type=int, default=5173, help="Vite dev UI port when --dev-ui is used.")
    parser.add_argument("--dev-ui", action="store_true", help="Use Vite dev server instead of built UI.")
    parser.add_argument("--open-browser", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--runtime", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--runtime-bin", default="", help="Existing xace_runtime binary to use.")
    parser.add_argument("--runtime-build", choices=["auto", "always", "never"], default="auto")
    parser.add_argument("--ui-build", choices=["auto", "always", "never"], default="auto")
    parser.add_argument(
        "--model-provider",
        choices=["auto", "ollama", "anthropic", "openai", "google", "moonshot"],
        default="auto",
    )
    parser.add_argument("--model", default="", help="Model name for the Builder prompt provider.")
    parser.add_argument(
        "--api-key",
        default="",
        help="Hosted provider API key. Stored in local machine settings outside project files.",
    )
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--sgc-bin", default="", help="Optional System Graph Compiler binary.")
    parser.add_argument("--state-file", default="", help="Launcher state file. Defaults to ~/.xace/launcher_state.json.")
    parser.add_argument("--log-dir", default="", help="Folder for launcher logs. Defaults next to launcher state.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would start without launching anything.")
    return parser.parse_args(argv)


def resolve_state_file(args: argparse.Namespace) -> Path:
    if args.state_file:
        return Path(args.state_file).expanduser().resolve()
    return (Path.home() / ".xace" / "launcher_state.json").resolve()


def resolve_log_dir(args: argparse.Namespace, state_file: Path) -> Path:
    if args.log_dir:
        return Path(args.log_dir).expanduser().resolve()
    return state_file.parent / "logs"


def resolve_project_dir(args: argparse.Namespace, state_file: Path) -> Path:
    explicit = str(args.project or os.environ.get("XACE_PROJECT", "")).strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    remembered = read_remembered_project(state_file)
    if remembered and is_launchable_project_candidate(remembered):
        return remembered

    cwd = Path.cwd().resolve()
    if is_launchable_project_candidate(cwd):
        return cwd

    starter = default_starter_project_dir()
    if is_xace_project(starter):
        return starter
    if args.dry_run:
        return starter.resolve()
    return create_starter_project(starter)


def read_remembered_project(state_file: Path) -> Path | None:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(data.get("last_project") or "").strip() if isinstance(data, dict) else ""
    if not value:
        return None
    return Path(value).expanduser().resolve()


def is_xace_project(path: Path) -> bool:
    return (path / "xace.project.json").exists() or (path / "game.cgs.json").exists()


def is_launchable_project_candidate(path: Path) -> bool:
    resolved = path.resolve()
    if resolved == REPO_ROOT:
        return False
    return is_xace_project(resolved)


def project_cgs_path(project_dir: Path) -> Path:
    manifest_path = project_dir / "xace.project.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            cgs_path = str(data.get("cgs_path") or "game.cgs.json")
            return (project_dir / cgs_path).resolve()
        except (OSError, json.JSONDecodeError):
            pass
    return (project_dir / "game.cgs.json").resolve()


def default_starter_project_dir() -> Path:
    documents = Path.home() / "Documents"
    root = documents if documents.exists() else Path.home()
    return root / "XACE Projects" / "Starter Project"


def create_starter_project(project_dir: Path) -> Path:
    sys.path.insert(0, str(PROJECT_SYSTEM))
    from project_creator import CreateProjectRequest, ProjectCreator  # noqa: PLC0415

    ProjectCreator().create_project(CreateProjectRequest(
        project_dir=str(project_dir),
        name="XACE Starter Project",
        engine_type="godot",
        template_id="blank_3d",
        force=False,
    ))
    return project_dir.resolve()


def resolve_ports(args: argparse.Namespace) -> tuple[int, int, int, int]:
    used: set[int] = set()
    builder_port = choose_port(args.port, "Builder", args.strict_port, used)
    used.add(builder_port)
    control_port = choose_port(args.runtime_control_port, "runtime control", args.strict_port, used)
    used.add(control_port)
    runtime_port = choose_port(args.runtime_port, "runtime", args.strict_port, used)
    used.add(runtime_port)
    vite_port = choose_port(args.vite_port, "Builder dev UI", args.strict_port, used) if args.dev_ui else args.vite_port
    return builder_port, control_port, runtime_port, vite_port


def choose_port(preferred: int, label: str, strict: bool, used: set[int]) -> int:
    if preferred <= 0:
        chosen = reserve_free_port(used)
        print(f"[xace] {label} port selected: {chosen}")
        return chosen
    if preferred not in used and port_is_free(preferred):
        return preferred
    if strict:
        raise SystemExit(f"{label} port {preferred} is busy. Close the other app or choose another port.")
    candidate = preferred + 1
    while candidate < preferred + 100:
        if candidate not in used and port_is_free(candidate):
            print(f"[xace] {label} port {preferred} is busy; using {candidate}.")
            return candidate
        candidate += 1
    raise SystemExit(f"No free {label} port found near {preferred}.")


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def reserve_free_port(used: set[int]) -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in used:
            return port


def resolve_runtime_bin(args: argparse.Namespace) -> Path:
    candidates: list[Path] = []
    if args.runtime_bin:
        candidates.append(Path(args.runtime_bin).expanduser())
    env_runtime = os.environ.get("XACE_RUNTIME_BIN", "").strip()
    if env_runtime:
        candidates.append(Path(env_runtime).expanduser())
    candidates.append(RUNTIME_BIN)

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved

    fallback_candidates = [
        RUNTIME_BIN,
        REPO_ROOT / "target" / "debug" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime"),
        REPO_ROOT / "target" / "release" / ("xace_runtime.exe" if os.name == "nt" else "xace_runtime"),
    ]
    for candidate in fallback_candidates:
        resolved = candidate.resolve()
        if resolved.exists() and runtime_supports_launcher_args(resolved):
            return resolved
    return Path(args.runtime_bin).expanduser().resolve() if args.runtime_bin else RUNTIME_BIN


def runtime_supports_launcher_args(runtime_bin: Path) -> bool:
    if not runtime_bin.exists():
        return False
    try:
        completed = subprocess.run(
            [str(runtime_bin), "--help"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    help_text = completed.stdout or ""
    return all(flag in help_text for flag in REQUIRED_RUNTIME_FLAGS)


def build_launch_plan(
    args: argparse.Namespace,
    project_dir: Path,
    state_file: Path,
    runtime_bin: Path,
    builder_port: int,
    control_port: int,
    runtime_port: int,
    vite_port: int,
) -> list[dict[str, Any]]:
    env = os.environ.copy()
    env[STATE_ENV] = str(state_file)

    plan: list[dict[str, Any]] = []
    cgs_path = project_cgs_path(project_dir)
    if args.runtime:
        plan.append({
            "name": "runtime",
            "label": "XACE runtime",
            "command": [
                str(runtime_bin),
                "--cgs",
                str(cgs_path),
                "--port",
                str(runtime_port),
                "--engine-clients",
                "3",
                "--control-port",
                str(control_port),
                "--no-wait",
                "--live-engine-accept",
                "--start-paused",
                "--quiet",
            ],
            "cwd": REPO_ROOT,
            "env": env,
            "settle_seconds": 0.8,
        })

    server_command = [
        sys.executable,
        str(BUILDER_SERVER),
        "--project",
        str(project_dir),
        "--host",
        args.host,
        "--port",
        str(builder_port),
        "--static-dir",
        str(STATIC_DIR),
        "--runtime-control-port",
        str(control_port),
        "--model-provider",
        args.model_provider,
        "--ollama-url",
        args.ollama_url,
    ]
    if args.dev_ui:
        server_command.append("--dev")
    if args.model:
        server_command.extend(["--model", args.model])
    if args.api_key:
        server_command.extend(["--api-key", args.api_key])
    if args.sgc_bin:
        server_command.extend(["--sgc-bin", args.sgc_bin])

    plan.append({
        "name": "builder_server",
        "label": "Builder server",
        "command": server_command,
        "cwd": REPO_ROOT,
        "env": env,
        "settle_seconds": 0.6,
    })

    if args.dev_ui:
        vite_env = env.copy()
        vite_env["VITE_WS_URL"] = f"ws://127.0.0.1:{builder_port}/ws"
        vite_env["VITE_BUILDER_PORT"] = str(builder_port)
        vite_env["VITE_PROJECT_ID"] = str(project_dir)
        plan.append({
            "name": "builder_ui",
            "label": "Builder UI dev server",
            "command": npm_command() + ["run", "dev", "--", "--host", "127.0.0.1", "--port", str(vite_port)],
            "cwd": BUILDER_WORKSPACE,
            "env": vite_env,
            "settle_seconds": 0.5,
        })
    return plan


def npm_command() -> list[str]:
    return ["npm.cmd" if os.name == "nt" else "npm"]


def run_checked(label: str, command: list[str], cwd: Path) -> None:
    print_command(label, command, cwd)
    subprocess.run(command, cwd=str(cwd), check=True)


def print_command(label: str, command: list[str], cwd: Path) -> None:
    print(f"[{label}] cwd={cwd}")
    print(" ".join(command))


def wait_for_http(url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            request = Request(url, headers={"User-Agent": "xace-launcher"})
            with urlopen(request, timeout=2.0) as response:
                if 200 <= int(response.status) < 500:
                    return
        except (OSError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}. {last_error}")


def stop_processes(processes: list[subprocess.Popen[Any]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 6.0
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        remaining = max(0.1, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()


def print_banner(project_dir: Path, url: str, log_dir: Path, state_file: Path) -> None:
    print("=" * 64)
    print("XACE Builder Launcher")
    print(f"Project: {project_dir}")
    print(f"Open:    {url}")
    print(f"Logs:    {log_dir}")
    print(f"Memory:  {state_file}")
    print("=" * 64)


if __name__ == "__main__":
    raise SystemExit(main())
