"""All-engine local portable update/save/removal independence; no clean-PC claim."""
from pathlib import Path
import copy,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from tools.nec018_signed_proof import BASES
from tools.nec012_lifecycle_proof import Host
from release_handoff import tree,sha
import playable_package as pp
from native_executor_contract import canonical,digest,admit

def publish(root,native):
 (root/'native-release.json').write_bytes(canonical(native));return sha(root/'native-release.json')
def host(exe,release,history):return Host(exe,release,sha(release/'native-release.json'),history)
def play(h):
 result=h.ask('play');assert result['ok'],result;assert h.ask('stop')['ok'];return result['result']
def save(h,slot):
 root=Path(h.initial['save_root']);root.mkdir(parents=True,exist_ok=True);snapshot=dict(tick=42,proof='admission_only_no_restore');raw=canonical(dict(schema='xace.native_save.v1',identity=h.initial['save_identity'],payload_sha256=digest(snapshot),snapshot=snapshot));p=root/('slot-'+slot+'.json');p.write_bytes(raw);return p

def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec018') and not out.exists();out.mkdir(parents=True);exe=out/'native-host.exe';shutil.copyfile('C:/Users/ankit/XACE-Recovery/build-output/cargo/debug/xace-player-launcher.exe',exe);results={}
 for engine,original in BASES.items():
  original_files=tree(original);case=out/engine;case.mkdir();a=case/'version-a';shutil.copytree(original,a);b=case/'version-b';shutil.copytree(a,b);other=case/'other-game';shutil.copytree(a,other);history=case/'history'
  native=json.loads((b/'native-release.json').read_bytes());r=json.loads((b/'executor-receipt.json').read_bytes());files={n:(b/'package'/n).read_bytes() for n in tree(b/'package')};m=json.loads(files['playable.manifest.json']);cgs=json.loads(files['game.cgs.json']);compiled,_=pp.compiled_artifacts(cgs);support=admit(r,expected_receipt_digest=digest(r),executable=b/'package/runtime/xace_runtime.exe',required_capabilities=native['required_capabilities'],expected_compatibility=native['compatibility'],package=compiled)
  presentation={n:data for n,data in files.items() if n.startswith('presentation/')};presentation['presentation/player/nec018-update-marker.txt']=b'Distinct cosmetic version B; gameplay and save identities intentionally unchanged.'
  archive=pp.read_archive(pp.build_package(cgs,files['execution_plan.json'],files['runtime/xace_runtime.exe'],support,package_id=m['package_id'],version='0.18.1',presentation_files=presentation))
  for n,data in archive.items():p=b/'package'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  native['package_manifest_sha256']=sha(b/'package/playable.manifest.json');publish(b,native)
  n=json.loads((other/'native-release.json').read_bytes());n['game_id']='nec018-independent-'+engine;publish(other,n)
  h=host(exe,a,history)
  try:
   play(h);first=save(h,'preserve');first_bytes=first.read_bytes();identity=h.initial['save_identity'];assert h.ask('check-save',slot='preserve')['result']['state']=='save_compatible'
  finally:h.close()
  active=case/'user-data/XACE/NativeGames'/('game-'+identity['game_id'])/'release-state/active.json';active_a=active.read_bytes()
  h=host(exe,other,history)
  try:play(h);second=save(h,'preserve');second_bytes=second.read_bytes();assert first.parent!=second.parent
  finally:h.close()
  h=host(exe,b,history)
  try:
   assert h.initial['save_identity']==identity and Path(h.initial['save_root'])==first.parent;play(h);assert first.read_bytes()==first_bytes;assert h.ask('check-save',slot='preserve')['result']['restored'] is False
   incompatible=json.loads(first_bytes);incompatible['identity']['executor_sha256']='0'*64;first.write_bytes(canonical(incompatible));bad_bytes=first.read_bytes();assert h.ask('check-save',slot='preserve')['ok'] is False and first.read_bytes()==bad_bytes;first.write_bytes(first_bytes)
  finally:h.close()
  active_b=active.read_bytes();assert active_a!=active_b and sha(a/'native-release.json')!=sha(b/'native-release.json');assert any(p.read_bytes()==active_a for p in active.parent.glob('previous-*.json'))
  broken=case/'invalid-world-update';shutil.copytree(b,broken);(broken/'package/world.json').write_bytes(b'{}');manifest=json.loads((broken/'package/playable.manifest.json').read_bytes())
  for row in manifest['files']:
   if row['path']=='world.json':row.update(size=2,sha256=sha(broken/'package/world.json'))
  manifest.pop('package_content_hash');manifest['package_content_hash']=digest(manifest);(broken/'package/playable.manifest.json').write_bytes(canonical(manifest));bad_native=json.loads((broken/'native-release.json').read_bytes());bad_native['package_manifest_sha256']=sha(broken/'package/playable.manifest.json');publish(broken,bad_native)
  h=host(exe,broken,history)
  try:assert h.initial['state']=='stopped';assert h.ask('verify')['ok'];failure=h.ask('play');assert not failure['ok'];assert active.read_bytes()==active_b and first.read_bytes()==first_bytes and second.read_bytes()==second_bytes
  finally:h.close()
  h=host(exe,b,history);assert h.initial['state']=='stopped';h.p.kill();h.p.wait(timeout=10);h.p.stdin.close();h.p.stdout.close();h.p.stderr.close();assert active.read_bytes()==active_b
  h=host(exe,a,history)
  try:play(h)
  finally:h.close()
  assert active.read_bytes()==active_a and first.read_bytes()==first_bytes
  # Reversible removal ONLY of the fresh owned test copy, all bytes retained.
  quarantine=case/'quarantine';quarantine.mkdir();destination=quarantine/'version-a'
  assert a.resolve().is_relative_to(out) and destination.absolute().is_relative_to(out) and not destination.exists();before_removal=tree(a);a.rename(destination);assert not a.exists() and tree(destination)==before_removal
  h=host(exe,other,history)
  try:play(h);assert first.read_bytes()==first_bytes and second.read_bytes()==second_bytes
  finally:h.close()
  assert destination.resolve().is_relative_to(out) and a.absolute().is_relative_to(out) and not a.exists();destination.rename(a)
  h=host(exe,a,history)
  try:play(h);assert h.ask('check-save',slot='preserve')['result']['state']=='save_compatible'
  finally:h.close()
  assert first.read_bytes()==first_bytes and second.read_bytes()==second_bytes and tree(original)==original_files
  results[engine]=dict(two_distinct_native_package_revisions=True,actual_authority_started=True,separate_game_namespaces=True,compatible_save_admitted_without_restore=True,incompatible_save_refused_unchanged=True,failed_ready_update_preserves_activation=True,interrupted_update_preserves_activation=True,prior_revision_retained=True,explicit_rollback=True,reversible_portable_removal_preserves_saves_and_other_game=True,restored_installation_relaunches=True,original_release_unchanged=True,failure=failure)
 proof=dict(schema='xace.nec018.portable_independence.v1',ok=True,launcher_sha256=sha(exe),engines=results,clean_machine=False,msi_or_general_installer=False,native_engine_rebuilds=False,native_engine_player_ui_retested=False,scope='Real common native-host authority and portable filesystem operations on development laptop; final native clean-PC matrix remains mandatory',release_certified=False)
 (out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print(json.dumps(proof,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
