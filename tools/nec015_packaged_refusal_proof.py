"""Refuse damaged cooked content and incompatible package metadata before Play."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec015_package_proof import sha,run
from tools.nec013_unity_player_proof import gone

def main(source,out):
 source=source.resolve();out=out.resolve()
 assert source.is_relative_to(ROOT/'evidence/nec015') and out.is_relative_to(ROOT/'evidence/nec015') and not out.exists()
 assert json.loads((source.parent.parent/'proof.json').read_text())['ok']
 out.mkdir(parents=True);results={}
 for case in ['missing-cooked-content','missing-required-audio','incompatible-package']:
  dest=out/case;game=dest/'installation';shutil.copytree(source,game);base=game/'NEC015'
  receipt=base/'XACEBuild.json';record=json.loads(receipt.read_text())
  if case=='missing-cooked-content':
   pak=next((base/'Content/Paks').glob('*.pak'));pak.rename(dest/('preserved-'+pak.name))
   expected='Cooked file mismatch:'
  else:
   relative='release/package/game.cgs.json' if case=='missing-required-audio' else 'release/package/playable.manifest.json'
   path=base/relative;data=json.loads(path.read_text());(dest/'original-metadata.json').write_bytes(path.read_bytes())
   if case=='missing-required-audio':
    rows=[r for r in data['semantic_bindings']['bindings'] if r['playback_kind']=='Audio'];assert rows
    for row in rows:row['parameters']['resource_path']='/Game/AbsentNEC015Audio.AbsentNEC015Audio'
    expected='Required native audio missing'
   else:data['gameplay']['runtime_abi']='nec015.incompatible.v999';expected='Native'
   path.write_text(json.dumps(data,sort_keys=True,separators=(',',':')),encoding='utf-8')
   record['files'][relative]=sha(path);receipt.write_text(json.dumps(record,indent=2),encoding='utf-8')
  env=dict(os.environ);env['LOCALAPPDATA']=str(dest/'user-data');env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
  cmd=[str(game/'NEC015.exe'),'-d3d11','-RenderOffscreen','-unattended',f'-XaceNativePreflight={dest/"preflight.json"}',f'-abslog={dest/"engine.log"}']
  (dest/'command.json').write_text(json.dumps(cmd),encoding='utf-8')
  with (dest/'run.log').open('xb') as stream:r=subprocess.run(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
  proof=json.loads((dest/'preflight.json').read_text(encoding='utf-8-sig'))
  assert r.returncode!=0 and not proof['ok'] and not proof['authority_started'] and not proof['package_admitted'] and expected in proof['error'],proof
  if proof['verifier_pid']:assert gone(proof['verifier_pid'])
  if case=='incompatible-package':assert proof['verifier_pid']>0,'Must exercise Rust admission beyond cooked hash gate'
  results[case]=proof
 (out/'proof.json').write_text(json.dumps(dict(ok=True,cases=results,receipt_reissued_only_for_controlled_fault_fixture=True),indent=2),encoding='utf-8');print(json.dumps(results))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
