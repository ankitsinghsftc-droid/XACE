@tool
extends RefCounted
## Native serialization for an explicitly approved, isolated new-project stage.
## The host reviews the resulting file inventory before publishing any files.
const Reader = preload("authoring_reader.gd")
const Writer = preload("authoring_writer.gd")
var reader = Reader.new()
var writer = Writer.new()
var error := ""

func fail(message: String) -> Dictionary:
	error = message
	return {}

func create(spec: Dictionary, approved_digest: String) -> Dictionary:
	error = ""
	reader.trusted_project = true
	if not reader.editor(): return fail(reader.error)
	if reader.wire.digest(spec) != approved_digest: return fail("Setup differs from approved native stage request")
	if spec.size() != 3 or not spec.has_all(["schema", "scene", "objects"]) or spec.schema != "xace.godot_native_setup.v1": return fail("Invalid setup request")
	if not spec.scene is Dictionary or not reader.metadata(spec.scene) or spec.scene.kind != "scene": return fail("Explicit scene identity required")
	if not spec.objects is Array or spec.objects.is_empty() or spec.objects.size() > 128: return fail("Select one to128 native objects")
	if not FileAccess.file_exists("res://.xace/native-setup-approved.json"): return fail("Registered setup stage authorization required")
	var approval: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://.xace/native-setup-approved.json"))
	if not approval is Dictionary or approval.get("digest") != approved_digest or approval.get("stage_root") != ProjectSettings.globalize_path("res://").trim_suffix("/"): return fail("Foreign setup stage")
	if DirAccess.dir_exists_absolute("res://XACEGenerated"): return fail("Existing generated content must not be replaced")
	var root := Node.new()
	root.name = "XACEWorld"
	root.set_meta(reader.META, spec.scene.duplicate(true))
	var seen := {spec.scene.authoring_id: true}
	for row in spec.objects:
		if not row is Dictionary or row.size() != 3 or not row.has_all(["identity", "name", "fields"]):
			root.free()
			return fail("Invalid setup object")
		if not row.identity is Dictionary or not reader.metadata(row.identity) or row.identity.kind != "object" or row.identity.namespace_id != spec.scene.namespace_id or seen.has(row.identity.authoring_id):
			root.free()
			return fail("Ambiguous setup identity")
		if not row.name is String or row.name.is_empty() or row.name.length() > 128 or not row.fields is Dictionary or row.fields.size() != 3 or not row.fields.has_all(["transform.position", "transform.rotation", "transform.scale"]):
			root.free()
			return fail("Explicit name and root transform required")
		seen[row.identity.authoring_id] = true
		var node := Node3D.new()
		node.name = row.name
		node.set_meta(reader.META, row.identity.duplicate(true))
		root.add_child(node, true)
		node.owner = root
		writer.apply(node, row.fields)
		if not writer.error.is_empty() or not writer.reader.wire.error.is_empty():
			root.free()
			return fail("Setup transform cannot be represented exactly")
	var packed := PackedScene.new()
	if packed.pack(root) != OK:
		root.free()
		return fail("Native scene packing failed")
	root.free()
	if DirAccess.make_dir_recursive_absolute("res://XACEGenerated") != OK: return fail("Stage directory unavailable")
	var path := "res://XACEGenerated/World.tscn"
	if ResourceSaver.save(packed, path) != OK: return fail("Native scene save failed")
	if ResourceLoader.get_resource_uid(path) < 0 and ResourceSaver.set_uid(path, ResourceUID.create_id()) != OK: return fail("Scene UID save failed")
	var captured: Dictionary = reader.capture([path])
	if captured.is_empty(): return fail(reader.error)
	return {"schema": "xace.godot_native_setup_result.v1", "inventory": captured, "files": ["XACEGenerated/World.tscn"], "request_digest": approved_digest}
