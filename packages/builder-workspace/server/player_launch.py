"""Local Player orchestration. No project-provided executable paths are accepted."""
import hashlib,json,os,queue,secrets,subprocess,threading
from pathlib import Path

class PlayerLaunchService:
    def __init__(self,load_project,*,release=None,expected=None,broker_digest=None,install=None,headless=False):
        self.load_project=load_project
        self.release=Path(release or os.environ.get("XACE_PLAYER_RELEASE",""))
        self.expected=expected or os.environ.get("XACE_PLAYER_RELEASE_SHA256","")
        self.broker_digest=broker_digest or os.environ.get("XACE_PLAYER_BROKER_SHA256","")
        self.install=Path(install or Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"XACE"/"BuilderPlayer")
        self.capability=secrets.token_urlsafe(32);self.headless=headless
        self.explicit_release=bool(release or os.environ.get("XACE_PLAYER_RELEASE"))
        self.launched_digest=""
        self.process=None;self.broker_capability="";self.messages=queue.Queue();self.lock=threading.Lock()
    def _validate(self,expected_cgs,*,check_project=True):
        if not self.explicit_release:
            registry=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"XACE"/"Player"
            try:
                active=json.loads((registry/"active.json").read_text())
                digest=active["version_digest"]
                if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):raise ValueError()
                root=registry/"versions"/digest
                raw=(root/"distribution.json").read_bytes()
                if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError()
                manifest=json.loads(raw)
                broker=next(row for row in manifest["files"] if row["path"]=="XACE Play.exe")
                self.release=root;self.expected=digest;self.broker_digest=broker["sha256"]
            except (OSError,ValueError,KeyError,StopIteration):
                raise ValueError("Open XACE Play from your trusted download once, then Retry here.")
        if not self.expected or not self.broker_digest:
            raise ValueError("Player is not installed. Configure a trusted Player release, then Retry.")
        raw=(self.release/"distribution.json").read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.expected:raise ValueError("Player release changed. Restore the verified release and Retry.")
        distribution=json.loads(raw)
        executable=self.release/"XACE Play.exe"
        if hashlib.sha256(executable.read_bytes()).hexdigest()!=self.broker_digest:raise ValueError("Player launcher changed. Restore the verified release and Retry.")
        project=self.load_project()
        packaged=json.loads((self.release/"package/game.cgs.json").read_text(encoding="utf8"))
        if check_project and (project!=packaged or project.get("metadata",{}).get("cgs_hash")!=expected_cgs or distribution["cgs_hash"]!=expected_cgs):
            raise ValueError("This Player package is older than your saved game. Publish an updated package, then Retry.")
        return executable
    def _read(self,timeout=25):
        try:value=self.messages.get(timeout=timeout)
        except queue.Empty:raise ValueError("Player did not respond. Retry the launch.")
        if value is None:raise ValueError("Player launcher stopped. Retry the launch.")
        return value
    def _start(self,executable):
        self.messages=queue.Queue()
        args=[str(executable),"--source",str(self.release.resolve()),"--expected",self.expected,"--install",str(self.install.resolve()),"--serve"]
        if self.headless:args.append("--headless-player")
        self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        stream=self.process.stdout;messages=self.messages
        def reader():
            try:
                for line in stream:
                    if len(line)>32768:break
                    messages.put(json.loads(line))
            except (ValueError,OSError):pass
            finally:messages.put(None)
        threading.Thread(target=reader,daemon=True).start()
        hello=self._read()
        if hello.get("schema")!="xace.player.broker_ready.v1":raise ValueError(hello.get("message","Player could not be prepared."))
        self.broker_capability=hello["capability"]
        self.launched_digest=self.expected
    def _request(self,action,code=""):
        self.process.stdin.write(json.dumps({"schema":"xace.player.broker_request.v1","capability":self.broker_capability,"action":action,**({"code":code} if action=="join" else {})})+"\n");self.process.stdin.flush()
        response=self._read(timeout=150 if action=="join" else 25)
        if not response.get("ok"):raise ValueError(response.get("message","Player action failed. Retry."))
        return response["result"]
    def control(self,action,expected_cgs="",code=""):
        with self.lock:
            # Validation happens before touching an existing healthy process.
            executable=self._validate(expected_cgs,check_project=action=="play") if action in {"play","join"} else None
            if action not in {"play","stop","status","invite","join"}:raise ValueError("Unknown Player action")
            if action in {"play","join"} and self.process is not None and self.process.poll() is None and self.launched_digest!=self.expected:
                if self._request("status")["state"]=="playing":raise ValueError("Close the current game, then Retry the updated package.")
                self._close()
            try:
                if action in {"play","join"} and (self.process is None or self.process.poll() is not None):
                    self._close()
                    self._start(executable)
                if self.process is None or self.process.poll() is not None:return {"state":"stopped"}
                return self._request(action,code)
            except (ValueError,OSError):
                if action not in {"invite","join"} or self.process is None or self.process.poll() is not None:self._close()
                raise
    def _close(self):
        if self.process is not None:
            if self.process.stdin:
                try:self.process.stdin.close()
                except OSError:pass
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            if self.process.stdout:self.process.stdout.close()
            self.process=None
    def close(self):
        with self.lock:self._close()
