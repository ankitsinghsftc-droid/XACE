"""XP-012 two-peer socket, ownership, pacing, and arrival-order proof."""
from pathlib import Path
import argparse, json, socket, struct, subprocess, time, hashlib
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser()
ap.add_argument("--package",required=True)
ap.add_argument("--out",required=True)
args=ap.parse_args()
pkg=Path(args.package).resolve()
out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));return sock.getsockname()[1]
def receive(sock):
    def exact(n):
        b=b""
        while len(b)<n:
            chunk=sock.recv(n-len(b))
            if not chunk:raise EOFError("socket closed")
            b+=chunk
        return b
    n=struct.unpack("<I",exact(4))[0]
    return json.loads(exact(n))
def send(sock,value,fragment=False):
    body=json.dumps(value,separators=(",",":")).encode()
    frame=struct.pack("<I",len(body))+body
    if fragment:
        for part in (frame[:1],frame[1:3],frame[3:5],frame[5:17],frame[17:]):
            sock.sendall(part);time.sleep(.004)
    else:sock.sendall(frame)
def until(sock,kind):
    while True:
        msg=receive(sock)
        if "sync_json" in msg:
            assert hashlib.sha256(msg["projection_json"].encode()).hexdigest()==msg["sync"]["projection_digest"]
            send(sock,{"msg_type":"baseline_ack","stamp_json":msg["sync_json"]})
        if msg.get("msg_type")==kind:return msg
