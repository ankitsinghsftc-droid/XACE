@tool
extends RefCounted
const Reader = preload("authoring_reader.gd")
const Writer = preload("authoring_writer.gd")
func run(path: String) -> bool:
	var reader = Reader.new()
	var writer = Writer.new()
	reader.trusted_project = true
	writer.reader.trusted_project = true
	if not path.begins_with("res://.xace/native-authoring-calls/") or not path.ends_with("/command.json") or ".." in path or "\\" in path: return false
	var output := path.get_base_dir() + "/result.json"
	if FileAccess.file_exists(output): return false
	var config: Dictionary = reader.wire.decode(FileAccess.get_file_as_string("res://.xace/native-authoring-host.json"))
	if config.get("engine") != "godot" or config.get("root") != ProjectSettings.globalize_path("res://").trim_suffix("/"): return false
	var paths: Array = config.get("documents", [])
	var command: Dictionary = reader.wire.decode(FileAccess.get_file_as_string(path))
	var result := {}
	match command.get("action"):
		"capture": result = reader.capture(paths)
		"prepare": result = writer.prepare(paths, reader.wire.encode(command.get("request")), command.get("transaction_id", ""))
		"commit": result = writer.commit(command.prepared.directory, command.prepared.approval_digest, paths)
		"recover": result = writer.rollback(command.prepared.directory, FileAccess.get_sha256(command.prepared.directory + "/receipt.json"), paths)
	var ok: bool = not result.is_empty() and reader.error.is_empty() and writer.error.is_empty() and reader.wire.error.is_empty()
	var file := FileAccess.open(output, FileAccess.WRITE)
	if file == null: return false
	file.store_string(reader.wire.encode({"ok": ok, "result": result, "error": reader.error + writer.error}))
	file.flush()
	file.close()
	return ok
