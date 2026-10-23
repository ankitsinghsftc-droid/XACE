"""Actual native readiness update/refusal/rollback, create-only fixtures."""
from pathlib import Path
import hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec012_lifecycle_proof import Host,sha

def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
def main(out):
    out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec012') and not out.exists();out.mkdir(parents=True)
    original=ROOT/'evidence/nec012/20261024/lifecycle-e'
    exe=out/'xace-player-launcher.exe';shutil.copyfile(Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe'),exe)
    release_a=out/'release-a';shutil.copytree(original/'release',release_a)
    receipt=json.loads((release_a/'native-release.json').read_bytes())
    release_b=out/'release-b';release_b.mkdir()
    shutil.copytree(ROOT/'evidence/nec011/20261023/godot-input-authority-f/replacement/package',release_b/'package')
    shutil.copyfile(release_a/'executor-receipt.json',release_b/'executor-receipt.json')
    receipt['package_manifest_sha256']=sha(release_b/'package/playable.manifest.json');(release_b/'native-release.json').write_bytes(encode(receipt))
    history=out/'history';host=None
    try:
        host=Host(exe,release_a,sha(release_a/'native-release.json'),history)
        identity=host.initial['save_identity'];save_root=host.initial['save_root']
        assert host.ask('play')['ok'];assert host.ask('stop')['ok'];host.close();host=None
        state=out/'user-data/XACE/NativeGames/game-nec012-proof/release-state'
        prior=(state/'active.json').read_bytes()
        host=Host(exe,release_b,sha(release_b/'native-release.json'),history)
        assert host.initial['save_identity']==identity and host.initial['save_root']==save_root
        assert host.ask('play')['ok'];assert host.ask('stop')['ok'];host.close();host=None
        working=(state/'active.json').read_bytes();assert working!=prior
        assert any(p.read_bytes()==prior for p in state.glob('previous-*.json'))
        # Trusted, byte-complete candidate whose authoritative World is incompatible.
        broken=out/'release-invalid-world';shutil.copytree(release_b,broken)
        world=broken/'package/world.json';world.write_bytes(b'{}')
        manifest_path=broken/'package/playable.manifest.json';manifest=json.loads(manifest_path.read_bytes())
        for row in manifest['files']:
            if row['path']=='world.json':row.update(sha256=sha(world),size=2)
        manifest.pop('package_content_hash');manifest['package_content_hash']=hashlib.sha256(encode(manifest)).hexdigest();manifest_path.write_bytes(encode(manifest))
        receipt['package_manifest_sha256']=sha(manifest_path);(broken/'native-release.json').write_bytes(encode(receipt))
        host=Host(exe,broken,sha(broken/'native-release.json'),history);assert host.initial['state']=='stopped',host.initial
        assert host.ask('verify')['ok'];failure=host.ask('play');assert not failure['ok'],failure
        assert (state/'active.json').read_bytes()==working;host.close();host=None
        host=Host(exe,release_a,sha(release_a/'native-release.json'),history)
        assert host.ask('play')['ok'];host.ask('stop');host.close();host=None
        assert (state/'active.json').read_bytes()==prior
        result=dict(ok=True,valid_cosmetic_update=True,same_save_identity_and_namespace=True,previous_receipt_retained=True,admitted_but_unready_update_refused=True,working_pointer_unchanged_on_failure=True,explicit_rollback_to_retained_release=True,failure=failure,launcher_sha256=sha(exe),full_installer=False)
        (out/'proof.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:
        if host:host.close()
if __name__=='__main__':main(Path(sys.argv[1]))
