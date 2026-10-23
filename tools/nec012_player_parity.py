"""Same-machine Player regression using a fresh copy of the recovered release."""
from pathlib import Path
import hashlib,json,shutil,sys,zipfile,socket
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.xp010_launch_proof import Native,stopped,reseal

def main(out):
    out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec012') and not out.exists();out.mkdir(parents=True)
    source=Path('C:/Users/ankit/XACE-Recovery/baselines/xp022-recovered-20261015/unsigned-release.zip')
    release=out/'release';release.mkdir()
    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            path=release/name;assert path.resolve().is_relative_to(release)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(name))
    shutil.copyfile(Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe'),release/'XACE Play.exe')
    expected=reseal(release);native=None
    try:
        native=Native(release,out/'install',expected);assert native.hello['state']=='ready',native.hello
        assert not native.request('play',capability='wrong')['ok']
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen();port=occupied.getsockname()[1]
            reply=native.request('play',preferred_port=port);assert reply['ok'],reply
            first=reply['result'];assert native.request('play')['result']['player_pid']==first['player_pid']
            assert native.request('stop')['ok'];stopped(first['player_pid'],first['runtime_pid'])
        reply=native.request('play');assert reply['ok'],reply
        running=reply['result'];native.close();native=None;stopped(running['player_pid'],running['runtime_pid'])
        report=dict(ok=True,existing_player_ready=True,capability_refusal=True,repeated_play_same_player=True,stop_and_eof_owned_cleanup=True,original_zip_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),new_launcher_sha256=hashlib.sha256((release/'XACE Play.exe').read_bytes()).hexdigest(),original_seal_modified=False,clean_machine=False)
        (out/'proof.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
    finally:
        if native:native.close()
if __name__=='__main__':main(Path(sys.argv[1]))