def run(name,order,stress=False,idle=False,quantize_probe=False):
    base=out/name;base.mkdir(exist_ok=True)
    port=free_port();ticket=base/"ticket.json";log=base/"session.jsonl"
    command=[str(pkg/"runtime/xace_runtime.exe"),"--cgs",str(pkg/"game.cgs.json"),
        "--sgc-plan",str(pkg/"execution_plan.json"),"--world",str(pkg/"world.json"),
        "--world-manifest",str(pkg/"world.manifest.json"),"--package-manifest",str(pkg/"playable.manifest.json"),
        "--session-ticket-out",str(ticket),"--session-log",str(log),
        "--session-controller-id","1,2","--input-lockstep-peer","1,2",
        "--port",str(port),"--engine-clients","2","--no-control","--live-session","--ticks","2","--quiet"]
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    clients=[]
    try:
        deadline=time.monotonic()+8
        while (not ticket.exists() or not (base/"ticket.peer2.json").exists()) and proc.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert ticket.exists(),proc.communicate(timeout=1)
        tickets=[json.loads(ticket.read_text()),json.loads((base/"ticket.peer2.json").read_text())]
        for _ in range(2):
            sock=socket.create_connection(("127.0.0.1",port),timeout=5);sock.settimeout(5);clients.append(sock)
        cgs=json.loads((pkg/"game.cgs.json").read_text())["metadata"]["cgs_hash"]
        for i,sock in enumerate(clients):
            grant=tickets[i]
            hello={"msg_type":"handshake","protocol_version":1,"engine_name":"Godot","engine_version":"4.x",
                "adapter_version":"0.1.0","cgs_hash":cgs,"capabilities":[],
                "session_offer_json":grant["offer_json"],"session_credential":grant["credential"],
                "session_peer_id":grant["peer_id"]}
            send(sock,hello,fragment=(i==0))
        acks=[until(sock,"handshake_ack") for sock in clients]
        assert all(ack["accepted"] for ack in acks),acks
        assert acks[0]["assigned_peer_id"]==1 and acks[1]["assigned_peer_id"]==2
        assert acks[0]["assigned_player_id"]!=acks[1]["assigned_player_id"]
        assert [until(sock,"input_tick_request")["tick"] for sock in clients]==[0,0]
        def packet(i,tick,seq,value,peer=None,player=None):
            return {"msg_type":"input_packet","peer_id":peer or i+1,"player_id":player or acks[i]["assigned_player_id"],
                "tick":tick,"sequence_id":seq,"actions":[] if idle else [{"action":"move_x","value":value,"kind":"axis_1d","phase":"changed"}]}
        send(clients[0],packet(0,0,1,1,peer=2))
        send(clients[0],packet(0,0,1,1,player=acks[1]["assigned_player_id"]))
        if not idle:
            targeted=packet(0,0,1,1)
            targeted["actions"][0]["target_entity"]=acks[1]["assigned_player_id"]
            send(clients[0],targeted)
        if stress:
            send(clients[0],packet(0,0,1,.5))
            for _ in range(40):send(clients[0],packet(0,0,1,1))
            send(clients[1],packet(1,0,1,-.5))
        else:
            for i in order:send(clients[i],packet(i,0,1,(.5003 if quantize_probe else .5) if i==0 else -.5),fragment=(i==0))
        snapshots=[until(sock,"tick_snapshot") for sock in clients]
        assert all(s["tick"]==0 for s in snapshots),snapshots
        assert snapshots[0]["entities"]==snapshots[1]["entities"]
        by_id={entity["id"]:entity for entity in snapshots[0]["entities"]}
        first=json.loads(by_id[acks[0]["assigned_player_id"]]["components"]["6"])
        second=json.loads(by_id[acks[1]["assigned_player_id"]]["components"]["6"])
        assert first["move_x"]==(0 if idle else .5) and second["move_x"]==(0 if idle else -.5),(first,second)
        assert first["peer_id"]==1 and second["peer_id"]==2,(first,second)
        first_tick_digest=hashlib.sha256(json.dumps({"tick":0,"entities":snapshots[0]["entities"],"events":snapshots[0]["events"]},sort_keys=True).encode()).hexdigest()
        if stress:
            time.sleep(.3)
            transcript=[json.loads(line) for line in log.read_text().splitlines()]
            decisions=[r for r in transcript if r.get("kind")=="input_validation"]
            rate_rejected=sum("rate limit" in r["reason"] for r in decisions)
            assert rate_rejected>=8,rate_rejected
            return {"players":[ack["assigned_player_id"] for ack in acks],
                "first_tick_digest":first_tick_digest,"rate_rejected":rate_rejected,"ticks":[0]}
        requests=[until(sock,"input_tick_request") for sock in clients]
        assert [r["tick"] for r in requests]==[1,1]
        send(clients[0],packet(0,0,1,1))
        send(clients[0],packet(0,100,2,1))
        for i in order:send(clients[i],packet(i,1,2,0))
        snapshots2=[until(sock,"tick_snapshot") for sock in clients]
        assert all(s["tick"]==1 for s in snapshots2),snapshots2
        assert snapshots2[0]["entities"]==snapshots2[1]["entities"]
        transcript=[json.loads(line) for line in log.read_text().splitlines()]
        admitted=[r for r in transcript if r.get("kind")=="membership" and r.get("action")=="admitted"]
        assert len(admitted)==2,transcript
        assert len({r["player_id"] for r in admitted})==2
        decisions=[r for r in transcript if r.get("kind")=="input_validation"]
        assert sum(r["decision"]=="accepted" for r in decisions)==4,decisions
        assert sum(r["decision"]=="rejected" for r in decisions)>=(2 if idle else 3),decisions
        if not idle:
            assert any("authority" in r["reason"].lower() for r in decisions),[r["reason"] for r in decisions]
        if stress:assert any("rate limit" in r["reason"] for r in decisions),[r["reason"] for r in decisions]
        state=[{"tick":s["tick"],"entities":s["entities"],"events":s["events"]} for s in [snapshots[0],snapshots2[0]]]
        return {"players":[ack["assigned_player_id"] for ack in acks],
            "state_digest":hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest(),
            "first_tick_digest":first_tick_digest,
            "input_records":len([r for r in transcript if r.get("kind")=="input"]),
            "rejected_inputs":sum(r["decision"]=="rejected" for r in decisions),
            "ticks":[s["tick"] for s in state]}
    finally:
        for sock in clients:sock.close()
        try:
            stdout,stderr=proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate();stdout,stderr=proc.communicate(timeout=5)
        if proc.returncode not in (0,None):
            print("runtime error",proc.returncode,stderr.decode(errors="replace"))
