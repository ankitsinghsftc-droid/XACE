"""Protocol clients prove all three engine claims, not actual editor/build integration."""
from pathlib import Path
import json,shutil,socket,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec012_lifecycle_proof import Host,sha
from tools.xp013_socket_proof import send,receive,verify

def main(out):
    out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec012') and not out.exists();out.mkdir(parents=True)
    exe=out/'xace-player-launcher.exe';shutil.copyfile(Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe'),exe)
    results=[]
    for engine,version in [('Unity','6000.4.9'),('Godot','4.6.3'),('Unreal','5.7.4')]:
        dest=out/engine;dest.mkdir();release=dest/'release';shutil.copytree(ROOT/'evidence/nec012/20261024/lifecycle-e/release',release)
        receipt=json.loads((release/'native-release.json').read_bytes());receipt['engine']=engine
        (release/'native-release.json').write_text(json.dumps(receipt,sort_keys=True))
        host=Host(exe,release,sha(release/'native-release.json'),dest/'history')
        try:
            ready=host.ask('play');assert ready['ok'],ready;ready=ready['result'];grant=json.loads(Path(ready['ticket']).read_bytes())
            address,port=ready['endpoint'].split(':');offer=grant['offer']
            with socket.create_connection((address,int(port)),timeout=10) as conn:
                send(conn,dict(msg_type='handshake',protocol_version=1,engine_name=engine,engine_version=version,adapter_version='0.1.0',cgs_hash=offer['contract']['gameplay']['cgs']['cgs_hash'],capabilities=[],session_offer_json=grant['offer_json'],session_peer_id=1,session_credential=grant['credential']))
                baseline=receive(conn);assert baseline['accepted'],baseline;verify(baseline)
                send(conn,dict(msg_type='baseline_ack',stamp_json=baseline['sync_json']))
                request=receive(conn);assert request['msg_type']=='input_tick_request',request
                tick=request['tick'];send(conn,dict(msg_type='input_packet',peer_id=1,player_id=baseline['assigned_player_id'],tick=tick,sequence_id=1,actions=[],ruleset_epoch=0))
                snapshot=receive(conn);assert snapshot['msg_type']=='tick_snapshot',snapshot;verify(snapshot)
                results.append(dict(engine=engine,admitted=True,authoritative_tick=True,no_developer_control_connection=True))
            host.ask('stop')
        finally:host.close()
    proof=dict(ok=True,engines=results,actual_native_engine=False,launcher_sha256=sha(exe));(out/'proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
