@tool
extends EditorPlugin
## Enabled only in an explicitly configured fresh native staging project.
func _enter_tree() -> void:
	call_deferred("_create_stage")
func _create_stage() -> void:
	if FileAccess.file_exists("res://.xace/result-create.json"):
		get_tree().quit(2)
		return
	var factory = preload("native_setup.gd").new()
	var spec: Dictionary = factory.reader.wire.decode(FileAccess.get_file_as_string("res://.xace/spec.json"))
	var result: Dictionary = factory.create(spec, factory.reader.wire.digest(spec))
	var file := FileAccess.open("res://.xace/result-create.json", FileAccess.WRITE)
	if file == null:
		get_tree().quit(1)
		return
	file.store_string(factory.reader.wire.encode({"ok": not result.is_empty(), "result": result, "error": factory.error}))
	file.flush()
	file.close()
	get_tree().quit(0 if not result.is_empty() else 1)
