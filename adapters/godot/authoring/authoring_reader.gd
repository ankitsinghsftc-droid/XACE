@tool
extends RefCounted
## Saved native content only. Never invokes runtime transport, GDE or Player.
const Wire = preload("authoring_wire.gd")
const VERSION := "4.6.3-stable (official)"
const META := "xace_identity_v1"
const BINDING := "xace_binding_v1"
var wire = Wire.new()
var error := ""
var trusted_project := false
var rescan_required := true

func fail(message: String) -> void:
	if error.is_empty(): error = message

func editor() -> bool:
	if not Engine.is_editor_hint() or Engine.get_version_info().string != VERSION:
		fail("pinned editor privilege required")
	elif not trusted_project: fail("explicit trusted-project approval required")
	elif EditorInterface.is_playing_scene(): fail("Play capture/write refused")
	return error.is_empty()

func path_ok(path: String) -> bool:
	if not path.begins_with("res://") or "\\" in path or path.length() > 1024:
		fail("project-relative path required")
		return false
	var current := "res://"
	for part in path.substr(6).split("/"):
		if part in ["", ".", ".."]:
			fail("unsafe resource path")
			return false
		var dir := DirAccess.open(current)
		if dir != null and dir.is_link(part):
			fail("linked resource path refused")
			return false
		current = current.path_join(part)
	return true

func scope(paths: Array) -> bool:
	if not editor(): return false
	if paths.is_empty() or paths.size() > 1000:
		fail("invalid document scope")
		return false
	var seen := {}
	for path in paths:
		if not path is String or not path_ok(path): return false
		if path.get_extension() not in ["tscn", "scn"] or not FileAccess.file_exists(path) or seen.has(path):
			fail("missing/duplicate/non-scene document")
			return false
		seen[path] = true
		# Godot 4.6 has no public unsaved-scene query. Never guess from an undo
		# counter: require the selected saved scenes to be closed explicitly.
		if path in EditorInterface.get_open_scenes():
			fail("close selected scene after save/discard before saved capture/write")
			return false
	return true

func fingerprint(path: String) -> String:
	var pending: Array = [path, "res://project.godot"]
	var rows := {}
	while not pending.is_empty():
		var item: String = pending.pop_back()
		if rows.has(item): continue
		if rows.size() >= 10000 or not path_ok(item) or not FileAccess.file_exists(item):
			fail("dependency missing/unsafe/limit")
			return ""
		rows[item] = FileAccess.get_sha256(item)
		if item.get_extension() != "godot":
			for dep in ResourceLoader.get_dependencies(item):
				var pieces: PackedStringArray = dep.split("::")
				var target: String = pieces[pieces.size() - 1]
				if target.begins_with("uid://"):
					var uid := ResourceUID.text_to_id(target)
					if not ResourceUID.has_id(uid):
						fail("unresolved dependency UID")
						return ""
					target = ResourceUID.get_id_path(uid)
				pending.append(target)
		for suffix in [".uid", ".import"]:
			if FileAccess.file_exists(item + suffix):
				if not path_ok(item + suffix): return ""
				rows[item + suffix] = FileAccess.get_sha256(item + suffix)
	return wire.digest(rows)

func document_id(path: String) -> String:
	var uid := ResourceLoader.get_resource_uid(path)
	if uid < 0:
		fail("saved resource UID required")
		return ""
	return ResourceUID.id_to_text(uid)

func hex_id(value: Variant) -> bool:
	if not value is String or value.length() != 32: return false
	for c in value:
		if c not in "0123456789abcdef": return false
	return true

func metadata(value: Variant) -> bool:
	if not value is Dictionary or value.size() != 6 or not value.has_all(["namespace_id", "authoring_id", "local_id", "kind", "generation", "prefab_id"]): return false
	if not hex_id(value.namespace_id) or not hex_id(value.authoring_id) or not hex_id(value.local_id): return false
	if value.kind not in ["scene", "prefab_definition", "prefab_instance", "object"]: return false
	if not value.generation is String or not value.generation.is_valid_int() or str(value.generation.to_int()) != value.generation or value.generation.to_int() < 1: return false
	return hex_id(value.prefab_id) if value.kind == "prefab_instance" else value.prefab_id == null

func nodes(root: Node) -> Array:
	var result: Array = []
	var pending: Array = [root]
	while not pending.is_empty():
		var node: Node = pending.pop_front()
		result.append(node)
		if result.size() > 10000:
			fail("node limit")
			return []
		pending.append_array(node.get_children())
	return result

