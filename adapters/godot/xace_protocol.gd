extends RefCounted
class_name XaceProtocol

const PROTOCOL_VERSION := 1
const DEFAULT_TICK_RATE := 60
const MAX_FRAME_BYTES := 4194304
const MAX_HANDSHAKE_BYTES := 65536

const MSG_HANDSHAKE := "handshake"
const MSG_HANDSHAKE_ACK := "handshake_ack"
const MSG_TICK_SNAPSHOT := "tick_snapshot"
const MSG_INPUT_PACKET := "input_packet"
const MSG_FEEDBACK_PAYLOAD := "feedback_payload"
const MSG_PLAYBACK_COMMANDS := "playback_commands"
const MSG_DISCONNECT := "disconnect"
const MSG_ERROR := "error"

const WIRE_SNAPSHOT := "Snapshot"
const WIRE_DELTA := "Delta"
const WIRE_INPUT := "Input"
const WIRE_EVENT := "Event"
const WIRE_CONTROL := "Control"
const WIRE_FEEDBACK := "Feedback"

static func build_handshake(
		engine_name: String = "Godot",
		engine_version: String = "4.x",
		adapter_version: String = "0.1.0",
		cgs_hash: String = "",
		capabilities: Array = []
) -> Dictionary:
	return {
		"msg_type": MSG_HANDSHAKE,
		"protocol_version": PROTOCOL_VERSION,
		"engine_name": _portable_text(engine_name, 96),
		"engine_version": _portable_text(engine_version, 64),
		"adapter_version": _portable_text(adapter_version, 64),
		"cgs_hash": _portable_text(cgs_hash, 128),
		"capabilities": _portable_array(capabilities, 64),
	}


static func build_input_action(
		action: String,
		value: float,
		secondary_value: float = 0.0,
		kind: String = "custom",
		phase: String = "performed"
) -> Dictionary:
	return {
		"action": _portable_text(action, 64),
		"value": clampf(value, -1.0, 1.0),
		"secondary_value": clampf(secondary_value, -1.0, 1.0),
		"kind": _portable_text(kind, 32),
		"phase": _portable_text(phase, 32),
	}


static func build_input_packet(
		peer_id: int,
		tick: int,
		sequence_id: int,
		actions: Array,
		player_id: int = 0,
		device_id: String = "",
		predicted: bool = false,
		timestamp_ms: int = 0
) -> Dictionary:
	return {
		"msg_type": MSG_INPUT_PACKET,
		"peer_id": max(1, peer_id),
		"tick": max(0, tick),
		"player_id": max(0, player_id),
		"sequence_id": max(1, sequence_id),
		"actions": _normalise_actions(actions),
		"timestamp_ms": max(0, timestamp_ms),
		"device_id": _portable_text(device_id, 64),
		"predicted": predicted,
	}


static func build_feedback_payload(tick: int, feedback_messages: Array) -> Dictionary:
	var messages: Array[Dictionary] = []
	for item in feedback_messages:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		var feedback: Dictionary = item.duplicate(true)
		if feedback.has("payload") and not feedback.has("payload_json"):
			feedback["payload_json"] = JSON.stringify(_sort_value(feedback.get("payload", {})))
			feedback.erase("payload")
		if not feedback.has("payload_json"):
			feedback["payload_json"] = "{}"
		feedback["entity_id"] = max(0, int(feedback.get("entity_id", 0)))
		feedback["generated_frame"] = max(0, int(feedback.get("generated_frame", tick)))
		feedback["feedback_type"] = str(feedback.get("feedback_type", "EngineError"))
		messages.append(feedback)
	return {
		"msg_type": MSG_FEEDBACK_PAYLOAD,
		"tick": max(0, tick),
		"messages": messages,
	}