def input_timeout():
    base=out/"input_timeout";base.mkdir(exist_ok=True)
    port=free_port();ticket=base/"ticket.json";log=base/"session.jsonl"
    command=[str(pkg/"runtime/xace_runtime.exe"),"--cgs",str(pkg/"game.cgs.json"),
        "--sgc-plan",str(pkg/"execution_plan.json"),"--world",str(pkg/"world.json"),
        "--world-manifest",str(pkg/"world.manifest.json"),"--package-manifest",str(pkg/"playable.manifest.json"),
        "--session-ticket-out",str(ticket),"--session-log",str(log),
        "--session-controller-id","1","--input-lockstep-peer","1",
        "--port",str(port),"--no-control","--live-session","--ticks","1","--quiet"]
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    sock=None
    try:
        deadline=time.monotonic()+8
        while not ticket.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert ticket.exists(),proc.communicate(timeout=1)
        grant=json.loads(ticket.read_text())
        sock=socket.create_connection(("127.0.0.1",port),timeout=5);sock.settimeout(8)
        cgs=json.loads((pkg/"game.cgs.json").read_text())["metadata"]["cgs_hash"]
        send(sock,{"msg_type":"handshake","protocol_version":1,"engine_name":"Godot","engine_version":"4.x",
            "adapter_version":"0.1.0","cgs_hash":cgs,"capabilities":[],
            "session_offer_json":grant["offer_json"],"session_credential":grant["credential"],
            "session_peer_id":grant["peer_id"]})
        assert until(sock,"handshake_ack")["accepted"]
        assert until(sock,"input_tick_request")["tick"]==0
        start=time.monotonic()
        try:
            notice=until(sock,"disconnect")
        except Exception:
            proc.terminate()
            stdout,stderr=proc.communicate(timeout=5)
            print("timeout scenario stdout",stdout.decode(errors="replace"))
            print("timeout scenario stderr",stderr.decode(errors="replace"))
            raise
        elapsed=time.monotonic()-start
        assert notice["reason"]=="input_timeout",notice
        assert 4.5<=elapsed<=8,elapsed
        stdout,stderr=proc.communicate(timeout=5)
        assert proc.returncode==0,(stdout,stderr)
        records=[json.loads(line) for line in log.read_text().splitlines()]
        assert any(r.get("kind")=="membership" and r.get("reason")=="input_timeout" for r in records),records
        return {"logged_disconnect":True,"elapsed_seconds":round(elapsed,2)}
    finally:
        if sock:sock.close()
        if proc.poll() is None:
            proc.terminate()
            try:proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.communicate()

def slow_handshake():
    base=out/"slow_handshake";base.mkdir(exist_ok=True)
    port=free_port();ticket=base/"ticket.json";log=base/"session.jsonl"
    command=[str(pkg/"runtime/xace_runtime.exe"),"--cgs",str(pkg/"game.cgs.json"),
        "--sgc-plan",str(pkg/"execution_plan.json"),"--world",str(pkg/"world.json"),
        "--world-manifest",str(pkg/"world.manifest.json"),"--package-manifest",str(pkg/"playable.manifest.json"),
        "--session-ticket-out",str(ticket),"--session-log",str(log),
        "--session-controller-id","1","--input-lockstep-peer","1",
        "--port",str(port),"--no-control","--live-session","--live-engine-accept",
        "--no-wait","--start-paused","--quiet"]
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    slow=None;valid=None
    try:
        deadline=time.monotonic()+8
        while not ticket.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert ticket.exists(),proc.communicate(timeout=1)
        grant=json.loads(ticket.read_text())
        slow=socket.create_connection(("127.0.0.1",port),timeout=5)
        slow.sendall(b"\x7f")
        time.sleep(1.9)
        assert proc.poll() is None,"slow handshake killed authority"
        valid=socket.create_connection(("127.0.0.1",port),timeout=5);valid.settimeout(5)
        cgs=json.loads((pkg/"game.cgs.json").read_text())["metadata"]["cgs_hash"]
        send(valid,{"msg_type":"handshake","protocol_version":1,"engine_name":"Godot","engine_version":"4.x",
            "adapter_version":"0.1.0","cgs_hash":cgs,"capabilities":[],
            "session_offer_json":grant["offer_json"],"session_credential":grant["credential"],
            "session_peer_id":grant["peer_id"]})
        ack=until(valid,"handshake_ack")
        assert ack["accepted"],ack
        assert until(valid,"input_tick_request")["tick"]==0
        records=[json.loads(line) for line in log.read_text().splitlines()]
        assert any(r.get("kind")=="admission_rejected" and "handshake read failed" in r.get("reason","") for r in records),records
        assert any(r.get("kind")=="membership" and r.get("action")=="admitted" for r in records),records
        return {"slow_rejected":True,"subsequent_valid_admitted":True}
    finally:
        if slow:slow.close()
        if valid:valid.close()
        proc.terminate()
        try:proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.communicate()

results={"order_12":run("order_12",[0,1]),"order_21":run("order_21",[1,0],quantize_probe=True),
    "idle":run("idle",[0,1],idle=True),
    "rate_stress":run("rate_stress",[0,1],stress=True),"slow_handshake":slow_handshake(),"input_timeout":input_timeout()}
assert results["order_12"]["state_digest"]==results["order_21"]["state_digest"],results
assert results["idle"]["ticks"]==[0,1],results
assert len({r["first_tick_digest"] for key,r in results.items() if key not in ("idle","slow_handshake","input_timeout")})==1,results
proof={"schema":"xace.xp012.socket_proof.v1","ok":True,"results":results}
(out/"proof.json").write_text(json.dumps(proof,indent=2))
print(json.dumps(proof,indent=2))
