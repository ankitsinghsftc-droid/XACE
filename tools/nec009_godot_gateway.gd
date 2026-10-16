@tool
extends "res://addons/xace_authoring/authoring_plugin.gd"
## Explicit NEC-009 copied-fixture proof only; never a production plugin entry.
const PATHS := ["res://Fixture/Template.tscn", "res://Fixture/World.tscn"]

func _enter_tree() -> void:
	super._enter_tree()
	call_deferred("run_proof")

func run_proof() -> void:
	await get_tree().create_timer(2.0).timeout
	approve_trusted_project()
	var command: Dictionary = reader.wire.decode(FileAccess.get_file_as_string("res://nec009-command.json"))
	var result := {}
	match command.action:
		"capture": result = {"inventory": rescan(PATHS)}
		"prepare": result = writer.prepare(PATHS, reader.wire.encode(command.request), command.transaction_id)
		"commit": result = writer.commit(command.prepared.directory, command.prepared.approval_digest, PATHS)
		"recover": result = writer.rollback(command.prepared.directory, FileAccess.get_sha256(command.prepared.directory + "/receipt.json"), PATHS)
		"inspect":
			var inventory := rescan(PATHS)
			var before := true
			var after := true
			var conflict := inventory.is_empty()
			for row in command.prepared.receipt.rows:
				var current := FileAccess.get_sha256(row.document)
				before = before and current == row.before
				after = after and current == row.after
				conflict = conflict or current not in [row.before, row.after]
				conflict = conflict or FileAccess.get_sha256(row.backup) != row.before or FileAccess.get_sha256(row.stage) != row.after
				if current == row.before: conflict = conflict or reader.fingerprint(row.document) != row.dependency_fingerprint
			result = {"state": "conflict" if conflict else "after" if after else "before" if before else "partial"}
	var ok: bool = not result.is_empty() and reader.error.is_empty() and writer.error.is_empty() and reader.wire.error.is_empty()
	var output := {"ok": ok, "result": result, "reader_error": reader.error, "writer_error": writer.error, "version": Engine.get_version_info().string}
	var file := FileAccess.open("res://nec009-result.json", FileAccess.WRITE)
	file.store_string(reader.wire.encode(output))
	file.close()
	get_tree().quit(0 if ok else 1)
