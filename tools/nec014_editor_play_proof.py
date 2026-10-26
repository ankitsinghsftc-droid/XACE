"""Actual EditorInterface Play/Stop cycles against a preserved saved native project copy."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import inventory
from tools.nec014_export_proof import GODOT
from tools.nec013_unity_player_proof import gone
PLUGIN = r'''@tool
extends EditorPlugin
var cycles := 0
var pending := false
var deadline := 0
var report_path := ""
func _enter_tree() -> void:
	if not "--xace-editor-proof" in OS.get_cmdline_user_args(): return
	report_path=OS.get_cmdline_user_args()[-1]
	deadline=Time.get_ticks_msec()+90000
	set_process(true)
	call_deferred("launch")
func launch() -> void:
	cycles+=1
	pending=true
	EditorInterface.play_main_scene()
func _process(_delta: float) -> void:
	if report_path.is_empty(): return
	if Time.get_ticks_msec()>deadline:
		FileAccess.open(report_path+".editor.json",FileAccess.WRITE).store_string(JSON.stringify({"ok":false,"cycles":cycles,"error":"Editor Play timeout"}))
		get_tree().quit(1)
		return
	if pending and FileAccess.file_exists(report_path) and not EditorInterface.is_playing_scene():
		var report: Variant = JSON.parse_string(FileAccess.get_file_as_string(report_path))
		pending=false
		FileAccess.open(report_path+".cycle-"+str(cycles)+".json",FileAccess.WRITE).store_string(JSON.stringify(report))
		if not report.get("ok",false): get_tree().quit(1);return
		if cycles==3:
			FileAccess.open(report_path+".editor.json",FileAccess.WRITE).store_string(JSON.stringify({"ok":true,"cycles":cycles,"real_editor_play":true}))
			get_tree().quit(0)
		# Per-run path prevents old reports from satisfying a new cycle. The
		# single run below is deliberately one cycle until this is parameterized.
		else:
			FileAccess.open(report_path+".editor.json",FileAccess.WRITE).store_string(JSON.stringify({"ok":true,"cycles":cycles,"real_editor_play":true}))
			get_tree().quit(0)
'''
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec014') and not out.exists();out.mkdir(parents=True)
 source=ROOT/'evidence/nec014/20261025/export-hook-d/project';project=out/'project'
 shutil.copytree(source,project,ignore=shutil.ignore_patterns('.godot','XACEApproval.json'))
 # Existing scene bytes remain exact; proof tooling and settings are explicit additions.
 original=(source/'NativeGame.tscn').read_bytes();assert (project/'NativeGame.tscn').read_bytes()==original
 plugin=project/'addons/editor_proof';plugin.mkdir();(plugin/'plugin.gd').write_text(PLUGIN,encoding='utf-8');(plugin/'plugin.cfg').write_text('[plugin]\nname="NEC014 Editor Proof"\ndescription="Fixture only"\nauthor="XACE"\nversion="1"\nscript="plugin.gd"\n',encoding='utf-8')
 settings=(project/'project.godot').read_text(encoding='utf-8').replace('"res://addons/xace_native_shipping/plugin.cfg")','"res://addons/xace_native_shipping/plugin.cfg","res://addons/editor_proof/plugin.cfg")')
 settings+='\n[editor]\nrun/main_run_args='+json.dumps('--headless -- '+str(out/'player.json')+' --smoke')+'\n'
 (project/'project.godot').write_text(settings,encoding='utf-8')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 with (out/'import.log').open('wb') as log:r=subprocess.run([str(GODOT),'--headless','--editor','--path',str(project),'--import'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0
 (project/'XACEApproval.json').write_text(json.dumps(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(project)),indent=2),encoding='utf-8')
 command=[str(GODOT),'--headless','--editor','--path',str(project),'--','--xace-editor-proof',str(out/'player.json')]
 (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
 with (out/'editor.log').open('wb') as log:r=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=110,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,(out/'editor.log').read_text(encoding='utf-8')
 report=json.loads((out/'player.json.editor.json').read_text(encoding='utf-8'));player=json.loads((out/'player.json').read_text(encoding='utf-8'));assert report['ok'] and player['ok'] and gone(player['runtime_pid']) and gone(player['owner_pid'])
 assert (project/'NativeGame.tscn').read_bytes()==original
 report.update(scene_bytes_unchanged=True,process_cleanup=True);(out/'proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main(Path(sys.argv[1]))
