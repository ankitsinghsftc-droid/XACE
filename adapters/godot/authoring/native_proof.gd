@tool
extends "authoring_plugin.gd"
## Explicit fixture-only installed-editor proof. Production plugin.cfg never loads this.
var cases: Array = []
var phase := "run"
const PATHS := ["res://Fixture/Template.tscn", "res://Fixture/World.tscn"]

func _enter_tree() -> void:
	super._enter_tree()
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--nec005-phase="): phase = arg.get_slice("=", 1)
	call_deferred("run")

func oid(n: int) -> String: return "%032x" % n

func identity(n: int, kind: String = "object", prefab: Variant = null) -> Dictionary:
	return {"namespace_id": oid(100), "authoring_id": oid(n), "local_id": oid(1000 + n), "generation": "1", "kind": kind, "prefab_id": prefab}

func check(name: String, ok: bool) -> bool:
	cases.append({"name": name, "ok": ok})
	print("NEC005 ", name, " ", ok, " ", reader.error, " ", writer.error)
	return ok

func save(root: Node, path: String) -> bool:
	var packed := PackedScene.new()
	if packed.pack(root) != OK or ResourceSaver.save(packed, path) != OK: return false
	if ResourceLoader.get_resource_uid(path) < 0:
		if ResourceSaver.set_uid(path, ResourceUID.create_id()) != OK: return false
	return true

func write_json(path: String, value: Variant) -> void:
	var w = preload("authoring_wire.gd").new()
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(w.encode(value))
	file.close()

func finish() -> void:
	var ok := not cases.is_empty()
	for item in cases: ok = ok and item.ok
	write_json("res://proof-" + phase + ".json", {"schema": "xace.nec005.godot_proof.v1", "ok": ok, "engine_version": Engine.get_version_info().string, "cases": cases, "reader_error": reader.error, "writer_error": writer.error})
	get_tree().quit(0 if ok else 1)

func load_root(path: String) -> Node:
	return ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)

func request(inventory: Dictionary, edits: Array) -> String:
	return reader.wire.encode({"schema": "xace.godot_authoring_write_request.v1", "expected_inventory_digest": reader.wire.digest(inventory), "edits": edits})

func edit(n: int, fields: Dictionary, path: String = PATHS[1]) -> Dictionary:
	return {"document": path, "authoring_id": oid(n), "fields": fields}

func undo_transaction(prepared: Dictionary) -> Dictionary:
	return writer.rollback(prepared.directory, FileAccess.get_sha256(prepared.directory + "/receipt.json"), PATHS)