static func encode_frame(message: Dictionary) -> PackedByteArray:
	var json_text: String = JSON.stringify(_sort_value(message))
	var payload: PackedByteArray = json_text.to_utf8_buffer()
	if payload.size() == 0:
		push_error("XaceProtocol refused to encode an empty frame")
		return PackedByteArray()
	if payload.size() > MAX_FRAME_BYTES:
		push_error("XaceProtocol refused oversized frame: %d bytes" % payload.size())
		return PackedByteArray()

	var frame: PackedByteArray = PackedByteArray()
	var length: int = payload.size()
	frame.append(length & 0xff)
	frame.append((length >> 8) & 0xff)
	frame.append((length >> 16) & 0xff)
	frame.append((length >> 24) & 0xff)
	frame.append_array(payload)
	return frame


static func try_decode_frames(buffer: PackedByteArray) -> Dictionary:
	var frames: Array[Dictionary] = []
	var offset: int = 0

	while buffer.size() - offset >= 4:
		var length: int = _read_u32_le(buffer, offset)
		if length <= 0:
			return {
				"ok": false,
				"frames": frames,
				"remaining": PackedByteArray(),
				"error": "zero-length protocol frame",
			}
		if length > MAX_FRAME_BYTES:
			return {
				"ok": false,
				"frames": frames,
				"remaining": PackedByteArray(),
				"error": "frame too large: %d bytes" % length,
			}
		if buffer.size() - offset - 4 < length:
			break

		var raw: PackedByteArray = buffer.slice(offset + 4, offset + 4 + length)
		var parsed = JSON.parse_string(raw.get_string_from_utf8())
		if typeof(parsed) != TYPE_DICTIONARY:
			return {
				"ok": false,
				"frames": frames,
				"remaining": PackedByteArray(),
				"error": "frame payload is not a JSON object",
			}

		var validation_error: String = validate_message(parsed)
		if validation_error != "":
			return {
				"ok": false,
				"frames": frames,
				"remaining": PackedByteArray(),
				"error": validation_error,
			}

		frames.append(parsed)
		offset += 4 + length

	return {
		"ok": true,
		"frames": frames,
		"remaining": buffer.slice(offset, buffer.size()),
		"error": "",
	}


static func validate_message(message: Dictionary) -> String:
	if message.has("msg_type"):
		return _validate_legacy_message(message)
	if message.has("message_type"):
		return _validate_wire_message(message)
	return "message missing msg_type or message_type"


static func classify_message(message: Dictionary) -> String:
	if message.has("msg_type"):
		return str(message.get("msg_type", ""))
	if message.has("message_type"):
		return _normalise_wire_type(message.get("message_type"))
	return ""


static func payload_dictionary(message: Dictionary) -> Dictionary:
	if not message.has("payload"):
		return message
	var payload = message.get("payload")
	if typeof(payload) == TYPE_DICTIONARY:
		return payload
	if typeof(payload) != TYPE_STRING:
		return {}
	var parsed = JSON.parse_string(payload)
	if typeof(parsed) == TYPE_DICTIONARY:
		return parsed
	return {}


static func is_state_message(message: Dictionary) -> bool:
	var kind: String = classify_message(message)
	return kind == MSG_HANDSHAKE_ACK or kind == MSG_TICK_SNAPSHOT or kind == WIRE_SNAPSHOT or kind == WIRE_DELTA


static func is_disconnect(message: Dictionary) -> bool:
	return classify_message(message) == MSG_DISCONNECT


static func is_error(message: Dictionary) -> bool:
	return classify_message(message) == MSG_ERROR


static func _validate_legacy_message(message: Dictionary) -> String:
	var msg_type: String = str(message.get("msg_type", ""))
	match msg_type:
		MSG_HANDSHAKE_ACK:
			if int(message.get("protocol_version", 0)) != PROTOCOL_VERSION:
				return "handshake_ack protocol_version mismatch"
			if not message.has("accepted"):
				return "handshake_ack missing accepted"
			if bool(message.get("accepted", false)) and str(message.get("session_id", "")).is_empty():
				return "accepted handshake_ack missing session_id"
			return ""
		MSG_TICK_SNAPSHOT:
			if int(message.get("tick", -1)) < 0:
				return "tick_snapshot has invalid tick"
			if typeof(message.get("entities", [])) != TYPE_ARRAY:
				return "tick_snapshot entities must be an array"
			return ""
		MSG_PLAYBACK_COMMANDS:
			if int(message.get("tick", -1)) < 0:
				return "playback_commands has invalid tick"
			if typeof(message.get("commands", [])) != TYPE_ARRAY:
				return "playback_commands commands must be an array"
			return ""
		MSG_DISCONNECT:
			return ""
		MSG_ERROR:
			return ""
		_:
			return "unexpected runtime msg_type: %s" % msg_type


