"""Installed-editor verification of the new Godot native setup factory."""
import json,sys,shutil,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'packages/project-system')]
from authoring_identity import canonical
from godot_authoring import prepare_identity_map,capture
GODOT=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
DRIVER='''@tool
extends EditorPlugin
const Factory = preload("native_setup.gd")
func _enter_tree() -> void:
	call_deferred("run")
func run() -> void:
	await get_tree().create_timer(1).timeout
	var factory = Factory.new()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://.xace/spec.json"))
	var result: Dictionary
	var reload_phase := "--cold-reopen" in OS.get_cmdline_user_args()
	if reload_phase:
		factory.reader.trusted_project = true
		result = {"inventory": factory.reader.capture(["res://XACEGenerated/World.tscn"])}
		var before := FileAccess.get_sha256("res://XACEGenerated/World.tscn")
		result["existing_refused"] = factory.create(spec, factory.reader.wire.digest(spec)).is_empty()
		result["unchanged"] = before == FileAccess.get_sha256("res://XACEGenerated/World.tscn")
	else:
		result = factory.create(spec, factory.reader.wire.digest(spec))
	var file := FileAccess.open("res://.xace/result-" + ("reload" if reload_phase else "create") + ".json", FileAccess.WRITE)
	file.store_string(factory.reader.wire.encode({"result": result, "error": factory.error}))
	file.close()
	get_tree().quit(0 if not result.is_empty() else 1)
'''

def main(out):
    assert out.is_relative_to(ROOT/'evidence/nec010') and not out.exists()
    project=out/'godot-project';addon=project/'addons/xace_authoring';addon.mkdir(parents=True)
    for p in (ROOT/'adapters/godot/authoring').iterdir():
        if p.is_file():shutil.copyfile(p,addon/p.name)
    (addon/'setup_proof.gd').write_text(DRIVER)
    (addon/'plugin.cfg').write_text((addon/'plugin.cfg').read_text().replace('authoring_plugin.gd','setup_proof.gd'))
    (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Native Setup Proof"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    from native_setup_plan import plan_setup,verify_setup
    cgs=json.loads((ROOT/'recovery-evidence/20261016/nec007/native-runtime/godot/plan.json').read_text())['proposed_cgs']
    plan=plan_setup(cgs,engine='godot',namespace_id='a'*32,project_id='native-setup-proof',branch_id='b'*32,mode_id=cgs['modes'][0]['id'])
    spec=plan.to_dict()['native_request']
    (out/'setup-plan.json').write_bytes(plan.payload);(out/'source.cgs.json').write_bytes(canonical(cgs))
    journal=project/'.xace';journal.mkdir();(journal/'spec.json').write_bytes(canonical(spec))
    (journal/'native-setup-approved.json').write_bytes(canonical(dict(digest=hashlib.sha256(canonical(spec)).hexdigest(),stage_root=project.as_posix())))
    for phase in ['create','reload']:
        command=[str(GODOT),'--headless','--editor','--path',str(project),'--']+(['--cold-reopen'] if phase=='reload' else [])
        (out/(phase+'-command.json')).write_text(json.dumps(command,indent=2))
        with (out/(phase+'.log')).open('wb') as f:r=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=75,creationflags=subprocess.CREATE_NO_WINDOW)
        assert r.returncode==0,(phase,r.returncode)
        result=json.loads((journal/('result-'+phase+'.json')).read_text())
        assert result['result'].get('inventory'),result
        data=canonical(result['result']['inventory']);mapping=prepare_identity_map(data,project_id='native-setup-proof',branch_id='b'*32)
        verified_mapping,verified_rows=verify_setup(plan,cgs,data)
        assert verified_mapping.objects and verified_rows
        if phase=='create':before=data
        else:assert before==data and result['result']['existing_refused'] and result['result']['unchanged']
        (out/(phase+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    (out/'proof.json').write_text(json.dumps(dict(ok=True,real_editor=True,created_native_scene=True,cold_capture_identical=True,existing_content_preserved=True,exact_transform=True),indent=2)+'\n')
    print((out/'proof.json').read_text())
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
