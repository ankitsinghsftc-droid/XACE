"""XP-011 real socket compatibility and admission matrix."""
from pathlib import Path
import argparse, copy, json, socket, struct, subprocess, time
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--package",required=True)
parser.add_argument("--out",required=True)
args=parser.parse_args()
PACKAGE=Path(args.package).resolve()
HOST=PACKAGE/"runtime/xace_runtime.exe"
OUT=Path(args.out).resolve()
OUT.mkdir(parents=True,exist_ok=True)
CGS=json.loads((PACKAGE/"game.cgs.json").read_text())["metadata"]["cgs_hash"]
OTHER="a"*64
def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]
def read_frame(sock):
    size=struct.unpack("<I",sock.recv(4))[0]
    data=b""
    while len(data)<size:
        data+=sock.recv(size-len(data))
    return json.loads(data)
def scenario(name,mutate=None,credential=None,engine="Godot",accept=False,omit_offer=False):
    base=OUT/name;base.mkdir(exist_ok=True)
    session_port=port()
    ticket=base/"ticket.json";log=base/"session.jsonl"
    command=[str(HOST),"--cgs",str(PACKAGE/"game.cgs.json"),"--sgc-plan",str(PACKAGE/"execution_plan.json"),
        "--world",str(PACKAGE/"world.json"),"--world-manifest",str(PACKAGE/"world.manifest.json"),
        "--package-manifest",str(PACKAGE/"playable.manifest.json"),"--session-ticket-out",str(ticket),
        "--session-log",str(log),"--session-controller-id","1","--port",str(session_port),
        "--no-control","--input-lockstep-peer","1","--live-session","--quiet"]
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline=time.monotonic()+8
        while not ticket.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert ticket.exists(),(name,proc.communicate(timeout=1))
        issued=json.loads(ticket.read_text())
        offer=copy.deepcopy(issued["offer"])
        if mutate:mutate(offer)
        hello={"msg_type":"handshake","protocol_version":1,"engine_name":engine,
            "engine_version":"4.x","adapter_version":"0.1.0","cgs_hash":CGS,
            "capabilities":[],"session_offer_json":json.dumps(offer,separators=(",",":")),
            "session_credential":credential if credential is not None else issued["credential"],
            "session_peer_id":issued["peer_id"]}
        if omit_offer:hello.pop("session_offer_json")
        with socket.create_connection(("127.0.0.1",session_port),timeout=5) as sock:
            sock.settimeout(5)
            raw=json.dumps(hello,separators=(",",":")).encode()
            sock.sendall(struct.pack("<I",len(raw))+raw)
            ack=read_frame(sock)
            if accept:
                baseline=json.dumps({"msg_type":"baseline_ack","stamp_json":ack["sync_json"]}).encode()
                sock.sendall(struct.pack("<I",len(baseline))+baseline)
                request=read_frame(sock)
                assert request["msg_type"]=="input_tick_request" and request["tick"]==0
                for peer,seq in [(1,1),(2,2)]:
                    packet={"msg_type":"input_packet","peer_id":peer,"tick":0,
                        "player_id":ack["assigned_player_id"],"sequence_id":seq,"actions":[]}
                    raw=json.dumps(packet,separators=(",",":")).encode()
                    sock.sendall(struct.pack("<I",len(raw))+raw)
                time.sleep(.3)
        assert ack["accepted"]==accept,(name,ack)
        if accept:
            assert ack["assigned_peer_id"]==1 and ack["assigned_player_id"]>0
            assert ack["session_id"]==issued["offer"]["contract"]["epoch"]["session_id"]
            assert ack["authority_incarnation"]==issued["offer"]["contract"]["epoch"]["authority_incarnation"]
        records=[json.loads(x) for x in log.read_text().splitlines()]
        assert records[0]["kind"]=="start"
        assert sum(r["kind"]=="membership" and r["action"]=="admitted" for r in records)==int(accept),(name,records)
        assert sum(r["kind"]=="admission_rejected" for r in records)==int(not accept),(name,records)
        assert sum(r["kind"]=="input" for r in records)==int(accept),(name,records)
        return {"accepted":accept,"reason":ack["reject_reason"],"records":[r["kind"] for r in records]}
    finally:
        proc.terminate()
        try:proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.communicate()
def change(path,value):
    def apply(offer):
        target=offer
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value
    return apply
results={}
results["godot"]=scenario("godot",accept=True)
results["unity_visual_variant"]=scenario("unity",lambda o:(o["client"]["adapter"].update(engine="unity"),o["client"].update(presentation_manifest_hash=OTHER)),engine="Unity",accept=True)
results["wrong_grant"]=scenario("wrong_grant",credential="invalid")
results["missing_projection_capability"]=scenario("missing_projection_capability",lambda o:o["client"]["capabilities"].remove("session.projection.v1"))
results["missing_offer"]=scenario("missing_offer",omit_offer=True)
results["adapter_claim_mismatch"]=scenario("adapter_claim_mismatch",engine="Unity")
results["incompatible_client_protocol"]=scenario("incompatible_client_protocol",change(["client","engine_protocol_version"],999))
results["incompatible_wire_protocol"]=scenario("incompatible_wire_protocol",change(["contract","gameplay","runtime","wire_protocol_version"],999))
results["stale_cgs"]=scenario("stale_cgs",lambda o:(o["contract"]["gameplay"]["cgs"].update(cgs_hash=OTHER),
    o["contract"]["gameplay"]["sgc"].update(compiled_from_cgs_hash=OTHER),
    o["contract"]["gameplay"]["world"].update(compiled_from_cgs_hash=OTHER)))
for label,path in [
    ("stale_plan",["contract","gameplay","sgc","plan_hash"]),
    ("stale_world",["contract","gameplay","world","artifact","content_hash"]),
    ("stale_input",["contract","gameplay","input","artifact","content_hash"]),
    ("stale_runtime",["contract","gameplay","runtime","artifact","content_hash"])
]:
    results[label]=scenario(label,change(path,OTHER))
results["stale_epoch"]=scenario("stale_epoch",change(["contract","epoch","ruleset_epoch"],1))
results["stale_incarnation"]=scenario("stale_incarnation",change(["contract","epoch","authority_incarnation"],"aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"))
assert results["godot"]["accepted"] and results["unity_visual_variant"]["accepted"]
assert all(not v["accepted"] for k,v in results.items() if k not in ("godot","unity_visual_variant"))
proof={"schema":"xace.xp011.session_proof.v1","ok":True,"scenarios":results}
(OUT/"proof.json").write_text(json.dumps(proof,indent=2))
print(json.dumps(proof,indent=2))