func asset(resource: Resource) -> Dictionary:
	if resource != null and resource.get_script() != null:
		fail("scripted resource requires explicit unsupported-behavior review")
		return {}
	if resource == null or not path_ok(resource.resource_path) or "::" in resource.resource_path:
		fail("external persistent resource required; embedded resources remain native")
		return {}
	var kind := ""
	if resource is Mesh: kind = "MESH"
	elif resource is Material: kind = "MATERIAL"
	elif resource is Animation: kind = "ANIMATION_CLIP"
	elif resource is AudioStream: kind = "AUDIO_CLIP"
	else:
		fail("unsupported typed resource")
		return {}
	var uid := document_id(resource.resource_path)
	return {"asset_id": "godot_" + uid.replace("uid://", ""), "asset_type": kind, "status": "LINKED", "resolved_path": resource.resource_path}

func fields(node: Node) -> Dictionary:
	var result := {"native.name": str(node.name)}
	if node is Node3D:
		var scale: Vector3 = node.scale
		if scale.x <= 0 or scale.y <= 0 or scale.z <= 0 or not node.basis.orthonormalized().is_equal_approx(Basis(node.quaternion)):
			fail("sheared/reflected/degenerate native transform")
		result["transform.position"] = wire.vector(node.position)
		result["transform.rotation"] = wire.rotation(node.quaternion)
		result["transform.scale"] = wire.vector(scale)
	if node is MeshInstance3D:
		if node.mesh != null: result["presentation.asset"] = asset(node.mesh)
		if node.material_override != null: result["presentation.material"] = asset(node.material_override)
	if node.has_meta(BINDING):
		var binding: Variant = node.get_meta(BINDING)
		if not binding is Dictionary:
			fail("invalid binding metadata")
			return result
		if binding.has("input_action"):
			var action: Variant = binding.input_action
			var settings := ConfigFile.new()
			if not action is String or settings.load("res://project.godot") != OK or not settings.has_section_key("input", action):
				fail("input action absent from saved project settings")
			else: result["input.action"] = action
		if binding.has("resource"):
			if not binding.has_all(["binding_id", "event_name", "playback_kind"]) or not binding.resource is Resource:
				fail("incomplete semantic binding")
			else:
				var ref := asset(binding.resource)
				if binding.playback_kind not in ["Animation", "Audio"] or (binding.playback_kind == "Animation" and ref.get("asset_type") != "ANIMATION_CLIP") or (binding.playback_kind == "Audio" and ref.get("asset_type") != "AUDIO_CLIP"):
					fail("unsupported binding resource/kind")
				result["binding.playback"] = {"binding_id": binding.binding_id, "event_name": binding.event_name, "playback_kind": binding.playback_kind, "asset": ref}
	if not wire.error.is_empty(): fail(wire.error)
	return result

func opaque(node: Node, fingerprint_value: String) -> Array:
	var result: Array = []
	var kind := node.get_class()
	var critical := kind not in ["Node", "Node3D", "MeshInstance3D", "DirectionalLight3D", "OmniLight3D", "SpotLight3D"] or node.get_script() != null
	if node.get_parent() == null:
		var settings := ConfigFile.new()
		if settings.load("res://project.godot") != OK or settings.has_section("autoload"):
			critical = true
	for signal_info in node.get_signal_list():
		for connection in node.get_signal_connection_list(signal_info.name):
			if connection.flags & Object.CONNECT_PERSIST: critical = true
	result.append({"id": "native.properties", "sha256": (fingerprint_value + ":" + str(node.get_path()) + ":" + kind).sha256_text(), "critical": critical, "reason": "Unmapped native behavior retained" if critical else "Unowned native properties retained"})
	return result

func load_scene(path: String) -> PackedScene:
	var scene = ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE_DEEP)
	if not scene is PackedScene:
		fail("native PackedScene load failed")
		return null
	return scene

