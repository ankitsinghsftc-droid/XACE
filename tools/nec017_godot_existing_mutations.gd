@tool
extends 'authoring_plugin.gd'
# Test-only native operations on a new disposable fixture copy; never a user project.
const PATHS=['res://Game/Crate.tscn','res://Game/World.tscn','res://Game/Annex.tscn']
var phase=''
func _enter_tree() -> void:
 super._enter_tree()
 for arg in OS.get_cmdline_user_args():
  if arg.begins_with('--nec017-mutation='):phase=arg.trim_prefix('--nec017-mutation=');call_deferred('mutate')
func store(path: String,value: Variant) -> void:
 var f=FileAccess.open(path,FileAccess.WRITE);f.store_string(reader.wire.encode(value));f.close()
func capture(paths: Array) -> Dictionary:
 reader.error='';return reader.capture(paths)
func mutate() -> void:
 await get_tree().create_timer(1.0).timeout
 approve_trusted_project()
 # This newly created private fixture has no unsaved user edits. Close its startup-restored saved scenes before the production saved-capture API.
 for opened in EditorInterface.get_open_scenes():
  assert(opened in PATHS)
  assert(EditorInterface.close_scene()==OK)
 await get_tree().process_frame
 var before=capture(PATHS)
 if before.is_empty():
  store('res://mutation-'+phase+'.json',{'ok':false,'capture_error':reader.error,'open_scenes':Array(EditorInterface.get_open_scenes())});get_tree().quit(1);return
 var output={'phase':phase,'ok':false,'before':before}
 if phase=='move':
  var old=PATHS[2];var moved='res://Game/MovedAnnex.tscn';var uid=ResourceLoader.get_resource_uid(old)
  assert(DirAccess.rename_absolute(ProjectSettings.globalize_path(old),ProjectSettings.globalize_path(moved))==OK)
  if uid>=0:ResourceUID.set_id(uid,moved)
  output['after']=capture([PATHS[0],PATHS[1],moved]);output['ok']=not output.after.is_empty()
 else:
  EditorInterface.open_scene_from_path(PATHS[1]);await get_tree().process_frame
  var scene=EditorInterface.get_edited_scene_root();assert(scene!=null)
  if phase=='rename':scene.get_node('Crate1').name='CrateOne'
  elif phase=='reparent':scene.get_node('North/DuplicateDisplayName').reparent(scene.get_node('South'),true)
  elif phase=='delete':
   var node=scene.get_node('Crate49');scene.remove_child(node);node.free()
  elif phase=='duplicate':
   var node=scene.get_node('Crate1').duplicate();scene.add_child(node);node.owner=scene;node.name='DuplicatedCrate'
  else:assert(false,'Unknown native mutation phase')
  EditorInterface.mark_scene_as_unsaved();assert(EditorInterface.save_scene()==OK);assert(EditorInterface.close_scene()==OK);await get_tree().process_frame
  var after=capture(PATHS)
  if phase=='duplicate':
   output['collision_refused']=after.is_empty();output['collision_error']=reader.error;assert(output.collision_refused)
   EditorInterface.open_scene_from_path(PATHS[1]);await get_tree().process_frame
   scene=EditorInterface.get_edited_scene_root();var node=scene.get_node('DuplicatedCrate');var old=node.get_meta(reader.META);var fresh=old.duplicate(true);fresh.authoring_id='%032x'%990001;fresh.local_id='%032x'%990002
   assert(enroll(node,fresh,old));assert(EditorInterface.save_scene()==OK);assert(EditorInterface.close_scene()==OK);await get_tree().process_frame
   after=capture(PATHS);output['explicit_distinct_identity']=not after.is_empty()
  output['after']=after;output['ok']=not after.is_empty()
 output['capture_error']=reader.error
 print('Native workflow capture error: '+reader.error)
 store('res://mutation-'+phase+'.json',output);get_tree().quit(0 if output.ok else 1)
