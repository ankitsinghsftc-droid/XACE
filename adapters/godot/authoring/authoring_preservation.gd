@tool
extends RefCounted
## Fingerprint stored native properties independently of mapped Node3D transforms.
## Never hash instance IDs or use Object serialization. Unsupported values fail closed.
var error := ""
var active := {}
const Wire = preload("authoring_wire.gd")
var wire = Wire.new()

func fail(message: String) -> Variant:
	if error.is_empty(): error = message
	return null

func value(item: Variant, reader: RefCounted, depth: int = 0) -> Variant:
	if depth > 20: return fail("preservation depth limit")
	if item is Object:
		if not item is Resource: return fail("unmapped object reference requires preservation profile")
		var path: String = item.resource_path
		if not path.is_empty() and "::" not in path:
			if not reader.path_ok(path): return fail("unsafe preservation resource")
			var fingerprint: String = reader.fingerprint(path)
			if not reader.error.is_empty(): return fail(reader.error)
			return {"resource": path, "class": item.get_class(), "fingerprint": fingerprint}
		if active.has(item): return fail("cyclic embedded resource requires preservation profile")
		active[item] = true
		var result: Dictionary = properties(item, reader, depth + 1)
		active.erase(item)
		return {"embedded_class": item.get_class(), "properties": result}
	if item is Dictionary:
		var entries: Array = []
		for key in item:
			var encoded_key: String = wire.encode(value(key, reader, depth + 1))
			entries.append([encoded_key, value(item[key], reader, depth + 1)])
		entries.sort_custom(func(a, b): return a[0] < b[0])
		return {"dictionary": entries}
	if item is Array:
		if item.size() > 10000: return fail("preservation array limit")
		var entries: Array = []
		for child in item: entries.append(value(child, reader, depth + 1))
		return {"array": entries}
	if typeof(item) in [TYPE_CALLABLE, TYPE_SIGNAL, TYPE_RID]: return fail("unmapped runtime reference")
	var bytes: PackedByteArray = var_to_bytes(item)
	if bytes.size() > 1048576: return fail("preservation value limit")
	return {"type": str(typeof(item)), "bytes": bytes.hex_encode()}

func properties(object: Object, reader: RefCounted, depth: int = 0) -> Dictionary:
	var result := {}
	for property in object.get_property_list():
		if not (property.usage & PROPERTY_USAGE_STORAGE): continue
		var name: String = property.name
		# Position/quaternion/scale are verified separately by exact typed readback.
		# Every other serialized property, including arbitrary metadata, is retained.
		if object is Node3D and name == "transform" and object.get_meta(reader.META, {}).get("kind") != "scene": continue
		result[name] = value(object.get(name), reader, depth + 1)
	return result

func fingerprint(node: Node, reader: RefCounted) -> String:
	error = ""
	active.clear()
	var fields: Dictionary = properties(node, reader)
	if not error.is_empty(): return ""
	var result: String = wire.digest({"profile": "godot.stored_properties.v1", "class": node.get_class(), "properties": fields})
	if not wire.error.is_empty(): error = wire.error
	return result
