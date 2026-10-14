"""Stage fresh recovered XP022 binaries and packages; never recreate original seal."""
import sys, json, shutil, hashlib, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.xp019_activation_proof import prepare
from tools.xp017_mixed_session_proof import GODOT,TEMPLATE
from tools.xp008_player_build import prepare_player
from tools.xp010_player_distribution import assemble
from tools.xp007_package_proof import compile_plan
from playable_package import RuntimeSupport,digest
base=Path(os.environ.get('XACE_RECOVERY_EVIDENCE',str(ROOT/'recovery-evidence/20261012/xp022'))).resolve()
base.mkdir(parents=True,exist_ok=True)
build=Path('C:/Users/ankit/XACE-Recovery/build-output/cargo/release')
pins=base/'pinned-binaries';pins.mkdir(exist_ok=False)
identity={}
for name in ['xace_reference_host.exe','xace-player-launcher.exe','xace-session-relay.exe']:
    shutil.copy2(build/name,pins/name)
    identity[name]=digest((pins/name).read_bytes())
    assert identity[name]==digest((build/name).read_bytes())
(pins/'identity.json').write_text(json.dumps(identity,indent=2))
legacy=ROOT/'target/debug/xace_reference_host.exe'
if legacy.exists():shutil.copy2(legacy,pins/'previous-reproducible-debug-host.exe')
legacy.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(pins/'xace_reference_host.exe',legacy)
artifacts=base/'artifacts';prepare(artifacts)
assert digest((artifacts/'parent/runtime/xace_runtime.exe').read_bytes())==identity['xace_reference_host.exe']
shutil.copy2(ROOT/'adapters/unity/Editor/XaceNativeContractProof.cs',artifacts/'build/target-codex-task65-unity-vertical-slice/Assets/XACE/Editor')
package=artifacts/'parent';cgs=json.loads((package/'game.cgs.json').read_text());_,compiled=compile_plan(cgs)
support=RuntimeSupport(identity['xace_reference_host.exe'],'xace.runtime_executor.v1',tuple(compiled.to_sgc_input()))
prepare_player(package,support,base/'production-player')
result=assemble(base/'production-player',base/'release',GODOT,TEMPLATE,pins/'xace-player-launcher.exe')
assert not list((base/'release/package').rglob('*.import'))
(base/'packaging.json').write_text(json.dumps(result,indent=2))
print('Fresh recovered XP022 artifacts staged; original evidence remains missing')
