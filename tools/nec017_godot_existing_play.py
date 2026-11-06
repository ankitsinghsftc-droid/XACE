"""Create-only actual native Play/export proof for the imported NEC017 Godot fixture."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'packages'),str(ROOT/'packages/project-system')]
from tools.nec014_export import inventory,sha,export
from tools.nec014_export_proof import GODOT
from tools.nec014_editor_play_proof import PLUGIN
from tools.nec013_unity_player_proof import gone
import playable_package as pp
from native_executor_contract import admit,digest
PROBE = r'''extends Node
var host
var deadline := 0
var done := false
var initial := {}
func _ready() -> void: call_deferred("attach")
func attach() -> void:
 var scene=get_tree().current_scene
 for i in range(50): initial["Crate"+str(i)]=scene.get_node("Crate"+str(i)).global_position
 host=load("res://xace_native_host.gd").new()
 host.name="NativeHost"
 deadline=Time.get_ticks_msec()+45000
 scene.add_child(host)
func _process(_dt: float) -> void:
 if done or host==null: return
 if host.preflight_only: return
 if host.state=="failed": finish(false,host.error);return
 if Time.get_ticks_msec()>deadline: finish(false,"Native proof timeout");return
 if host.state!="playing": return
 host.collector.submit_native_action("proof.move",1.0)
 if host.adapter._last_runtime_tick<30: return
 var scene=get_tree().current_scene
 var ok=host.manager.entity_count()==50 and scene.get_node("Crate0").global_position.x>initial["Crate0"].x+0.1
 for i in range(50):
  var node=scene.get_node("Crate"+str(i))
  ok=ok and node.get_node_or_null("CanonicalVisual")==null and node.mesh!=null and node.material_override!=null
  if i>0: ok=ok and node.global_position.distance_to(initial["Crate"+str(i)])<0.00001
 for node in host.manager._nodes.values():
  var id=int(node.get_meta("xace_entity_id"))
  var position=host.manager.component_snapshot(id).get(1,{}).get("data",{}).get("position",{})
  ok=ok and node.global_position.distance_to(Vector3(float(position.get("x",0)),float(position.get("y",0)),float(position.get("z",0)))/1000000.0)<0.00001
 finish(ok,"" if ok else "Original native identity/resource/input/projection mismatch")
func finish(ok: bool,issue: String) -> void:
 done=true
 var result={"ok":ok,"error":issue,"objects":host.manager.entity_count() if host.manager!=null else 0,"tick":host.adapter._last_runtime_tick if host.adapter!=null else 0,"runtime_pid":host.runtime_pid,"owner_pid":host.host_client.pid if host.host_client!=null else 0,"exported":not OS.has_feature("editor"),"native_scene":get_tree().current_scene.scene_file_path}
 host.stop()
 FileAccess.open(OS.get_cmdline_user_args()[0],FileAccess.WRITE).store_string(JSON.stringify(result))
 get_tree().quit(0 if ok else 1)
'''
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists();assert shutil.disk_usage(ROOT).free>4*1024**3
 out.mkdir(parents=True);source=ROOT/'evidence/nec017/20261105/godot-material-publish-a/project';before=inventory(source)
 project=out/'project';shutil.copytree(source,project,ignore=shutil.ignore_patterns('.godot','.git','.xace','XACEApproval.json'))
 native={p.relative_to(project).as_posix():sha(p) for p in (project/'Game').rglob('*') if p.is_file()}
 for p in (ROOT/'adapters/godot').glob('*.gd'):shutil.copyfile(p,project/p.name)
 shutil.copytree(ROOT/'adapters/godot/native_export',project/'addons/xace_native_shipping')
 (project/'nec017_probe.gd').write_text(PROBE,encoding='utf-8')
 plugin=project/'addons/nec017_editor_proof';plugin.mkdir();(plugin/'plugin.gd').write_text(PLUGIN,encoding='utf-8');(plugin/'plugin.cfg').write_text('[plugin]\nname="NEC017 proof"\ndescription="Fixture only"\nauthor="XACE"\nversion="1"\nscript="plugin.gd"\n',encoding='utf-8')
 settings=(project/'project.godot').read_text(encoding='utf-8').replace('enabled=PackedStringArray("res://addons/xace_authoring/plugin.cfg")','enabled=PackedStringArray("res://addons/xace_native_shipping/plugin.cfg")')
 settings=settings.replace('enabled=PackedStringArray("res://addons/xace_native_shipping/plugin.cfg")','enabled=PackedStringArray("res://addons/xace_native_shipping/plugin.cfg","res://addons/nec017_editor_proof/plugin.cfg")')
 settings+='\n[editor]\nrun/main_run_args='+json.dumps('--headless -- '+str(out/'editor-player.json'))+'\n'
 (project/'project.godot').write_text(settings+'\n[autoload]\nNEC017Observer="*res://nec017_probe.gd"\n',encoding='utf-8')
 base=ROOT/'evidence/nec017/20261106/existing-execution-b/godot';files=pp.read_archive((base/'game.xacepkg').read_bytes());cgs=json.loads(files['game.cgs.json'])
 receipt_path=ROOT/'evidence/nec011/20261021/reference-admission-a/executor-receipt.json';receipt=json.loads(receipt_path.read_bytes());exe=base/'relocated/runtime/xace_runtime.exe'
 compiled,_=pp.compiled_artifacts(cgs);support=admit(receipt,expected_receipt_digest=digest(receipt),executable=exe,required_capabilities=['native.structured_transform.v1'],expected_compatibility=receipt['compatibility'],package=compiled)
 presentation={p:data for p,data in files.items() if p.startswith('presentation/')}
 presentation['presentation/player/settings.json']=pp.encode(dict(schema='xace.player.controls.v1',controller_id=1,instructions='Move with D/A; native proof injects the declared move axis',bindings=[dict(action='move_x',positive=68,negative=65,kind='axis_1d')]))
 archive=pp.build_package(cgs,files['execution_plan.json'],exe.read_bytes(),support,package_id='nec017.existing.godot',version='0.1.0',presentation_files=presentation)
 (out/'game.xacepkg').write_bytes(archive);release=project/'release';release.mkdir()
 for name,data in pp.read_archive(archive).items():
  p=release/'package'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 shutil.copyfile(receipt_path,release/'executor-receipt.json');shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 native_release=dict(schema='xace.native_release.v1',engine='Godot',game_id='nec017-existing-godot',package_manifest_sha256=sha(release/'package/playable.manifest.json'),executor_receipt_sha256=sha(release/'executor-receipt.json'),required_capabilities=['native.structured_transform.v1'],compatibility=receipt['compatibility'],save_schema='nec017.existing.v1',resources=[])
 (release/'native-release.json').write_bytes(pp.encode(native_release))
 world=json.loads((release/'package/world.json').read_bytes());capture=json.loads((base/'native-inventory.json').read_bytes());objects={o['id']:'../'+capture['objects'][o['id'].split('_')[-1]]['name'] for o in world['objects']}
 profile=dict(schema='xace.godot.native_profile.v1',game_id=native_release['game_id'],release_directory='release',release_sha256=sha(release/'native-release.json'),launcher_sha256=sha(release/'xace-player-launcher.exe'),controller_id=1,objects=objects,input_bindings=[dict(action='move_x',kind='axis_1d',native_selector='proof.move')]);(project/'xace-native-profile.json').write_bytes(pp.encode(profile))
 pins={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),*sorted((ROOT/'adapters/godot').rglob('*.gd')),*sorted((ROOT/'packages/project-system').glob('*.py'))]};(out/'source-pins.json').write_bytes(pp.encode(pins))
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 def run(args,name,timeout=120):
  with (out/(name+'.log')).open('wb') as log:r=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
  assert r.returncode==0,name+' failed; retained log'
 run([str(GODOT),'--headless','--editor','--path',str(project),'--import'],'import')
 def approve(): (project/'XACEApproval.json').write_bytes(pp.encode(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(project))))
 approve();run([str(GODOT),'--headless','--path',str(project),'--',str(out/'native-play.json')],'native-play')
 proof=json.loads((out/'native-play.json').read_bytes());assert proof['ok'] and gone(proof['runtime_pid']) and gone(proof['owner_pid']);print('Native scene Play passed',flush=True)
 run([str(GODOT),'--headless','--editor','--path',str(project),'--','--xace-editor-proof',str(out/'editor-player.json')],'editor-play')
 editor=json.loads((out/'editor-player.json.editor.json').read_bytes());editor_player=json.loads((out/'editor-player.json').read_bytes());assert editor['ok'] and editor['real_editor_play'] and editor_player['ok'] and gone(editor_player['runtime_pid']) and gone(editor_player['owner_pid'])
 print('Actual EditorInterface Play passed',flush=True)
 template=ROOT/'evidence/nec014/20261025/export-preflight-f/windows_release_x86_64.exe'
 preset='[preset.0]\nname="Windows Desktop"\nplatform="Windows Desktop"\nrunnable=true\nexport_filter="all_resources"\ninclude_filter="xace-native-profile.json"\nexclude_filter="release/*"\nscript_export_mode=1\n[preset.0.options]\ncustom_template/release="'+template.as_posix()+'"\nbinary_format/architecture="x86_64"\nbinary_format/embed_pck=false\napplication/modify_resources=false\n'
 (project/'export_presets.cfg').write_text(preset,encoding='utf-8');approve();builds=[]
 for name in ['export','export-repeat']:
  start=time.perf_counter();receipt=export(project,out/name,GODOT);builds.append(dict(output=name,seconds=time.perf_counter()-start,status=receipt['status']))
 (out/'build-times.json').write_bytes(pp.encode(builds))
 game=out/'relocated';shutil.copytree(out/'export/shipping',game);installation=inventory(game);env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 run([str(game/'NativeGame.exe'),'--headless','--',str(out/'export-player.json')],'export-player')
 shipped=json.loads((out/'export-player.json').read_bytes());assert shipped['ok'] and shipped['exported'] and gone(shipped['runtime_pid']) and gone(shipped['owner_pid'])
 assert inventory(game)==installation and inventory(source)==before and all(sha(project/name)==h for name,h in native.items()) and all(sha(ROOT/name)==h for name,h in pins.items())
 (out/'proof.json').write_bytes(pp.encode(dict(ok=True,native_play=proof,exported_player=shipped,source_unchanged=True,native_scene_resources_unchanged=True,installation_unchanged=True,source_stable=True,clean_machine=False,editor_play_button_verified=True,editor_play=editor,builds=builds,full_nec017_complete=False)))
 print('Native Play and relocated export passed',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]))
