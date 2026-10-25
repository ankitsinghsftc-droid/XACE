"""Fresh saved native Godot scene and actual Windows export proof."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import export,sha,inventory
from tools.nec013_unity_player_proof import gone
GODOT=Path('C:/Users/ankit/Downloads/Godot_v4.6.3-stable_win64.exe/Godot_v4.6.3-stable_win64_console.exe')
TEMPLATE=Path('C:/Users/ankit/Downloads/xace/tmp/xp008-export/windows_release_x86_64.exe')
def main(out,release_source=None):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec014') and not out.exists();project=out/'project';project.mkdir(parents=True)
 for p in (ROOT/'adapters/godot').glob('*.gd'):shutil.copyfile(p,project/p.name)
 shutil.copyfile(ROOT/'tools/nec014_export_probe.gd',project/'probe.gd')
 shutil.copytree(ROOT/'adapters/godot/native_export',project/'addons/xace_native_shipping')
 (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Existing Native Game"\nrun/main_scene="res://NativeGame.tscn"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[editor_plugins]\nenabled=PackedStringArray("res://addons/xace_native_shipping/plugin.cfg")\n',encoding='utf-8')
 (project/'NativeGame.tscn').write_text('[gd_scene load_steps=3 format=3]\n[ext_resource type="Script" path="res://probe.gd" id="1"]\n[ext_resource type="Script" path="res://xace_native_host.gd" id="2"]\n[node name="ExistingGame" type="Node3D"]\nscript=ExtResource("1")\n[node name="Existing0" type="Node3D" parent="."]\nposition=Vector3(2,0,0)\n[node name="Existing1" type="Node3D" parent="Existing0"]\nposition=Vector3(5,0,0)\n[node name="NativeHost" type="Node" parent="."]\nscript=ExtResource("2")\n',encoding='utf-8')
 release=project/'release';shutil.copytree(release_source or ROOT/'evidence/nec012/20261024/engine-claims-listener-final/Godot/release',release)
 shutil.copyfile(ROOT/'evidence/nec012/20261024/lifecycle-listener-final/xace-player-launcher.exe',release/'xace-player-launcher.exe')
 world=json.loads((release/'package/world.json').read_bytes())
 profile=dict(schema='xace.godot.native_profile.v1',game_id='nec012-proof',release_directory='release',release_sha256=sha(release/'native-release.json'),launcher_sha256=sha(release/'xace-player-launcher.exe'),controller_id=1,objects={o['id']:['../Existing0','../Existing0/Existing1'][i] for i,o in enumerate(world['objects'])},input_bindings=[dict(action='move_x',kind='axis_1d',native_selector='proof.move')])
 if release_source:
  profile['input_bindings'].append(dict(action='jump',kind='button',native_selector='proof.jump'))
  scene=(project/'NativeGame.tscn').read_text(encoding='utf-8').replace('load_steps=3','load_steps=5').replace('[node name="ExistingGame"','[sub_resource type="Animation" id="Anim"]\nlength=1.0\n[sub_resource type="AnimationLibrary" id="Lib"]\n_data={"play":SubResource("Anim")}\n[node name="ExistingGame"').replace('position=Vector3(2,0,0)','position=Vector3(2,-1,0)').replace('position=Vector3(5,0,0)','position=Vector3(5,1,0)')
  for parent in ['Existing0','Existing0/Existing1']:scene+='[node name="AnimationPlayer" type="AnimationPlayer" parent="'+parent+'"]\nlibraries={&"":SubResource("Lib")}\n'
  (project/'NativeGame.tscn').write_text(scene,encoding='utf-8')
  (project/'tone.tres').write_text('[gd_resource type="AudioStreamWAV" format=3]\n[resource]\nformat=0\nmix_rate=8000\nstereo=false\ndata=PackedByteArray('+','.join(['128']*8000)+')\n',encoding='utf-8')
 (project/'xace-native-profile.json').write_text(json.dumps(profile),encoding='utf-8')
 # Preserve a durable template copy; the existing disposable source is read-only.
 shutil.copyfile(TEMPLATE,out/'windows_release_x86_64.exe')
 preset='[preset.0]\nname="Windows Desktop"\nplatform="Windows Desktop"\nrunnable=true\nexport_filter="all_resources"\ninclude_filter="xace-native-profile.json"\nexclude_filter="release/*"\nscript_export_mode=1\n[preset.0.options]\ncustom_template/release="'+(out/'windows_release_x86_64.exe').as_posix()+'"\nbinary_format/architecture="x86_64"\nbinary_format/embed_pck=false\napplication/modify_resources=false\n'
 (project/'export_presets.cfg').write_text(preset,encoding='utf-8')
 env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 with (out/'import.log').open('wb') as log:r=subprocess.run([str(GODOT),'--headless','--path',str(project),'--editor','--import'],stdout=log,stderr=subprocess.STDOUT,timeout=120,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0
 (project/'XACEApproval.json').write_text(json.dumps(dict(schema='xace.godot.source_approval.v1',godot='4.6.3-stable (official)',files=inventory(project)),indent=2),encoding='utf-8')
 receipt=export(project,out/'export',GODOT);assert receipt['status']=='built-not-certified'
 game=out/'relocated';shutil.copytree(out/'export/shipping',game);before=inventory(game)
 env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
 command=[str(game/'NativeGame.exe'),'--headless','--',str(out/'player.json')]
 (out/'command.json').write_text(json.dumps(command,indent=2),encoding='utf-8')
 with (out/'player.log').open('wb') as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
 assert r.returncode==0,(out/'player.log').read_text(encoding='utf-8')
 proof=json.loads((out/'player.json').read_text(encoding='utf-8'));proof.update(install_unchanged=before==inventory(game),process_cleanup=gone(proof['runtime_pid']) and gone(proof['owner_pid']),clean_machine=False)
 proof['ok'] &= proof['install_unchanged'] and proof['process_cleanup'] and proof['exported'];(out/'proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');assert proof['ok'],proof;print(json.dumps(proof))
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]) if len(sys.argv)>2 else None)
