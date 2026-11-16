"""Close a verified private authoring sequence with fresh gameplay/replay/native Play/build."""
from pathlib import Path
import json,sys,importlib,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec017_existing_execution import main as execution

def main(engine,workflow):
 workflow=workflow.resolve();assert engine in ['godot','unity','unreal'] and workflow.is_relative_to(ROOT/'evidence/nec017') and not (workflow/'proof.json').exists();authoring=json.loads((workflow/'authoring-proof.json').read_bytes());assert authoring['ok'] and authoring['actual_native_conflict_refused'] and authoring['explicit_engine_resolution_committed'] and len(authoring['mutations'])==5
 execution(workflow/'gameplay',{engine:workflow});native=importlib.import_module('tools.nec017_'+engine+'_existing_play');native.main(workflow/'play-again',source=workflow/'project',package_base=workflow/'gameplay'/engine,**(dict(project_destination=Path('C:/Users/ankit/XACE-Recovery/continuity')/('ue17wf-'+workflow.name[-1]),disable_pch=True) if engine=='unreal' else {}))
 played=json.loads((workflow/'play-again/proof.json').read_bytes());assert played['ok'];proof=dict(ok=True,engine=engine,objects=authoring['objects'],native_mutations=authoring['mutations'],native_edit_and_canonical_conflict_refused=True,explicit_resolution_and_reviewed_restore=True,fresh_explicit_gameplay_choice=True,arbitrary_native_gameplay_conversion=False,gameplay_execution_replay=json.loads((workflow/'gameplay'/engine/'proof.json').read_bytes()),native_play_again_build=played,structural_scope='Native identity preservation and explicit fail-closed refusal where materialization unsupported; no dynamic spawn/despawn/reparent certification',clean_machine=False,full_nec017_complete=False,source_and_compact_off_device=False)
 (workflow/'proof.json').write_text(json.dumps(proof,indent=2));print('Integrated '+engine+' authoring/conflict/replay/native Play/build chain passed',flush=True)
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
