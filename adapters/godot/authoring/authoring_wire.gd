@tool
extends RefCounted
## Canonical bounded NEC JSON. All wire numbers are strings, never JSON doubles.
var error := ""

func fail(message: String) -> void:
	if error.is_empty(): error = message

func encode(value: Variant, depth: int = 0) -> String:
	if depth > 24:
		fail("wire depth limit")
		return ""
	var result := ""
	if value == null: result = "null"
	elif value is bool: result = "true" if value else "false"
	elif value is String:
		if value.length() > 4096: fail("wire string limit")
		result = '"'
		for i in value.length():
			var c: int = value.unicode_at(i)
			if c == 34: result += '\\"'
			elif c == 92: result += '\\\\'
			elif c == 8: result += '\\b'
			elif c == 9: result += '\\t'
			elif c == 10: result += '\\n'
			elif c == 12: result += '\\f'
			elif c == 13: result += '\\r'
			elif c < 32 or c > 126:
				if c > 65535:
					c -= 65536
					result += "\\u%04x\\u%04x" % [55296 + (c >> 10), 56320 + (c & 1023)]
				else: result += "\\u%04x" % c
			else: result += String.chr(c)
		result += '"'
	elif value is Array:
		if value.size() > 100000: fail("wire array limit")
		var parts: Array[String] = []
		for child in value: parts.append(encode(child, depth + 1))
		result = "[" + ",".join(parts) + "]"
	elif value is Dictionary:
		var keys: Array = value.keys()
		keys.sort()
		var parts: Array[String] = []
		for key in keys:
			if not key is String or key.length() > 256:
				fail("invalid wire key")
				return ""
			parts.append(encode(key, depth + 1) + ":" + encode(value[key], depth + 1))
		result = "{" + ",".join(parts) + "}"
	else: fail("wire numbers/objects prohibited")
	if result.length() > 16777216: fail("wire byte limit")
	return result

func decode(text: String) -> Dictionary:
	if text.to_utf8_buffer().size() > 16777216:
		fail("wire byte limit")
		return {}
	var json := JSON.new()
	if json.parse(text) != OK or not json.data is Dictionary:
		fail("malformed wire object")
		return {}
	# Requiring canonical input also rejects duplicate keys, numeric tokens and
	# alternate spelling. Public requests are produced by the Python bridge.
	if encode(json.data) != text:
		fail("noncanonical/ambiguous wire JSON")
		return {}
	return json.data if error.is_empty() else {}

func digest(value: Variant) -> String:
	return encode(value).sha256_text()

func decimal(value: float) -> String:
	if not is_finite(value):
		fail("nonfinite native value")
		return ""
	if value == 0: return "0"
	var text := String.num(value, 17)
	if "." in text:
		while text.ends_with("0"): text = text.left(-1)
		if text.ends_with("."): text = text.left(-1)
	return text

func vector(value: Vector3) -> Dictionary:
	return {"x": decimal(value.x), "y": decimal(value.y), "z": decimal(value.z)}

func rotation(value: Quaternion) -> Dictionary:
	return {"x": decimal(value.x), "y": decimal(value.y), "z": decimal(value.z), "w": decimal(value.w)}

func fixed(value: Variant) -> float:
	if not value is String or not value.is_valid_int() or str(value.to_int()) != value or value.length() > 20:
		fail("invalid fixed64")
		return 0.0
	var raw: int = value.to_int()
	# The certified transform subset is bounded; no float coercion of large int64.
	if abs(raw) > 8192000000:
		fail("native numeric range")
		return 0.0
	var native := float(raw) / 1000000.0
	var stored := Vector3(native, 0, 0).x
	if roundi(stored * 1000000.0) != raw or stored * 1000000.0 != float(raw):
		fail("native float cannot preserve fixed value")
	return stored

func inverse_vector(value: Dictionary) -> Vector3:
	if value.keys().size() != 3 or not value.has_all(["x", "y", "z"]):
		fail("vector shape")
		return Vector3.ZERO
	return Vector3(fixed(value.x), fixed(value.y), fixed(value.z))
