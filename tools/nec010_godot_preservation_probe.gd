@tool
extends "res://addons/xace_authoring/authoring_plugin.gd"
var cases: Array = []
func check(label: String, ok: bool) -> void:
	cases.append({"name": label, "ok": ok})
func _enter_tree() -> void:
	super._enter_tree()
	call_deferred("run_proof")
func run_proof() -> void:
	await get_tree().create_timer(2.0).timeout
	approve_trusted_project()
	var path := "res://Fixture/World.tscn"
	var root: Node = reader.load_scene(path).instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	var target: Node3D
	for node in reader.nodes(root):
		if node is Node3D:
			target = node
			break
	var original: Array = reader.opaque(target, "")
	target.position += Vector3(1, 2, 3)
	check("mapped_transform_does_not_change_unowned_digest", reader.opaque(target, "") == original)
	target.set_meta("artist_custom_value", {"nested": ["retained", Vector3(2, 3, 4)]})
	var custom: Array = reader.opaque(target, "")
	check("unknown_stored_metadata_changes_digest", custom != original)
	target.set_meta("artist_custom_value", {"nested": ["changed", Vector3(2, 3, 4)]})
	check("nested_unknown_edit_changes_digest", reader.opaque(target, "") != custom)
	target.remove_meta("artist_custom_value")
	check("native_undo_restores_digest", reader.opaque(target, "") == original)
	target.visible = not target.visible
	check("unknown_native_property_changes_digest", reader.opaque(target, "") != original)
	target.visible = not target.visible
	check("native_redo_restores_property_digest", reader.opaque(target, "") == original)
	root.free()
	var ok: bool = reader.error.is_empty()
	for row in cases: ok = ok and row.ok
	var file := FileAccess.open("res://preservation-proof.json", FileAccess.WRITE)
	file.store_string(reader.wire.encode({"ok": ok, "cases": cases, "error": reader.error}))
	file.close()
	get_tree().quit(0 if ok else 1)
