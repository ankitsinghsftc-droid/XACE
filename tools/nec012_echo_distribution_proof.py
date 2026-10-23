"""Rust admission plus relocated custom mechanic checkpoint/replay; bounded CLI profile."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.nec011_echo_session_proof import prove

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main(out):
    out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec012') and not out.exists();out.mkdir(parents=True)
    original=ROOT/'evidence/nec011/20261021/distribution-player-a'
    release=out/'relocated';release.mkdir();shutil.copytree(original/'relocated-game',release/'package')
    shutil.copyfile(original/'executor-receipt.json',release/'executor-receipt.json')
    executor=json.loads((release/'executor-receipt.json').read_bytes())
    receipt=dict(schema='xace.native_release.v1',game_id='echo-proof',engine='Godot',executor_receipt_sha256=sha(release/'executor-receipt.json'),package_manifest_sha256=sha(release/'package/playable.manifest.json'),compatibility=executor['compatibility'],required_capabilities=executor['capabilities'],resources=[],save_schema='echo.save.v1')
    (release/'native-release.json').write_text(json.dumps(receipt,sort_keys=True))
    exe=out/'xace-player-launcher.exe';shutil.copyfile(Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe'),exe)
    env=dict(os.environ);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    result=subprocess.run([str(exe),'--native-verify','--source',str(release),'--expected',sha(release/'native-release.json')],env=env,capture_output=True,text=True,timeout=30)
    (out/'verification.stdout.txt').write_text(result.stdout);(out/'verification.stderr.txt').write_text(result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    verification=json.loads(result.stdout);assert verification['ok']
    package=release/'package'
    proof=prove(package/'runtime/xace_runtime.exe',package/'game.cgs.json',package/'execution_plan.json',out/'custom-session')
    (out/'proof.json').write_text(json.dumps(dict(ok=True,rust_release_admission=verification,mechanic=proof,launcher_sha256=sha(exe),profile='creator_echo_cli_checkpoint_replay.v1',native_engine_build=False,native_input_graph_mapping=False,clean_machine=False),indent=2))
    print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]))
