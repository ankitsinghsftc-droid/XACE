extends SceneTree
# Explicit test-fixture migration, never applied to a developer's project.
func _init() -> void:
 var path := "res://Game/World.tscn"
 var before := FileAccess.get_sha256(path)
 # A fresh command-line project has no imported UID cache yet. Preserve the
 # existing text-scene UID explicitly while using ResourceSaver for the edit.
 var header := FileAccess.get_file_as_string(path).get_slice("\n",0)
 var uid_text := header.get_slice('uid="',1).get_slice('"',0)
 var original_uid := ResourceUID.text_to_id(uid_text)
 if original_uid < 0:
  push_error("original scene UID missing");quit(1);return
 var scene := (load(path) as PackedScene).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
 var dispositions := []
 for node_path in ["NativeAudio", "NativeAnimation", "UnsupportedCriticalScore"]:
  var node := scene.get_node(node_path)
  dispositions.append({"path":node_path,"class":node.get_class(),"action":"remove_native_authority_from_copied_fixture","script":node.get_script().resource_path if node.get_script()!=null else ""})
  scene.remove_child(node)
  node.free()
 var packed := PackedScene.new()
 assert(packed.pack(scene)==OK)
 assert(ResourceSaver.save(packed,path)==OK)
 assert(ResourceSaver.set_uid(path,original_uid)==OK)
 var report := {"ok":true,"before":before,"after":FileAccess.get_sha256(path),"dispositions":dispositions,"automatic_gameplay_conversion":false,"original_project_preserved_externally":true,"native_resources_and_script_files_retained":true}
 var output := FileAccess.open("res://explicit-disposition.json",FileAccess.WRITE)
 output.store_string(JSON.stringify(report));output.close()
 scene.free();quit(0)
