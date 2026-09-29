"""Trusted isolated process worker. No project authority; MCP uses parent stdio.

This private execution transport is not an Agent or Builder protocol. It never
publishes a host port and never receives host credential-store contents.
"""
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import queue
import secrets
import socketserver
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_host.codex_linux_profile import profile_config, RUNTIME_SHA256, validate_profile_schema
from agent_host.codex_runtime_lifecycle import _probe_stable_app_server, _is_revoked

MAX_FRAME = 256 * 1024
output_lock = threading.Lock()
pending = {}
pending_lock = threading.Lock()
token = secrets.token_urlsafe(32)


def emit(channel, value, request_id=None):
    line = json.dumps({'channel':channel,'value':value,'id':request_id},separators=(',',':'))+'\n'
    if len(line) > MAX_FRAME: raise ValueError('execution frame too large')
    with output_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def read(stream):
    line = stream.readline(MAX_FRAME+1)
    if not line: return None
    if len(line)>MAX_FRAME or not line.endswith('\n'): raise ValueError('invalid execution frame')
    value = json.loads(line)
    if not isinstance(value,dict): raise ValueError('invalid execution object')
    return value


class Broker(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(60)
        reader = self.connection.makefile('r',encoding='utf8')
        writer = self.connection.makefile('w',encoding='utf8')
        try:
            auth = read(reader) or {}
            if not hmac.compare_digest(str(auth.get('token','')),token): return
            writer.write('{"ok":true}\n'); writer.flush()
            while True:
                envelope = read(reader)
                if envelope is None: return
                if not isinstance(envelope.get('message'),dict): return
                request_id = secrets.token_hex(16)
                reply = queue.Queue(maxsize=1)
                with pending_lock:
                    if len(pending)>=4: return
                    pending[request_id] = reply
                try:
                    emit('mcp',envelope['message'],request_id)
                    result = reply.get(timeout=60)
                    writer.write(json.dumps({'response':result})+'\n'); writer.flush()
                finally:
                    with pending_lock: pending.pop(request_id,None)
        except (OSError,ValueError,queue.Empty):
            return
        finally:
            reader.close(); writer.close()


def main():
    executable = '/opt/codex/package/vendor/x86_64-unknown-linux-musl/bin/codex'
    if os.getuid()==0 or hashlib.sha256(Path(executable).read_bytes()).hexdigest()!=RUNTIME_SHA256:
        raise RuntimeError('unverified execution runtime')
    security = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if security.get('NoNewPrivs','').strip()!='1' or int(security.get('CapEff','1').strip(),16)!=0 or security.get('Seccomp','').strip()!='2':
        raise RuntimeError('execution isolation unavailable')
    if _is_revoked('0.155.1',RUNTIME_SHA256): raise RuntimeError('runtime revoked')
    validate_profile_schema(_probe_stable_app_server(executable),str(Path(executable).parent.parent))
    broker = socketserver.ThreadingTCPServer(('127.0.0.1',0),Broker)
    broker.daemon_threads = True
    threading.Thread(target=broker.serve_forever,daemon=True).start()
    config = profile_config('',str(Path(executable).parent.parent))
    def toml(value):
        if isinstance(value,dict): return '{'+','.join(json.dumps(k)+'='+toml(v) for k,v in value.items())+'}'
        return json.dumps(value)
    arguments = [executable]
    for key,value in config.items(): arguments += ['-c',key+'='+toml(value)]
    env = {'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/provider','CODEX_HOME':'/provider',
           'LANG':'C.UTF-8','XACE_MCP_SESSION_TOKEN':token}
    child = subprocess.Popen([*arguments,'app-server','--strict-config'],cwd='/provider',env=env,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8')
    def provider_output():
        try:
            while True:
                value = read(child.stdout)
                if value is None: break
                emit('provider',value)
        finally:
            # A dead child must close the container channel, not hang auth/RPC.
            os._exit(0 if child.poll()==0 else 1)
    threading.Thread(target=provider_output,daemon=True).start()
    try:
        while True:
            frame = read(sys.stdin)
            if frame is None: break
            if frame.get('channel')=='mcp_response':
                with pending_lock: waiter = pending.get(frame.get('id'))
                if waiter is None: raise ValueError('unknown relay response')
                waiter.put_nowait(frame.get('value'))
                continue
            if frame.get('channel')!='provider' or not isinstance(frame.get('value'),dict):
                raise ValueError('unsupported execution frame')
            message = frame['value']
            params = message.get('params') or {}
            if message.get('method') in {'thread/start','thread/resume','thread/fork'}:
                servers = params.get('config',{}).get('mcp_servers',{})
                if set(servers)-{'xace'}: raise ValueError('foreign MCP server')
                if 'xace' in servers:
                    server = servers['xace']
                    server['command'] = '/usr/local/bin/python'
                    server['args'] = ['/xace/agent_host/mcp_stdio_proxy.py','--host','127.0.0.1','--port',str(broker.server_address[1])]
                    server['env_vars'] = ['XACE_MCP_SESSION_TOKEN']
            child.stdin.write(json.dumps(message)+'\n'); child.stdin.flush()
    finally:
        with contextlib.suppress(Exception): child.terminate(); child.wait(timeout=2)
        with contextlib.suppress(Exception): child.kill()
        broker.shutdown(); broker.server_close()


if __name__=='__main__':
    try: main()
    except Exception:
        print('Isolated execution failed; no operation was replayed.',file=sys.stderr)
        raise SystemExit(1)