func capture(paths: Array, discovery: bool = false) -> Dictionary:
	error = ""
	wire.error = ""
	if not scope(paths): return {}
	var documents: Array = []
	var objects := {}
	var discovered: Array = []
	var namespace_id := ""
	var local_keys := {}
	var total_nodes := 0
	var ordered := paths.duplicate()
	ordered.sort()
	for path in ordered:
		var before := fingerprint(path)
		var doc_id := document_id(path)
		var scene := load_scene(path)
		if not error.is_empty() or scene == null: return {}
		# Trusted editor-only operation. Tool scripts may execute their constructors;
		# this API is never an untrusted-project loader or a runtime facility.
		var root := scene.instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
		if root == null:
			fail("scene instantiate failed")
			return {}
		var root_meta: Variant = root.get_meta(META, {})
		if root_meta.get("kind") == "scene" and root.get_class() != "Node":
			root.free()
			fail("scene metadata root must be a neutral Node; transformed roots require explicit modeling")
			return {}
		var scene_id: Variant = root_meta.get("authoring_id") if root_meta.get("kind") == "scene" else null
		for node in nodes(root):
			total_nodes += 1
			if total_nodes > 10000:
				fail("capture object limit")
				break
			var meta: Variant = node.get_meta(META, {})
			var extracted := fields(node)
			var node_path := str(root.get_path_to(node))
			if discovery:
				discovered.append({"document": path, "document_id": doc_id, "node_path_hint": node_path, "name": str(node.name), "class": node.get_class(), "registered": metadata(meta), "fields": extracted, "opaque": opaque(node, before), "blocking_reason": error if not error.is_empty() else null})
				error = ""
				wire.error = ""
				continue
			if not metadata(meta) or (node == root and meta.kind not in ["scene", "prefab_definition"]) or (node != root and meta.kind in ["scene", "prefab_definition"]):
				fail("missing/invalid native metadata; explicit enrollment required")
				break
			if namespace_id.is_empty(): namespace_id = meta.namespace_id
			var local_key: String = doc_id + ":" + meta.local_id
			if meta.namespace_id != namespace_id or objects.has(meta.authoring_id) or local_keys.has(local_key):
				fail("foreign/duplicate native identity; recovery required")
				break
			local_keys[local_key] = true
			var parent_id: Variant = null
			if node != root and (node.get_parent() != root or root_meta.get("kind") == "prefab_definition"):
				parent_id = node.get_parent().get_meta(META, {}).get("authoring_id")
				if parent_id == null: fail("unregistered parent")
			if node != root and not node.scene_file_path.is_empty():
				if meta.kind != "prefab_instance" or node.scene_file_path not in paths: fail("packed instance definition outside selected scope")
				else:
					var definition := load_scene(node.scene_file_path)
					if definition != null:
						var state := definition.get_state()
						var found := false
						for index in state.get_node_property_count(0):
							if str(state.get_node_property_name(0, index)) == "metadata/" + META:
								var dm = state.get_node_property_value(0, index)
								found = dm.get("kind") == "prefab_definition" and dm.get("authoring_id") == meta.prefab_id
						if not found: fail("instance/definition identity mismatch")
			objects[meta.authoring_id] = {"metadata": {"schema": "xace.native_identity.v1", "namespace_id": namespace_id, "authoring_id": meta.authoring_id, "kind": meta.kind, "generation": meta.generation}, "locator": {"engine": "godot", "document_id": doc_id, "object_id": meta.local_id}, "scene_id": null if node == root else scene_id, "prefab_id": meta.prefab_id, "parent_id": parent_id, "fields": extracted, "dependencies": [], "opaque": opaque(node, before), "name": str(node.name), "path_hint": path}
		root.free()
		if not error.is_empty(): return {}
		var after := fingerprint(path)
		if before != after:
			fail("saved source changed during capture")
			return {}
		documents.append({"id": doc_id, "before": before, "after": after, "dirty": false})
	documents.sort_custom(func(a, b): return a.id < b.id)
	for row in objects.values():
		for reference in [row.scene_id, row.prefab_id, row.parent_id]:
			if reference != null and not objects.has(reference): fail("identity dependency outside selected scope")
	if not error.is_empty(): return {}
	rescan_required = false
	var source := {"engine": "godot", "engine_version": VERSION, "reader_version": "godot.authoring.reader.v1", "materializer_version": "godot.authoring.writer.v1", "play_mode": false, "documents": documents}
	var result: Dictionary
	if discovery: result = {"schema": "xace.godot_native_discovery.v1", "source": source, "nodes": discovered}
	else: result = {"schema": "xace.godot_authoring_inventory.v1", "namespace_id": namespace_id, "source": source, "objects": objects}
	wire.encode(result)
	if not wire.error.is_empty():
		fail(wire.error)
		return {}
	return result
