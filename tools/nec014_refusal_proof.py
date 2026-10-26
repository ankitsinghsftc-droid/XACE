"""Fresh stale-source, prior-output and cooked required-resource refusal proofs."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import export,inventory
from tools.nec014_export_proof import GODOT

def main(source,out):
 source=source.resolve();out=out.resolve();assert source.is_relative_to(ROOT/'evidence/nec014') and out.is_relative_to(ROOT/'evidence/nec014') and not out.exists();out.mkdir(parents=True)
 original=inventory(source)
 stale=out/'stale-source';shutil.copytree(source,stale,ignore=shutil.ignore_patterns('.godot'))
 with (stale/'NativeGame.tscn').open('a',encoding='utf-8') as f:f.write('\n; unapproved source edit\n')
 refused=False
 try:export(stale,out/'stale-output',GODOT)
 except AssertionError as error:refused='approval stale' in str(error)
 assert refused and not (out/'stale-output').exists()
 prior=out/'prior-output';prior.mkdir();(prior/'preserved.bin').write_bytes(b'prior release')
 try:export(source,prior,GODOT)
 except AssertionError:pass
 else:raise AssertionError('Prior export accepted as output')
 assert (prior/'preserved.bin').read_bytes()==b'prior release'
 missing=out/'missing-packed-audio';shutil.copytree(source,missing,ignore=shutil.ignore_patterns('.godot','XACEApproval.json'))
 p=missing/'export_presets.cfg';s=p.read_text(encoding='utf-8').replace('exclude_filter="release/*"','exclude_filter="release/*,tone.tres"');p.write_text(s,encoding='utf-8')
 (missing/'XACEApproval.json').write_text(json.dumps(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(missing)),indent=2),encoding='utf-8')
 try:export(missing,out/'missing-export',GODOT)
 except AssertionError:pass
 else:raise AssertionError('Missing packed required resource admitted')
 receipt=json.loads((out/'missing-export/receipt.json').read_text(encoding='utf-8'));probe=json.loads((out/'missing-export/packed-preflight.json').read_text(encoding='utf-8'))
 assert receipt['status']=='failed' and probe['schema']=='xace.godot.native_preflight.v1' and not probe['ok'] and not probe['authority_started'],probe
 assert original==inventory(source)
 result=dict(ok=True,stale_source_refused=True,prior_output_preserved=True,cooked_missing_audio_refused=True,no_authority_for_preflight=True,original_source_unchanged=True,failed_staging_retained=True)
 (out/'proof.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
