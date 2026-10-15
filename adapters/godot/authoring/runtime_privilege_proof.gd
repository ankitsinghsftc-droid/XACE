extends SceneTree
## Explicit installed non-editor fixture process; not attached to shipped scenes.
func _initialize() -> void:
	var reader = preload("authoring_reader.gd").new()
	reader.trusted_project = true
	var observed: Dictionary = reader.capture(["res://Fixture/World.tscn"])
	var protocol = load("res://xace_protocol.gd")
	var cases := [
		{"name": "actual_non_editor_process", "ok": not Engine.is_editor_hint()},
		{"name": "runtime_cannot_gain_authoring_privilege", "ok": observed.is_empty() and reader.error == "pinned editor privilege required"},
		{"name": "unchanged_shared_runtime_protocol_loads", "ok": protocol != null and protocol.can_instantiate() and protocol.PROTOCOL_VERSION == 1}
	]
	var ok := true
	for row in cases: ok = ok and row.ok
	var wire = preload("authoring_wire.gd").new()
	var file := FileAccess.open("res://proof-privilege.json", FileAccess.WRITE)
	file.store_string(wire.encode({"schema": "xace.nec005.godot_proof.v1", "ok": ok, "engine_version": Engine.get_version_info().string, "cases": cases}))
	file.close()
	quit(0 if ok else 1)
