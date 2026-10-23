"""Read current NEC011 proof receipts, source pins and protected baseline; write fresh audit."""
import hashlib,json,subprocess,sys
from pathlib import Path
from nec011_seal_integrity import verify
import nec011_reference_build as reference
import nec011_echo_build as echo
ROOT=Path(__file__).resolve().parents[1]
PROOFS=[
'evidence/nec011/20261021/distribution-player-a/interactive-session/proof.json',
'evidence/nec011/20261022/unreal-authoring-regression-a/summary.json',
'evidence/nec011/20261021/distribution-player-a/proof.json',
'evidence/nec011/20261021/browser-measured-a/proof.json',
'evidence/nec011/20261021/godot-hierarchy-monitor-c/proof.json',
'evidence/nec011/20261021/unity-hierarchy-a/proof.json',
'evidence/nec011/20261021/unreal-hierarchy-c/proof.json',
'evidence/nec011/20261023/structured-native-b/proof.json',
'evidence/nec011/20261023/godot-event-input-b/proof.json',
'evidence/nec011/20261023/unity-replacement-final-e/proof.json',
'evidence/nec011/20261023/unreal-replacement-final-b/proof.json',
'evidence/nec011/20261023/godot-contract-b/proof.json',
'evidence/nec011/20261023/unity-contract-b/proof.json',
'evidence/nec011/20261023/unreal-replacement-final-b/contract.json',
'evidence/nec011/20261023/godot-input-authority-f/proof.json',
'evidence/nec011/20261023/unity-input-authority-b/proof.json',
'evidence/nec011/20261023/unreal-input-authority-a/proof.json',
'evidence/nec011/20261021/reference-admission-a/proof.json']
def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec011') and not out.exists()
    receipts={}
    for name in PROOFS:
        path=ROOT/name;value=json.loads(path.read_bytes());assert value['ok'],name
        if isinstance(value.get('checks'),dict) and all(type(v) is bool for v in value['checks'].values()):assert all(value['checks'].values()),name
        receipts[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for module,path in [(reference,'reference-repro-a'),(echo,'repro-player-a')]:
        assert module.source_inventory()==json.loads((ROOT/'evidence/nec011/20261021'/path/'source-files.json').read_bytes())
    # Native staged sources must equal the current production adapter bytes.
    for engine,folder in [('godot','godot-event-input-b'),('unity','unity-replacement-final-e'),('unreal','unreal-replacement-final-b')]:
        project=ROOT/'evidence/nec011/20261023'/folder/'project'
        for source in (ROOT/'adapters'/engine).glob({'godot':'*.gd','unity':'*.cs','unreal':'*'}[engine]):
            if not source.is_file() or (engine=='unreal' and source.suffix not in {'.h','.cpp'}):continue
            if engine=='godot':staged=project/source.name
            elif engine=='unity':staged=project/'Assets/XACE'/source.name
            else:staged=project/'Plugins/XACE/Source/XACEAdapter'/('Public' if source.suffix=='.h' else 'Private')/source.name
            if staged.exists():assert staged.read_bytes()==source.read_bytes(),str(source)
    regressions=json.loads((ROOT/'evidence/nec011/20261023/final-regression/results.json').read_bytes())
    assert len(regressions)==3 and all(row['returncode']==0 for row in regressions)
    for index,count in enumerate([291,208,14]):
        text=(ROOT/f'evidence/nec011/20261023/final-regression/{index}.txt').read_bytes()
        assert f'Ran {count} tests'.encode('ascii') in text and b'\nOK' in text
    seal=verify();assert seal['ok']
    result=dict(schema='xace.nec011.acceptance_audit.v1',ok=True,proof_receipts=receipts,regression_counts=[291,208,14],custom_build_source_inventories_current=True,baseline_manifest_sha256=seal['baseline_manifest_sha256'],protected_baseline_files=len(seal['protected_files']),source_archive_entries=seal['source_archive_entries'],native_shipping_certified=False,nec012_started=False)
    out.mkdir(parents=True);(out/'audit.json').write_text(json.dumps(result,indent=2));(out/'seal.json').write_text(json.dumps(seal,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
