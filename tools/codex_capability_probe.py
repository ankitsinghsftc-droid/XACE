"""No-account native-runtime tool-catalog probe against a loopback fake model.

Not a certificate or production adapter: it tests what the real binary exposes
after disabling native capabilities in an empty provider home and capsule.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from codex_isolation_probe import ROOT, isolated_environment
sys.path.insert(0, str(ROOT / "packages/builder-workspace/server"))
from agent_host.codex_protocol import JsonRpcLineSession

DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "view_image", "image_generation",
    "apps", "plugins", "remote_plugin", "plugin_sharing", "hooks", "multi_agent",
    "multi_agent_v2", "browser_use", "browser_use_external", "computer_use", "in_app_browser",
    "in_app_local_automation", "code_mode", "code_mode_host", "memories", "goals",
    "skill_mcp_dependency_install", "skill_search", "tool_suggest", "workspace_dependencies",
    "enable_request_compression", "unbounded_connection_retries",
)


def probe(executable: Path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4 * 1024 * 1024:
                self.send_error(413); return
            value = json.loads(self.rfile.read(length))
            requests.append(value)
            body = ('event: response.created\ndata: {"type":"response.created","response":{"id":"probe","status":"in_progress","output":[]}}\n\n'
                    'event: response.completed\ndata: {"type":"response.completed","response":{"id":"probe","status":"completed","output":[],"usage":{"input_tokens":1,"output_tokens":0,"total_tokens":1}}}\n\n').encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="ag029-capabilities-", dir=ROOT / "tmp") as directory:
            root = Path(directory).resolve()
            home, capsule, temp = (root / name for name in ("provider", "capsule", "temp"))
            for p in (home, capsule, temp): p.mkdir()
            config = (
                'model = "gpt-5.4"\nmodel_provider = "probe"\napproval_policy = "never"\n'
                'sandbox_mode = "read-only"\nweb_search = "disabled"\n'
                '[analytics]\nenabled = false\n[feedback]\nenabled = false\n'
                '[features]\n' + ''.join(f'{name} = false\n' for name in DISABLED_FEATURES) +
                '[model_providers.probe]\nname = "XACE loopback probe"\nwire_api = "responses"\n'
                f'base_url = "http://127.0.0.1:{server.server_port}/v1"\nrequires_openai_auth = false\n')
            (home / "config.toml").write_text(config, encoding="utf8")
            diagnostic_file = (root / "runtime-stderr.txt").open("w", encoding="utf8")
            proc = subprocess.Popen([str(executable), "app-server", "--strict-config"], cwd=capsule,
                env=isolated_environment(home, temp), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=diagnostic_file, text=True, encoding="utf8")
            session = JsonRpcLineSession(proc, timeout_seconds=15)
            error = None
            try:
                print("probe: initialize", flush=True)
                session.request("initialize", {"clientInfo": {"name": "xace_isolation_probe", "version": "1"}})
                session.notify("initialized", {})
                print("probe: thread/start", flush=True)
                thread = session.request("thread/start", {"cwd": str(capsule), "model": "gpt-5.4",
                    "modelProvider": "probe", "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True})
                print("probe: turn/start", flush=True)
                session.request("turn/start", {"threadId": thread["thread"]["id"], "input": [{"type": "text", "text": "Synthetic isolation test. Reply OK."}]})
                end = time.monotonic() + 20
                while time.monotonic() < end:
                    event = session.read_notification(.5)
                    if event and event.get("method") == "turn/completed": break
            except Exception as exc:
                error = getattr(exc, "code", type(exc).__name__)
            finally:
                print("probe: close", flush=True)
                session.close()
                diagnostic_file.close()
                stderr = (root / "runtime-stderr.txt").read_text(encoding="utf8")
                print("probe: closed", flush=True)
            tools = requests[0].get("tools", []) if requests else []
            # Schemas and names are public capability metadata; prompt bodies and
            # environment/account values are never returned by this probe.
            return {"schema": "xace.codex_capability_probe.v1", "account_calls_performed": False,
                    "fake_model_requests": len(requests), "error_code": error,
                    "tools": tools, "runtime_diagnostic": stderr[-2000:] if not requests else "",
                    "isolation_certified": False}
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.executable.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report, indent=2))
