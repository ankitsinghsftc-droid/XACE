"""Fresh copy of an earlier authoring project: real Play, Stop and authority faults."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import inventory,sha,export
from tools.nec014_export_proof import GODOT
from tools.nec013_unity_player_proof import gone
PLUGIN=r'''@tool
extends EditorPlugin
var report := ""
var deadline := 0
var stopped := false
func _enter_tree() -> void:
 if not "--stop-proof" in OS.get_cmdline_user_args(): return
 report=OS.get_cmdline_user_args()[-1]
 deadline=Time.get_ticks_msec()+60000
 set_process(true)
 call_deferred("launch")
func launch() -> void: EditorInterface.play_main_scene()
func _process(_dt: float) -> void:
 if report.is_empty(): return
 if Time.get_ticks_msec()>deadline: get_tree().quit(1);return
 if not stopped and FileAccess.file_exists(report+".ready.json"):
  stopped=true
  EditorInterface.stop_playing_scene()
 if stopped and not EditorInterface.is_playing_scene():
  FileAccess.open(report+".editor.json",FileAccess.WRITE).store_string(JSON.stringify({"ok":true,"actual_editor_stop":true}))
  get_tree().quit()
'''
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec014') and not out.exists();out.mkdir(parents=True)
 source=ROOT/'evidence/nec011/20261021/godot-hierarchy-monitor-c/project';before=inventory(source)
 project=out/'project';shutil.copytree(source,project,ignore=shutil.ignore_patterns('.godot','.git','XACEApproval.json'))
 preserved=(project/'Fixture/World.tscn').read_bytes()
 for p in (ROOT/'adapters/godot').glob('*.gd'):shutil.copyfile(p,project/p.name)
 shutil.copytree(ROOT/'adapters/godot/native_export',project/'addons/xace_native_shipping')
 # The earlier saved scene remains byte-identical: opt-in host is added at runtime
 # by this fixture observer, without replacing nodes or authoring identities.
 probe=(ROOT/'tools/nec014_export_probe.gd').read_text(encoding='utf-8').replace('extends Node3D','extends Node',1).replace('$Existing0/Existing1','$Parent/Child').replace('$Existing0','$Parent')
 probe=probe.replace('func _ready() -> void: deadline=Time.get_ticks_msec()+30000','''func _ready() -> void:
 deadline=Time.get_ticks_msec()+30000
 var host = load("res://xace_native_host.gd").new()
 host.name="NativeHost"
 add_child(host)''')
 (project/'probe.gd').write_text(probe.expandtabs(1),encoding='utf-8')
 # A fixture autoload attaches the observer to the existing loaded main scene.
 (project/'observer.gd').write_text('extends Node\nfunc _ready() -> void: call_deferred("attach")\nfunc attach() -> void:\n var scene=get_tree().current_scene\n scene.set_script(load("res://probe.gd"))\n scene._ready()\n scene.set_process(true)\n',encoding='utf-8')
 release=project/'release';shutil.copytree(ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Godot/release',release)
 shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 world=json.loads((release/'package/world.json').read_bytes())
 profile=dict(schema='xace.godot.native_profile.v1',game_id='nec012-proof',release_directory='release',release_sha256=sha(release/'native-release.json'),launcher_sha256=sha(release/'xace-player-launcher.exe'),controller_id=1,objects={o['id']:['../Parent','../Parent/Child'][i] for i,o in enumerate(world['objects'])},input_bindings=[dict(action='move_x',kind='axis_1d',native_selector='proof.move')])
 (project/'xace-native-profile.json').write_text(json.dumps(profile),encoding='utf-8')
 plugin=project/'addons/stop_proof';plugin.mkdir();(plugin/'plugin.gd').write_text(PLUGIN,encoding='utf-8');(plugin/'plugin.cfg').write_text('[plugin]\nname="Stop Proof"\ndescription="Fixture"\nauthor="XACE"\nversion="1"\nscript="plugin.gd"\n',encoding='utf-8')
 # Preserve every original file in the source; settings changes in the copy are explicit.
 settings='config_version=5\n[application]\nconfig/name="NEC011 Existing World"\nrun/main_scene="res://Fixture/World.tscn"\n[autoload]\nObserver="*res://observer.gd"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_native_shipping/plugin.cfg","res://addons/stop_proof/plugin.cfg")\n[editor]\nrun/main_run_args='+json.dumps('--headless -- '+str(out/'editor-stop.json')+' --hold')+'\n'
 (project/'project.godot').write_text(settings,encoding='utf-8')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 with (out/'import.log').open('wb') as log:r=subprocess.run([str(GODOT),'--headless','--editor','--path',str(project),'--import'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0
 (project/'XACEApproval.json').write_text(json.dumps(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(project)),indent=2),encoding='utf-8')
 results={}
 sentinel=subprocess.Popen([sys.executable,'-c','import time; time.sleep(180)'],creationflags=subprocess.CREATE_NO_WINDOW)
 try:
  for mode in ['smoke','fault','parent-crash','editor-stop']:
   report=out/(mode+'.json');args=[str(GODOT),'--headless','--path',str(project)]
   if mode=='editor-stop':args+=['--editor','--','--stop-proof',str(report)]
   else:args+=['--',str(report),'--fault' if mode=='fault' else '--hold' if mode=='parent-crash' else '--smoke']
   with (out/(mode+'.log')).open('wb') as log:
    process=subprocess.Popen(args,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    if mode in ['fault','parent-crash']:
     deadline=time.monotonic()+45;ready=Path(str(report)+'.ready.json')
     while not ready.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.1)
     assert ready.exists(),mode
     ids=json.loads(ready.read_text());assert process.poll() is None and ids['godot_pid']>0 and ids['runtime_pid']>0
     if mode=='fault':
      # Only the exact runtime identified by this freshly launched host.
      subprocess.run(['taskkill','/PID',str(ids['runtime_pid']),'/F'],capture_output=True,check=True)
     else:subprocess.run(['taskkill','/PID',str(ids['godot_pid']),'/F'],capture_output=True,check=True)
    code=process.wait(timeout=70)
   if mode in ['smoke','fault']:
    proof=json.loads(report.read_text());assert code==0 and proof['ok'],proof
    if mode=='fault':assert proof['fault_frozen_frames']>=20 and proof['error']
   else:
    proof=json.loads(Path(str(report)+'.ready.json').read_text())
    if mode=='editor-stop':assert code==0 and json.loads(Path(str(report)+'.editor.json').read_text())['actual_editor_stop']
   assert gone(proof['runtime_pid']) and gone(proof['owner_pid']),mode
   assert sentinel.poll() is None
   results[mode]=dict(ok=True,process_cleanup=True,unrelated_process_survives=True)
 finally:sentinel.terminate();sentinel.wait(timeout=10)
 assert (project/'Fixture/World.tscn').read_bytes()==preserved and inventory(source)==before
 # Export the same preserved existing World, using the ordinary native preset.
 template=ROOT/'evidence/nec014/20261025/export-preflight-f/windows_release_x86_64.exe'
 shutil.copyfile(template,out/'windows_release_x86_64.exe')
 preset=(ROOT/'evidence/nec014/20261025/export-preflight-f/project/export_presets.cfg').read_text(encoding='utf-8').replace(str(template).replace('\\','/'),(out/'windows_release_x86_64.exe').as_posix())
 (project/'export_presets.cfg').write_text(preset,encoding='utf-8')
 (project/'XACEApproval.json').write_text(json.dumps(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(project)),indent=2),encoding='utf-8')
 export(project,out/'export',GODOT)
 game=out/'relocated';shutil.copytree(out/'export/shipping',game);installation=inventory(game)
 env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 with (out/'export-player.log').open('wb') as log:r=subprocess.run([str(game/'NativeGame.exe'),'--headless','--',str(out/'export-player.json'),'--smoke'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
 player=json.loads((out/'export-player.json').read_text());assert r.returncode==0 and player['ok'] and player['exported'] and gone(player['runtime_pid']) and gone(player['owner_pid'])
 assert inventory(game)==installation and (project/'Fixture/World.tscn').read_bytes()==preserved
 results['existing_project_export']=dict(ok=True,main_scene=player['native_scene'],installation_unchanged=True,process_cleanup=True)
 results.update(ok=True,original_source_unchanged=True,existing_scene_bytes_unchanged=True,scene_sha256=sha(source/'Fixture/World.tscn'),profile='static translation hierarchy; existing NEC011 authoring fixture; explicit settings/observer additions')
 (out/'proof.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
if __name__=='__main__':main(Path(sys.argv[1]))