static func _validate_wire_message(message: Dictionary) -> String:
	if int(message.get("protocol_version", 0)) != PROTOCOL_VERSION:
		return "wire protocol_version mismatch"
	if str(message.get("world_id", "")).strip_edges().is_empty():
		return "wire world_id is empty"
	if str(message.get("schema_version", "")).strip_edges().is_empty():
		return "wire schema_version is empty"
	if int(message.get("execution_plan_version", 0)) <= 0:
		return "wire execution_plan_version must be greater than zero"
	var message_type: String = _normalise_wire_type(message.get("message_type"))
	if message_type == "":
		return "wire message_type is unknown"
	if typeof(message.get("payload", "")) != TYPE_STRING:
		return "wire payload must be a JSON string"
	if payload_dictionary(message).is_empty() and str(message.get("payload", "")) != "{}":
		return "wire payload is not valid JSON object"
	return ""


static func _normalise_wire_type(value) -> String:
	var raw: String = str(value).strip_edges()
	match raw.to_lower():
		"snapshot":
			return WIRE_SNAPSHOT
		"delta":
			return WIRE_DELTA
		"input":
			return WIRE_INPUT
		"event":
			return WIRE_EVENT
		"control":
			return WIRE_CONTROL
		"feedback":
			return WIRE_FEEDBACK
		_:
			return ""


static func _read_u32_le(bytes: PackedByteArray, offset: int) -> int:
	return int(bytes[offset]) | (int(bytes[offset + 1]) << 8) | (int(bytes[offset + 2]) << 16) | (int(bytes[offset + 3]) << 24)


static func _normalise_actions(actions: Array) -> Array:
	var normalised: Array = []
	for action in actions:
		if typeof(action) != TYPE_DICTIONARY:
			continue
		normalised.append(build_input_action(
			str(action.get("action", "")),
			float(action.get("value", 0.0)),
			float(action.get("secondary_value", 0.0)),
			str(action.get("kind", "custom")),
			str(action.get("phase", "performed"))
		))
	normalised.sort_custom(func(left, right): return str(left.get("action", "")) < str(right.get("action", "")))
	return normalised


static func _portable_array(values: Array, max_bytes: int) -> Array:
	var out: Array = []
	for value in values:
		var item: String = _portable_text(str(value), max_bytes)
		if not item.is_empty():
			out.append(item)
	out.sort()
	return out


static func _portable_text(value: String, max_bytes: int) -> String:
	var cleaned: String = value.strip_edges()
	var out: String = ""
	for index in range(cleaned.length()):
		var ch: String = cleaned.substr(index, 1)
		var code: int = ch.unicode_at(0)
		var is_alpha: bool = (code >= 65 and code <= 90) or (code >= 97 and code <= 122)
		var is_digit: bool = code >= 48 and code <= 57
		var is_allowed_punctuation: bool = ch in ["_", "-", ".", "/", " "]
		if is_alpha or is_digit or is_allowed_punctuation:
			out += ch
	if out.to_utf8_buffer().size() <= max_bytes:
		return out
	while out.to_utf8_buffer().size() > max_bytes and out.length() > 0:
		out = out.left(out.length() - 1)
	return out


static func _sort_value(value):
	match typeof(value):
		TYPE_DICTIONARY:
			var sorted: Dictionary = {}
			var keys: Array = value.keys()
			keys.sort()
			for key in keys:
				sorted[key] = _sort_value(value[key])
			return sorted
		TYPE_ARRAY:
			var array: Array = []
			for item in value:
				array.append(_sort_value(item))
			return array
		_:
			return value
