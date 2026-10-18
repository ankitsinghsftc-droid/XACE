@tool
extends RefCounted
const Reader = preload("authoring_reader.gd")
var reader = Reader.new()
var error := ""

func fail(message: String) -> void:
	if error.is_empty(): error = message

func write_bytes(path: String, bytes: PackedByteArray) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		fail("file preparation failed")
		return false
	file.store_buffer(bytes)
	file.flush()
	file.close()
	return true

func persist(directory: String, receipt: Dictionary) -> bool:
	var text: String = reader.wire.encode(receipt)
	if not reader.wire.error.is_empty():
		fail(reader.wire.error)
		return false
	if not write_bytes(directory + "/receipt.next", text.to_utf8_buffer()): return false
	if DirAccess.rename_absolute(directory + "/receipt.next", directory + "/receipt.json") != OK:
		fail("receipt publication failed; retain transaction directory")
		return false
	return true

func resource(ref: Dictionary) -> Resource:
	if not ref.has_all(["resolved_path", "asset_id", "asset_type", "status"]) or not ref.resolved_path is String or not reader.path_ok(ref.resolved_path):
		fail("invalid native resource reference")
		return null
	var loaded = ResourceLoader.load(ref.resolved_path, "", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
	if not loaded is Resource or reader.asset(loaded) != ref:
		fail("native resource identity/type mismatch")
		return null
	return loaded

func apply(node: Node, fields: Dictionary) -> void:
	for key in fields:
		var value: Variant = fields[key]
		match key:
			"transform.position", "transform.scale", "transform.rotation":
				if not node is Node3D or not value is Dictionary:
					fail("transform target/type mismatch")
					return
				if key == "transform.position": node.position = reader.wire.inverse_vector(value)
				elif key == "transform.scale":
					var scale: Vector3 = reader.wire.inverse_vector(value)
					if scale.x <= 0 or scale.y <= 0 or scale.z <= 0: fail("nonpositive native scale")
					else: node.scale = scale
				else:
					if value.size() != 4 or not value.has_all(["x", "y", "z", "w"]):
						fail("quaternion shape")
						return
					var q := Quaternion(reader.wire.fixed(value.x), reader.wire.fixed(value.y), reader.wire.fixed(value.z), reader.wire.fixed(value.w))
					if abs(q.length_squared() - 1.0) > 0.000004: fail("nonunit quaternion")
					else: node.quaternion = q
			"presentation.asset":
				if not node is MeshInstance3D or not value is Dictionary:
					fail("mesh target/type mismatch")
					return
				var mesh = resource(value)
				if not mesh is Mesh: fail("mesh resource required")
				else: node.mesh = mesh
			"input.action", "binding.playback":
				if not node.has_meta(reader.BINDING):
					fail("explicit native binding required")
					return
				var binding: Dictionary = node.get_meta(reader.BINDING).duplicate()
				if key == "input.action": binding.input_action = value
				else:
					if not value is Dictionary or value.size() != 4 or not value.has_all(["binding_id", "event_name", "playback_kind", "asset"]):
						fail("binding shape")
						return
					binding.binding_id = value.binding_id
					binding.event_name = value.event_name
					binding.playback_kind = value.playback_kind
					binding.resource = resource(value.asset)
				node.set_meta(reader.BINDING, binding)
			_:
				fail("field not writable: " + key)
	if not reader.wire.error.is_empty(): fail(reader.wire.error)
	reader.fields(node)
	if not reader.error.is_empty(): fail(reader.error)

func verify_fields(node: Node, expected: Dictionary) -> bool:
	var actual: Dictionary = reader.fields(node)
	for key in expected:
		if not actual.has(key):
			fail("saved field missing")
			return false
		if key.begins_with("transform."):
			for axis in expected[key]:
				var fixed := roundi(float(actual[key][axis]) * 1000000.0)
				if str(fixed) != expected[key][axis]: fail("saved numeric readback mismatch")
		elif actual[key] != expected[key]: fail("saved native readback mismatch")
	return error.is_empty() and reader.error.is_empty()

func prepare(paths: Array, request_text: String, transaction_id: String) -> Dictionary:
	error = ""
	reader.error = ""
	reader.wire.error = ""
	if not reader.hex_id(transaction_id):
		fail("explicit unique transaction ID required")
		return {}
	var request: Dictionary = reader.wire.decode(request_text)
	if not reader.wire.error.is_empty() or request.size() != 3 or request.get("schema") != "xace.godot_authoring_write_request.v1" or not request.get("edits") is Array:
		fail("invalid canonical writer request")
		return {}
	var inventory: Dictionary = reader.capture(paths)
	if not reader.error.is_empty() or reader.wire.digest(inventory) != request.get("expected_inventory_digest"):
		fail("stale or unavailable saved inventory: " + reader.error)
		return {}
	if request.edits.is_empty() or request.edits.size() > 10000:
		fail("edit count limit")
		return {}
	var grouped := {}
	var seen := {}
	for edit in request.edits:
		if not edit is Dictionary or edit.size() != 3 or not edit.has_all(["document", "authoring_id", "fields"]) or edit.document not in paths or not inventory.objects.has(edit.authoring_id) or not edit.fields is Dictionary or edit.fields.is_empty():
			fail("invalid approved edit scope")
			return {}
		if seen.has(edit.authoring_id) or inventory.objects[edit.authoring_id].path_hint != edit.document:
			fail("duplicate or misbound edit")
			return {}
		seen[edit.authoring_id] = true
		if not grouped.has(edit.document): grouped[edit.document] = []
		grouped[edit.document].append(edit)
	var resource_fingerprints := {}
	for edit in request.edits:
		var refs: Array = []
		if edit.fields.has("presentation.asset"): refs.append(edit.fields["presentation.asset"])
		if edit.fields.has("binding.playback"):
			var playback: Variant = edit.fields["binding.playback"]
			if not playback is Dictionary or not playback.has("asset"):
				fail("invalid playback resource")
				return {}
			refs.append(playback.asset)
		for ref in refs:
			if not ref is Dictionary or not ref.get("resolved_path") is String:
				fail("explicit persistent resource required")
				return {}
			var stamp := reader.fingerprint(ref.resolved_path)
			if stamp.is_empty() or not reader.error.is_empty():
				fail("resource dependency unavailable")
				return {}
			resource_fingerprints[ref.resolved_path] = stamp
	var directory := "res://.xace_authoring/transactions/" + transaction_id
	if not reader.path_ok(directory) or DirAccess.dir_exists_absolute(directory):
		fail("unsafe/reused transaction directory")
		return {}
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		fail("transaction directory unavailable")
		return {}
	write_bytes("res://.xace_authoring/.gdignore", PackedByteArray())
	var receipt := {"schema": "xace.godot_native_transaction.v1", "transaction_id": transaction_id, "state": "prepared", "inventory_digest": request.expected_inventory_digest, "scope": paths.duplicate(), "rows": [], "resource_fingerprints": resource_fingerprints}
	var docs: Array = grouped.keys()
	docs.sort()
	for path in docs:
		var prefix := directory + "/" + str(receipt.rows.size())
		var before: String = FileAccess.get_sha256(path)
		if not write_bytes(prefix + ".before", FileAccess.get_file_as_bytes(path)): return {}
		var packed = reader.load_scene(path)
		if packed == null:
			fail(reader.error)
			return {}
		var root: Node = packed.instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
		var targets := {}
		for node in reader.nodes(root):
			targets[node.get_meta(reader.META, {}).get("authoring_id", "")] = node
		var before_preservation := {}
		for key in targets:
			before_preservation[key] = reader.opaque(targets[key], "")
		var transform_only := true
		for edit in grouped[path]:
			for field in edit.fields:
				if not field.begins_with("transform."): transform_only = false
		for edit in grouped[path]:
			if not targets.has(edit.authoring_id): fail("write target disappeared")
			else: apply(targets[edit.authoring_id], edit.fields)
		var expected_fields := {}
		var expected_preservation := {}
		for key in targets:
			expected_fields[key] = reader.fields(targets[key])
			expected_preservation[key] = reader.opaque(targets[key], "")
		var staged := PackedScene.new()
		if not error.is_empty() or staged.pack(root) != OK:
			root.free()
			fail("native staging failed: " + reader.error)
			return {}
		root.free()
		var stage: String = prefix + "." + path.get_extension()
		if ResourceSaver.save(staged, stage) != OK or ResourceSaver.set_uid(stage, ResourceLoader.get_resource_uid(path)) != OK:
			fail("native serialization failed")
			return {}
		var reopened = reader.load_scene(stage)
		if reopened == null:
			fail("staged reopen failed")
			return {}
		root = reopened.instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
		targets.clear()
		for node in reader.nodes(root): targets[node.get_meta(reader.META, {}).get("authoring_id", "")] = node
		if targets.size() != expected_fields.size(): fail("saved object set changed")
		for key in targets:
			if not expected_fields.has(key) or reader.fields(targets[key]) != expected_fields[key]:
				fail("saved mapped fields changed outside the reviewed write")
			if not expected_preservation.has(key) or reader.opaque(targets[key], "") != expected_preservation[key]:
				fail("saved stored properties differ from staged target")
			if transform_only and (not before_preservation.has(key) or reader.opaque(targets[key], "") != before_preservation[key]):
				fail("saved unowned properties changed")
		for edit in grouped[path]:
			if not targets.has(edit.authoring_id): fail("saved identity lost")
			else: verify_fields(targets[edit.authoring_id], edit.fields)
		root.free()
		if not error.is_empty(): return {}
		receipt.rows.append({"document": path, "before": before, "after": FileAccess.get_sha256(stage), "dependency_fingerprint": reader.fingerprint(path), "backup": prefix + ".before", "stage": stage, "fields": grouped[path], "applied": false})
	var after_inventory: Dictionary = reader.capture(paths)
	if not reader.error.is_empty() or reader.wire.digest(after_inventory) != request.expected_inventory_digest:
		fail("original source drift during staging")
		return {}
	if not persist(directory, receipt): return {}
	return {"directory": directory, "approval_digest": reader.wire.digest(receipt), "receipt": receipt}

func read_receipt(directory: String, expected_digest: String, approved_paths: Array) -> Dictionary:
	reader.error = ""
	reader.wire.error = ""
	if not directory.begins_with("res://.xace_authoring/transactions/") or not reader.hex_id(directory.get_file()) or not reader.path_ok(directory) or not reader.scope(approved_paths):
		fail("recovery scope/editor refusal: " + reader.error)
		return {}
	var text := FileAccess.get_file_as_string(directory + "/receipt.json")
	var receipt: Dictionary = reader.wire.decode(text)
	if text.sha256_text() != expected_digest or receipt.get("schema") != "xace.godot_native_transaction.v1" or receipt.get("transaction_id") != directory.get_file() or receipt.get("scope") != approved_paths:
		fail("receipt digest/scope mismatch")
		return {}
	var seen := {}
	for row in receipt.get("rows", []):
		if row.document not in approved_paths or seen.has(row.document) or not row.backup.begins_with(directory + "/") or not row.stage.begins_with(directory + "/") or not reader.path_ok(row.backup) or not reader.path_ok(row.stage) or FileAccess.get_sha256(row.backup) != row.before:
			fail("invalid transaction backup/paths")
			return {}
		seen[row.document] = true
	return receipt

func rollback(directory: String, digest: String, paths: Array) -> Dictionary:
	error = ""
	var receipt := read_receipt(directory, digest, paths)
	if not error.is_empty(): return {}
	var conflict := false
	for row in receipt.rows:
		var current := FileAccess.get_sha256(row.document)
		if current == row.before: continue
		if current != row.after:
			conflict = true
			continue
		if not write_bytes(row.backup + ".restore", FileAccess.get_file_as_bytes(row.backup)) or DirAccess.rename_absolute(row.backup + ".restore", row.document) != OK:
			conflict = true
		else: row.applied = false
	receipt.state = "recovery_conflict" if conflict else "rolled_back"
	if not persist(directory, receipt): return {}
	reader.rescan_required = true
	return receipt

func commit(directory: String, approval_digest: String, paths: Array, fail_after: int = -1) -> Dictionary:
	error = ""
	var receipt := read_receipt(directory, approval_digest, paths)
	if not error.is_empty(): return {}
	if receipt.state != "prepared":
		fail("transaction not prepared")
		return {}
	var inventory: Dictionary = reader.capture(paths)
	if not reader.error.is_empty() or reader.wire.digest(inventory) != receipt.inventory_digest:
		fail("native source changed since approval")
		return {}
	for row in receipt.rows:
		if FileAccess.get_sha256(row.document) != row.before or FileAccess.get_sha256(row.stage) != row.after or reader.fingerprint(row.document) != row.dependency_fingerprint:
			fail("source/stage/dependency mismatch")
			return {}
	for resource_path in receipt.get("resource_fingerprints", {}):
		if reader.fingerprint(resource_path) != receipt.resource_fingerprints[resource_path] or not reader.error.is_empty():
			fail("approved resource changed after staging")
			return {}
	receipt.state = "applying"
	if not persist(directory, receipt): return {}
	for i in receipt.rows.size():
		var row: Dictionary = receipt.rows[i]
		if FileAccess.get_sha256(row.document) != row.before or not write_bytes(row.stage + ".publish", FileAccess.get_file_as_bytes(row.stage)) or DirAccess.rename_absolute(row.stage + ".publish", row.document) != OK:
			fail("native replacement failed")
			break
		row.applied = true
		if not persist(directory, receipt): break
		if fail_after == i:
			fail("injected native replacement failure")
			break
	if not error.is_empty():
		var reason := error
		var recovered := rollback(directory, FileAccess.get_sha256(directory + "/receipt.json"), paths)
		error = reason
		return recovered
	receipt.state = "committed"
	if not persist(directory, receipt): return {}
	reader.rescan_required = true
	return receipt