func run() -> void:
	await get_tree().create_timer(2.0).timeout
	approve_trusted_project()
	if phase == "reload":
		var recovery: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://restart-recovery.json"))
		check("fresh_process_receipt_recovery", writer.rollback(recovery.directory, recovery.digest, PATHS).get("state") == "rolled_back")
		var native: Dictionary = rescan(PATHS)
		check("cold_editor_capture_identical", reader.wire.encode(native) == FileAccess.get_file_as_string("res://native-before.json"))
		var prepared: Dictionary = writer.prepare(PATHS, FileAccess.get_file_as_string("res://python-request.json"), oid(901))
		if not check("python_request_native_prepare", not prepared.is_empty()):
			finish()
			return
		check("python_request_native_commit", writer.commit(prepared.directory, prepared.approval_digest, PATHS).get("state") == "committed")
		write_json("res://native-after-python.json", rescan(PATHS))
		check("python_native_write_undo", undo_transaction(prepared).get("state") == "rolled_back")
		finish()
		return
	if phase == "play":
		var before: String = FileAccess.get_sha256(PATHS[1])
		EditorInterface.play_custom_scene(PATHS[1])
		await get_tree().create_timer(3.0).timeout
		check("actual_play_active", EditorInterface.is_playing_scene())
		check("play_authoring_capture_refused", rescan(PATHS).is_empty() and not reader.error.is_empty())
		EditorInterface.stop_playing_scene()
		await get_tree().create_timer(2.0).timeout
		check("play_saved_scene_unchanged", FileAccess.get_sha256(PATHS[1]) == before)
		check("saved_capture_after_stop", not rescan(PATHS).is_empty())
		finish()
		return
	DirAccess.make_dir_recursive_absolute("res://Fixture")
	var mesh := BoxMesh.new()
	mesh.size = Vector3(2, 4, 6)
	check("binary_mesh_save", ResourceSaver.save(mesh, "res://Fixture/Mesh.res") == OK)
	ResourceSaver.set_uid("res://Fixture/Mesh.res", ResourceUID.create_id())
	mesh = ResourceLoader.load("res://Fixture/Mesh.res", "", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
	var second := SphereMesh.new()
	ResourceSaver.save(second, "res://Fixture/Replacement.res")
	ResourceSaver.set_uid("res://Fixture/Replacement.res", ResourceUID.create_id())
	var animation := Animation.new()
	ResourceSaver.save(animation, "res://Fixture/Clip.res")
	ResourceSaver.set_uid("res://Fixture/Clip.res", ResourceUID.create_id())
	animation = ResourceLoader.load("res://Fixture/Clip.res", "", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
	var template := Node3D.new()
	template.name = "Template"
	template.set_meta(reader.META, identity(2, "prefab_definition"))
	var child := MeshInstance3D.new()
	child.name = "Visual"
	child.mesh = mesh
	child.set_meta(reader.META, identity(6))
	template.add_child(child)
	child.owner = template
	check("packed_template_save", save(template, PATHS[0]))
	template.free()
	var root := Node.new()
	root.name = "World"
	root.set_meta(reader.META, identity(1, "scene"))
	var instance := load_root(PATHS[0])
	instance.name = "Ordinary Name"
	root.add_child(instance)
	instance.owner = root
	root.set_editable_instance(instance, true)
	instance.set_meta(reader.META, identity(3, "prefab_instance", oid(2)))
	instance.get_child(0).set_meta(reader.META, identity(7))
	instance.set_meta(reader.BINDING, {"input_action": "move", "binding_id": "walk", "event_name": "walking", "playback_kind": "Animation", "resource": animation})
	var sibling := Node3D.new()
	sibling.name = "Sibling"
	sibling.position = Vector3(1, 2, 3)
	sibling.set_meta(reader.META, identity(4))
	root.add_child(sibling)
	sibling.owner = root
	var light := OmniLight3D.new()
	light.name = "Lamp"
	light.light_energy = 3.5
	light.set_meta(reader.META, identity(5))
	root.add_child(light)
	light.owner = root
	check("scene_nested_instance_save", save(root, PATHS[1]))
	root.free()
	var inventory: Dictionary = rescan(PATHS)
	if not check("saved_native_capture", inventory.get("objects", {}).size() == 7):
		finish()
		return
	write_json("res://native-before.json", inventory)
	var no_trust = Reader.new()
	check("unapproved_project_refused", no_trust.capture(PATHS).is_empty())
	check("path_traversal_refused", reader.capture(["res://Fixture/../Fixture/World.tscn"]).is_empty())
	reader.wire.error = ""
	check("duplicate_json_key_refused", reader.wire.decode('{"a":true,"a":false}').is_empty() and not reader.wire.error.is_empty())
	reader.wire.error = ""
	check("numeric_json_token_refused", reader.wire.decode('{"a":1}').is_empty() and not reader.wire.error.is_empty())
	reader.wire.error = ""
	root = load_root(PATHS[1])
	check("binary_scene_save", save(root, "res://Fixture/World.scn"))
	root.free()
	check("binary_scene_capture", reader.capture([PATHS[0], "res://Fixture/World.scn"]).get("objects", {}).size() == 7)
	var binary_paths := [PATHS[0], "res://Fixture/World.scn"]
	var binary_inventory: Dictionary = reader.capture(binary_paths)
	var binary_write: Dictionary = writer.prepare(binary_paths, request(binary_inventory, [edit(4, {"transform.position": {"x": "7000000", "y": "0", "z": "0"}}, binary_paths[1])]), oid(830))
	check("binary_scene_staged_save", not binary_write.is_empty() and writer.commit(binary_write.directory, binary_write.approval_digest, binary_paths).get("state") == "committed")
	check("binary_scene_saved_readback", reader.capture(binary_paths).objects[oid(4)].fields["transform.position"].x == "7")
	if not binary_write.is_empty(): check("binary_scene_restore", writer.rollback(binary_write.directory, FileAccess.get_sha256(binary_write.directory + "/receipt.json"), binary_paths).get("state") == "rolled_back")
	inventory = rescan(PATHS)
	check("binary_resource_uid_reference", inventory.objects[oid(7)].fields["presentation.asset"].resolved_path == "res://Fixture/Mesh.res")
	check("instance_definition_distinct", inventory.objects[oid(3)].prefab_id == oid(2) and inventory.objects[oid(7)].parent_id == oid(3))
	var before := FileAccess.get_sha256(PATHS[1])
	var discover: Dictionary = reader.capture(PATHS, true)
	check("discovery_preserves_saved_bytes", not discover.is_empty() and FileAccess.get_sha256(PATHS[1]) == before)
	write_json("res://native-discovery.json", discover)
	var project_before := FileAccess.get_file_as_bytes("res://project.godot")
	var project_with_behavior := project_before.duplicate()
	project_with_behavior.append_array('\n[autoload]\nForeignBehavior="*res://unmapped.gd"\n'.to_utf8_buffer())
	writer.write_bytes("res://project.godot", project_with_behavior)
	check("project_autoload_blocks_adoption", rescan(PATHS).objects[oid(1)].opaque[0].critical)
	writer.write_bytes("res://project.godot", project_before)
	check("autoload_probe_restores_project_bytes", FileAccess.get_file_as_bytes("res://project.godot") == project_before)
	EditorInterface.open_scene_from_path(PATHS[1])
	await get_tree().process_frame
	root = EditorInterface.get_edited_scene_root()
	check("open_scene_capture_refused", rescan(PATHS).is_empty())
	var target: Node = root.get_node("Sibling")
	var old: Dictionary = target.get_meta(reader.META)
	check("explicit_duplicate_rekey_group", enroll(target, identity(44), old))
	var history := get_undo_redo().get_history_undo_redo(get_undo_redo().get_object_history_id(target))
	history.undo()
	check("editor_undo_restores_identity", target.get_meta(reader.META) == old)
	history.redo()
	check("editor_redo_rekeys_identity", target.get_meta(reader.META).authoring_id == oid(44))
	history.undo()
	check("editor_native_save", EditorInterface.save_scene() == OK)
	check("editor_close_saved", EditorInterface.close_scene() == OK)
	await get_tree().process_frame
	inventory = rescan(PATHS)
	if not check("editor_save_close_recapture", not inventory.is_empty()):
		finish()
		return
	root = load_root(PATHS[1])
	target = root.get_node("Sibling")
	target.name = "Renamed"
	target.owner = null
	target.reparent(root.get_node("Ordinary Name"), false)
	target.owner = root
	save(root, PATHS[1])
	root.free()
	reader.rescan_required = false
	var renamed: Dictionary = rescan(PATHS)
	check("missed_notification_full_rescan", renamed.objects[oid(4)].name == "Renamed")
	check("rename_reparent_identity_stable", renamed.objects[oid(4)].locator == inventory.objects[oid(4)].locator and renamed.objects[oid(4)].parent_id == oid(3))
	inventory = renamed
	root = load_root(PATHS[1])
	root.get_node("Lamp").set_meta(reader.META, identity(4))
	var clean := FileAccess.get_file_as_bytes(PATHS[1])
	save(root, PATHS[1])
	root.free()
	check("duplicate_metadata_refused", rescan(PATHS).is_empty() and "duplicate" in reader.error)
	writer.write_bytes(PATHS[1], clean)
	inventory = rescan(PATHS)
	var prepared: Dictionary = writer.prepare(PATHS, request(inventory, [edit(4, {"transform.position": {"x": "8000000", "y": "2000000", "z": "3000000"}})]), oid(800))
	if not check("staged_native_serialization", not prepared.is_empty()):
		finish()
		return
	check("prepare_original_unchanged", FileAccess.get_file_as_bytes(PATHS[1]) == clean)
	check("approval_digest_refused", writer.commit(prepared.directory, "0".repeat(64), PATHS).is_empty())
	check("native_commit", writer.commit(prepared.directory, prepared.approval_digest, PATHS).get("state") == "committed")
	var after: Dictionary = rescan(PATHS)
	check("save_reextract_position", after.objects[oid(4)].fields["transform.position"].x == "8")
	root = load_root(PATHS[1])
	check("unknown_light_property_preserved", root.get_node("Lamp").light_energy == 3.5)
	check("packed_scene_reference_preserved", root.get_node("Ordinary Name").scene_file_path == PATHS[0])
	root.free()
	check("receipt_reload_recovery", undo_transaction(prepared).get("state") == "rolled_back")
	check("rollback_exact_saved_bytes", FileAccess.get_file_as_bytes(PATHS[1]) == clean)
	var golden: Array = JSON.parse_string(FileAccess.get_file_as_string("res://godot-golden.json"))
	for g in golden:
		var golden_prepared: Dictionary = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, {"transform." + g.kind: g.expected})]), oid(810 if g.kind == "position" else 811))
		if g.kind == "position":
			check("shared_golden_native_position", not golden_prepared.is_empty() and writer.commit(golden_prepared.directory, golden_prepared.approval_digest, PATHS).get("state") == "committed")
			if not golden_prepared.is_empty(): check("shared_golden_restore", undo_transaction(golden_prepared).get("state") == "rolled_back")
		else: check("shared_golden_inexact_rotation_refused", golden_prepared.is_empty())
	var exact_fields := {"transform.rotation": {"x": "0", "y": "0", "z": "1000000", "w": "0"}, "transform.scale": {"x": "2000000", "y": "2000000", "z": "2000000"}}
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, exact_fields), edit(3, {"input.action": "jump"})]), oid(812))
	if not check("exact_rotation_scale_input_prepare", not prepared.is_empty()):
		finish()
		return
	check("exact_rotation_scale_input_commit", writer.commit(prepared.directory, prepared.approval_digest, PATHS).get("state") == "committed")
	check("input_and_binding_preserved", rescan(PATHS).objects[oid(3)].fields["input.action"] == "jump" and rescan(PATHS).objects[oid(3)].fields.has("binding.playback"))
	check("exact_fields_undo", undo_transaction(prepared).get("state") == "rolled_back")
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, {"transform.position": {"x": "9000000", "y": "2000000", "z": "3000000"}})]), oid(801))
	check("fault_after_replace_rollback", not prepared.is_empty() and writer.commit(prepared.directory, prepared.approval_digest, PATHS, 0).get("state") == "rolled_back")
	check("fault_preserves_before_image", FileAccess.get_file_as_bytes(PATHS[1]) == clean)
	var replacement: Resource = ResourceLoader.load("res://Fixture/Replacement.res", "", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(7, {"presentation.asset": reader.asset(replacement)})]), oid(802))
	if not check("binary_resource_replacement_prepare", not prepared.is_empty()):
		finish()
		return
	check("binary_resource_replacement_commit", writer.commit(prepared.directory, prepared.approval_digest, PATHS).get("state") == "committed")
	after = rescan(PATHS)
	check("resource_replace_preserves_instance_identity", after.objects[oid(7)].locator == inventory.objects[oid(7)].locator and after.objects[oid(7)].fields["presentation.asset"].resolved_path == "res://Fixture/Replacement.res")
	check("resource_replacement_rollback", undo_transaction(prepared).get("state") == "rolled_back")
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, {"transform.position": {"x": "1", "y": "0", "z": "0"}})]), oid(803))
	check("unrepresentable_fixed_value_refused", prepared.is_empty())
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, {"transform.position": {"x": "10000000", "y": "0", "z": "0"}})]), oid(804))
	if not check("conflict_fixture_prepare", not prepared.is_empty()):
		finish()
		return
	writer.commit(prepared.directory, prepared.approval_digest, PATHS)
	var newer := FileAccess.get_file_as_bytes(PATHS[1])
	newer.append_array("\n; external edit\n".to_utf8_buffer())
	writer.write_bytes(PATHS[1], newer)
	check("newer_edit_recovery_conflict", undo_transaction(prepared).get("state") == "recovery_conflict")
	check("newer_edit_retained", FileAccess.get_file_as_bytes(PATHS[1]) == newer)
	# Explicit fixture reset, never automatic conflict resolution in production.
	writer.write_bytes(PATHS[1], clean)
	root = load_root(PATHS[1])
	var unknown := AudioStreamPlayer.new()
	unknown.name = "UnknownBehavior"
	unknown.set_meta(reader.META, identity(8))
	root.add_child(unknown)
	unknown.owner = root
	save(root, PATHS[1])
	root.free()
	var blocked: Dictionary = rescan(PATHS)
	check("unknown_behavior_blocking_disposition", blocked.objects[oid(8)].opaque[0].critical)
	write_json("res://native-unknown.json", blocked)
	prepared = writer.prepare(PATHS, request(blocked, [edit(4, {"transform.position": {"x": "5000000", "y": "0", "z": "0"}})]), oid(820))
	check("unknown_behavior_native_preservation_commit", not prepared.is_empty() and writer.commit(prepared.directory, prepared.approval_digest, PATHS).get("state") == "committed")
	root = load_root(PATHS[1])
	check("unknown_behavior_retained", root.get_node("UnknownBehavior") is AudioStreamPlayer)
	root.free()
	if not prepared.is_empty(): check("unknown_behavior_write_undo", undo_transaction(prepared).get("state") == "rolled_back")
	writer.write_bytes(PATHS[1], clean)
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, {"transform.position": {"x": "5000000", "y": "0", "z": "0"}})]), oid(821))
	var external := clean.duplicate()
	external.append_array("\n; newer native source\n".to_utf8_buffer())
	writer.write_bytes(PATHS[1], external)
	check("source_drift_refuses_approved_write", not prepared.is_empty() and writer.commit(prepared.directory, prepared.approval_digest, PATHS).is_empty())
	check("source_drift_keeps_newer_bytes", FileAccess.get_file_as_bytes(PATHS[1]) == external)
	writer.write_bytes(PATHS[1], clean)
	write_json("res://native-before.json", rescan(PATHS))
	prepared = writer.prepare(PATHS, request(rescan(PATHS), [edit(4, {"transform.position": {"x": "6000000", "y": "0", "z": "0"}})]), oid(840))
	if check("restart_recovery_prepare", not prepared.is_empty()):
		check("restart_recovery_commit", writer.commit(prepared.directory, prepared.approval_digest, PATHS).get("state") == "committed")
		write_json("res://restart-recovery.json", {"directory": prepared.directory, "digest": FileAccess.get_sha256(prepared.directory + "/receipt.json")})
	finish()
