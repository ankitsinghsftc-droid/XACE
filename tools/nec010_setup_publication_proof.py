"""Real native setup publication, saved-pair verification and host handoff."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from authoring_identity import canonical,IdentityMap
from authoring_saved_pair import MAP,verify_baseline_receipts
from native_editor_gateway import NativeEditorGateway
from native_setup_plan import NativeSetupPlan
from native_setup_stage import VerifiedNativeSetupStage
from native_setup_review import NativeSetupReview
from native_materialization import NativeMaterializationHost
from nec010_editor_gateway_proof import SOURCES

def main(engine,source,out):
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists()
    config=json.loads((source/'gateway-config.json').read_text())
    stage_gateway=NativeEditorGateway(source/(engine+'-project'),**config)
    generated=ROOT/SOURCES[engine]
    cgs=json.loads((generated/'source.cgs.json').read_text())
    plan=NativeSetupPlan((generated/'setup-plan.json').read_bytes())
    provider=VerifiedNativeSetupStage(plan,cgs,stage_gateway)
    root=out/(engine+'-project');root.mkdir(parents=True)
    (root/'game.cgs.json').write_bytes(canonical(cgs))
    gateway=NativeEditorGateway(root,**config)
    host=NativeMaterializationHost(root,lambda:None,gateway)
    review=NativeSetupReview(host,provider)
    opened=review.open('native-proof');approved=review.approve('native-proof',opened['token'],opened['proposal_digest'])
    assert not any((root/p).exists() for p in provider.files)
    (out/'review.json').write_bytes(canonical(opened))
    result=review.apply('native-proof',approved['token'],approved['proposal_digest'],approved['approval'])
    assert result['state']=='committed',result
    restarted=NativeMaterializationHost(root,lambda:None,NativeEditorGateway(root,**config))
    assert not restarted.status()['play_build_blocked']
    mapping=IdentityMap.from_dict(json.loads((root/MAP).read_text()))
    assert verify_baseline_receipts(root,mapping.baseline)
    assert gateway.capture()==provider.inventory
    try:review.open('native-proof')
    except ValueError:pass
    else:raise AssertionError('second setup must refuse existing native content')
    proof=dict(ok=True,engine=engine,real_native_editor=True,reviewed_files=len(provider.files),separate_approval=True,committed=result,cold_capture_identical=True,verified_baseline=True,normal_host_ready=True,existing_content_refused=True,runtime_activation=False)
    (out/'proof.json').write_bytes(canonical(proof));print(json.dumps(proof))
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve())
