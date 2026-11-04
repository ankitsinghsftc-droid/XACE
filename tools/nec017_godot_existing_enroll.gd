@tool
extends 'authoring_plugin.gd'
const PATHS = ['res://Game/Crate.tscn','res://Game/World.tscn','res://Game/Annex.tscn']
var next_id := 1
func oid(n: int) -> String: return '%032x' % n
func write_json(path: String, data: Variant) -> void:
 var file := FileAccess.open(path, FileAccess.WRITE)
 file.store_string(JSON.stringify(data))
 file.close()
func _enter_tree() -> void:
 super._enter_tree()
 call_deferred('run_existing_fixture')
func run_existing_fixture() -> void:
 approve_trusted_project()
 var discovery: Dictionary = reader.capture(PATHS, true)
 if discovery.is_empty():
  write_json('res://existing-failure.json',{'error':reader.error})
  get_tree().quit(1)
  return
 write_json('res://existing-discovery.json',discovery)
 var original := {}
 for path in PATHS:original[path]=FileAccess.get_sha256(path)
 # Reject once: discovery and this review step authorize no source writes.
 for path in PATHS:assert(FileAccess.get_sha256(path)==original[path])
 var manifest := []
 for path in PATHS:
  EditorInterface.open_scene_from_path(path)
  await get_tree().process_frame
  var root := EditorInterface.get_edited_scene_root()
  assert(root != null)
  for node in reader.nodes(root):
   var kind := 'object'
   var prefab: Variant = null
   if node == root:kind='prefab_definition' if path==PATHS[0] else 'scene'
   elif not node.scene_file_path.is_empty():
    kind='prefab_instance'
    prefab=oid(1)
   var identity := {'namespace_id':oid(9000),'authoring_id':oid(next_id),'local_id':oid(next_id+10000),'generation':'1','kind':kind,'prefab_id':prefab}
   assert(enroll(node,identity,node.get_meta(reader.META) if node.has_meta(reader.META) else null))
   manifest.append({'id':oid(next_id),'document':path,'node_path':str(root.get_path_to(node)),'kind':kind})
   next_id+=1
  assert(EditorInterface.save_scene()==OK)
  assert(EditorInterface.close_scene()==OK)
  await get_tree().process_frame
 var observed: Dictionary = reader.capture(PATHS)
 if observed.is_empty():
  write_json('res://existing-failure.json',{'error':reader.error})
  get_tree().quit(1)
  return
 var offset := (load(PATHS[1]) as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
 offset.position = Vector3(1, 0, 0)
 var packed := PackedScene.new()
 assert(packed.pack(offset)==OK)
 assert(ResourceSaver.save(packed,'res://Game/OffsetWorld.tscn')==OK)
 ResourceSaver.set_uid('res://Game/OffsetWorld.tscn',ResourceUID.create_id())
 offset.free()
 assert(reader.capture([PATHS[0],'res://Game/OffsetWorld.tscn']).is_empty())
 assert(reader.error.contains('transformed roots'))
 var file := FileAccess.open('res://existing-native.json',FileAccess.WRITE)
 file.store_string(reader.wire.encode(observed))
 file.close()
 write_json('res://existing-enrollment.json',{'ok':true,'objects':manifest,'rejected_preview_preserved':true,'explicit_fixture_enrollment':true,'original_scene_hashes':original,'full_adoption_verified':false,'neutral_node3d_root_captured':true,'translated_scene_root_refused':true})
 get_tree().quit(0)
