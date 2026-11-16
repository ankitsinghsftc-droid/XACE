"""Three native data rebuilds at1,000 bound objects; no rendered/gameplay scale claim."""
from pathlib import Path
import json,shutil,subprocess,sys,os,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.nec014_export import inventory,sha
from tools.nec014_export_proof import GODOT
from tools.nec017_process_metrics import memory,DescendantMemory
PROBE=r'''extends Node
func _ready() -> void: call_deferred("inspect_scene")
func inspect_scene() -> void:
 var expected=JSON.parse_string(FileAccess.get_file_as_string("res://scale-expected.json"))
 var scene=get_tree().current_scene
 var ok=expected.size()==1000 and scene.get_child_count()==1000
 for id in expected:
  var node=scene.get_node_or_null(NodePath(id))
  if not node is Node3D: ok=false;continue
  var value=expected[id]
  ok=ok and node.global_position.distance_to(Vector3(value[0],value[1],value[2]))<0.00001 and node.scale.is_equal_approx(Vector3.ONE) and node.quaternion.is_equal_approx(Quaternion.IDENTITY)
 var result={"ok":ok,"objects":expected.size(),"exported":not OS.has_feature("editor"),"scene":scene.scene_file_path,"profile":"static serialized transform nodes; no XACE gameplay runtime or graphics workload"}
 FileAccess.open(OS.get_cmdline_user_args()[0],FileAccess.WRITE).store_string(JSON.stringify(result))
 get_tree().quit(0 if ok else 1)
'''
def main(out):
 out=out.resolve();assert out.is_relative_to(ROOT/'evidence/nec017') and not out.exists() and shutil.disk_usage(ROOT).free>3*1024**3;out.mkdir(parents=True)
 seed=ROOT/'evidence/nec017/20261028/godot-scale-a';source=seed/'godot-project';original=inventory(source);project=out/'project';shutil.copytree(source,project,ignore=shutil.ignore_patterns('.godot','.git'))
 scene='XACEGenerated/World.tscn';scene_hash=sha(project/scene);cgs=json.loads((seed/'source.cgs.json').read_bytes());expected={actor['id']:[actor['components'][0]['defaults']['position'][axis]/1000000 for axis in ['x','y','z']] for actor in cgs['modes'][0]['actors']};assert len(expected)==1000
 (project/'scale-expected.json').write_text(json.dumps(expected,sort_keys=True));(project/'scale-probe.gd').write_text(PROBE,encoding='utf-8')
 (project/'project.godot').write_text('config_version=5\n[application]\nconfig/name="NEC017 scale rebuild"\nrun/main_scene="res://'+scene+'"\n[autoload]\nScaleObserver="*res://scale-probe.gd"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n',encoding='utf-8')
 template=ROOT/'evidence/nec014/20261025/export-preflight-f/windows_release_x86_64.exe'
 preset='[preset.0]\nname="Windows Desktop"\nplatform="Windows Desktop"\nrunnable=true\nexport_filter="all_resources"\ninclude_filter="scale-expected.json"\nscript_export_mode=1\n[preset.0.options]\ncustom_template/release="'+template.as_posix()+'"\nbinary_format/architecture="x86_64"\nbinary_format/embed_pck=false\napplication/modify_resources=false\n';(project/'export_presets.cfg').write_text(preset,encoding='utf-8');approved=inventory(project);(out/'source-before-import.json').write_text(json.dumps(approved,sort_keys=True,indent=2));env=dict(os.environ);env['LOCALAPPDATA']=str(out/'user-data')
 def run(command,name):
  started=time.perf_counter();(out/(name+'-command.json')).write_text(json.dumps(command,indent=2))
  with (out/(name+'.log')).open('wb') as log:
   process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);tree=DescendantMemory(process.pid)
   try:
    while process.poll() is None:
     tree.sample()
     if shutil.disk_usage(ROOT).free<2*1024**3 or time.perf_counter()-started>180:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True);raise RuntimeError('Owned process reserve/timeout reached; files retained')
     time.sleep(.1)
    root_memory=memory(int(process._handle));tree.sample();result=dict(seconds=time.perf_counter()-started,returncode=process.returncode,root_memory=root_memory,descendants=list(tree.rows.values()),sampled_descendant_peak_bytes=tree.sampled_peak,sampling_ms=100,aggregate_peak_exact=False)
   finally:tree.close()
  (out/(name+'-metrics.json')).write_text(json.dumps(result,indent=2));assert process.returncode==0,name+' failed; log retained';return result
 run([str(GODOT),'--headless','--editor','--path',str(project),'--import'],'import');approved=inventory(project);(out/'source-pins.json').write_text(json.dumps(approved,sort_keys=True,indent=2));samples=[]
 for n in range(3):
  target=out/('build-'+str(n));target.mkdir();metric=run([str(GODOT),'--headless','--path',str(project),'--export-release','Windows Desktop',str(target/'Scale.exe')],'build-'+str(n))
  report=out/('player-'+str(n)+'.json');run([str(target/'Scale.exe'),'--headless','--',str(report)],'player-'+str(n));value=json.loads(report.read_bytes());assert value['ok'] and value['exported'] and value['objects']==1000 and sha(project/scene)==scene_hash and inventory(project)==approved and inventory(source)==original
  samples.append(dict(build=n,measurement=metric,player=value,output_bytes=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())));print(json.dumps(dict(build=n,objects=1000,seconds=metric['seconds'],ok=True)),flush=True)
 (out/'proof.json').write_text(json.dumps(dict(ok=True,engine='Godot4.6.3',objects=1000,rebuilds=3,samples=samples,original_unchanged=True,scene_bytes_unchanged=True,source_unchanged=True,scale_scope='Native serialized transform-node rebuild/readback only; authoring/edit/recovery measured separately',gameplay_runtime_scale_certified=False,graphics_scale_certified=False,full_nec017_complete=False),indent=2))
if __name__=='__main__':main(Path(sys.argv[1]))
