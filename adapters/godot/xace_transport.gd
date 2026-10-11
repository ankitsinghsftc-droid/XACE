extends Node
class_name XaceTransport

signal connected
signal disconnected(reason: String)
signal handshake_accepted(ack: Dictionary)
signal handshake_rejected(reason: String)
signal message_received(message: Dictionary)
signal protocol_error(message: String)
signal stats_changed(stats: Dictionary)

@export var host := "127.0.0.1"
@export var port := 7777
@export var engine_name := "Godot"
@export var engine_version := "4.x"
@export var adapter_version := "0.1.0"
@export var cgs_hash := ""
var session_offer_json := ""
var session_credential := ""
var session_peer_id := 0
var native_contract: RefCounted

func configure_live_session(ticket: Dictionary, world_json: String) -> bool:
	if _connected:
		return false
	var candidate: RefCounted = load(_script_base_dir().path_join("xace_native_contract.gd")).new()
	if not candidate.configure(ticket, world_json):
		_fail(str(candidate.error))
		return false
	native_contract = candidate
	session_offer_json = JSON.stringify(candidate.offer)
	session_credential = str(candidate.credential)
	session_peer_id = int(candidate.peer_id)
	return true
var _projection_stamp: Dictionary = {}
var _projection_stamp_json := ""
var _projection_recovering := false
@export var capabilities: Array[String] = [
	"length_prefixed_json",
	"tick_snapshot_v1",
	"input_packet_v1",
	"feedback_payload_v1",
	"adapter_side_effect_rollback_v1",
	"godot_4",
]
@export var auto_connect := false
@export var reconnect_enabled := false
@export var reconnect_delay_sec := 1.0

var _tcp := StreamPeerTCP.new()
var _incoming := PackedByteArray()
var _send_queue: Array[Dictionary] = []
var _connected := false
var _handshake_sent := false
var _handshake_complete := false
var _reconnect_timer := 0.0
var _sequence_id := 1
var _last_error := ""
var _protocol_script: Script
var _stats := {
	"bytes_sent": 0,
	"bytes_received": 0,
	"frames_sent": 0,
	"frames_received": 0,
	"malformed_frames": 0,
	"queued_messages": 0,
}


func _ready() -> void:
	_load_adapter_scripts()
	set_process(true)
	if auto_connect:
		connect_to_runtime()


func _process(delta: float) -> void:
	if reconnect_enabled and not _connected and _tcp.get_status() == StreamPeerTCP.STATUS_NONE:
		_reconnect_timer -= delta
		if _reconnect_timer <= 0.0:
			connect_to_runtime()
	poll_transport()


func connect_to_runtime(target_host: String = "", target_port: int = 0) -> Error:
	if not target_host.is_empty():
		host = target_host
	if target_port > 0:
		port = target_port

	_reset_connection_state(false)
	var err: int = _tcp.connect_to_host(host, port)
	if err != OK:
		_fail("connect_to_host failed: %s" % error_string(err))
		_schedule_reconnect()
	return err


func disconnect_from_runtime(reason: String = "adapter disconnect") -> void:
	if _tcp.get_status() != StreamPeerTCP.STATUS_NONE:
		_tcp.disconnect_from_host()
	_reset_connection_state(true)
	disconnected.emit(reason)


func poll_transport() -> void:
	_tcp.poll()
	var status: int = _tcp.get_status()

	if status == StreamPeerTCP.STATUS_CONNECTED and not _connected:
		_connected = true
		_send_handshake()
		connected.emit()

	if status == StreamPeerTCP.STATUS_ERROR:
		_fail("TCP connection error")
		_tcp.disconnect_from_host()
		_reset_connection_state(true)
		_schedule_reconnect()
		return

	if status == StreamPeerTCP.STATUS_NONE:
		if _connected:
			_reset_connection_state(true)
			disconnected.emit("remote closed")
			_schedule_reconnect()
		return

	if status != StreamPeerTCP.STATUS_CONNECTED:
		return

	_read_available()
	_flush_send_queue()
	_emit_stats()


func send_message(message: Dictionary) -> bool:
	if not _connected:
		_send_queue.append(message)
		_stats["queued_messages"] = _send_queue.size()
		return false
	return _write_message(message)


func send_input_packet(packet: Dictionary) -> bool:
	if native_contract != null:
		if not _handshake_complete or not native_contract.can_send(packet):
			return false
		var success := send_message(packet)
		if success:
			native_contract.sent = true
		return success
	return send_message(packet)


func send_feedback_payload(tick: int, feedback_messages: Array) -> bool:
	if not session_offer_json.is_empty():
		return false
	if feedback_messages.is_empty():
		return true
	return send_message(_protocol_script.build_feedback_payload(tick, feedback_messages))


func next_sequence_id() -> int:
	var seq: int = _sequence_id
	_sequence_id += 1
	return seq


func is_runtime_connected() -> bool:
	return _connected


func is_handshake_complete() -> bool:
	return _handshake_complete


func stats() -> Dictionary:
	return _stats.duplicate(true)


func last_error() -> String:
	return _last_error


func _send_handshake() -> void:
	if _handshake_sent:
		return
	var hello: Dictionary = _protocol_script.build_handshake(
		engine_name,
		engine_version,
		adapter_version,
		cgs_hash,
		capabilities
	)
	if not session_offer_json.is_empty():
		hello["session_offer_json"] = session_offer_json
		hello["session_credential"] = session_credential
		hello["session_peer_id"] = session_peer_id
	_handshake_sent = true
	_write_message(hello)


func _read_available() -> void:
	var available: int = _tcp.get_available_bytes()
	if available <= 0:
		return
	var chunk: Array = _tcp.get_data(available)
	if int(chunk[0]) != OK:
		_fail("TCP read failed: %s" % error_string(int(chunk[0])))
		return
	var bytes: PackedByteArray = chunk[1]
	_stats["bytes_received"] = int(_stats["bytes_received"]) + bytes.size()
	_incoming.append_array(bytes)

	var decoded: Dictionary = _protocol_script.try_decode_frames(_incoming)
	if not bool(decoded.get("ok", false)):
		_stats["malformed_frames"] = int(_stats["malformed_frames"]) + 1
		_incoming = PackedByteArray()
		_fail(str(decoded.get("error", "malformed frame")))
		return

	_incoming = decoded.get("remaining", PackedByteArray())
	for message in decoded.get("frames", []):
		_stats["frames_received"] = int(_stats["frames_received"]) + 1
		_handle_message(message)


func _handle_message(message: Dictionary) -> void:
	var kind: String = _protocol_script.classify_message(message)
	if not session_offer_json.is_empty():
		if kind == "input_tick_request":
			if _projection_recovering or int(message.get("tick", -1)) != int(_projection_stamp.get("next_tick", -2)):
				return
			if native_contract != null and not native_contract.request(int(message.get("tick", -1))):
				return
		elif kind in ["handshake_ack", "tick_snapshot", "session_baseline"] and bool(message.get("accepted", true)):
			if not _verify_projection(message, kind == "handshake_ack"):
				return
	if kind == _protocol_script.MSG_HANDSHAKE_ACK:
		if bool(message.get("accepted", false)):
			_handshake_complete = true
			handshake_accepted.emit(message)
			if message.has("sync"):
				session_credential = str(message.get("reconnect_credential", ""))
				_ack_projection()
		else:
			var reason: String = str(message.get("reject_reason", "handshake rejected"))
			handshake_rejected.emit(reason)
			disconnect_from_runtime(reason)
	elif kind == _protocol_script.MSG_DISCONNECT:
		disconnect_from_runtime(str(message.get("reason", "runtime disconnect")))
	elif kind == _protocol_script.MSG_ERROR:
		_fail("%s: %s" % [str(message.get("code", "runtime_error")), str(message.get("message", ""))])
	else:
		message_received.emit(message)
		if message.has("sync"):
			_ack_projection()


func _verify_projection(message: Dictionary, initial: bool) -> bool:
	if native_contract != null:
		var result: String = native_contract.verify(message)
		if result == "reject":
			_fail(str(native_contract.error))
			disconnect_from_runtime("Invalid live projection")
			return false
		if result == "recover":
			_request_projection_recovery()
			return false
		if result == "drop":
			return false
		_projection_stamp = message.sync.duplicate(true)
		_projection_stamp_json = str(message.sync_json)
		_projection_recovering = false
		return true
	var parsed_stamp: Variant = JSON.parse_string(str(message.get("sync_json", "")))
	if not parsed_stamp is Dictionary:
		return false
	var stamp: Dictionary = parsed_stamp
	var offer: Dictionary = JSON.parse_string(session_offer_json)
	var epoch: Dictionary = offer.get("contract", {}).get("epoch", {})
	for key in ["session_id", "authority_incarnation", "ruleset_epoch"]:
		if str(stamp.get(key, "")) != str(epoch.get(key, "")):
			_fail("Projection session identity mismatch")
			disconnect_from_runtime("Invalid baseline")
			return false
	var generation := int(stamp.get("connection_generation", 0))
	var previous_generation := int(_projection_stamp.get("connection_generation", 0))
	if initial:
		if generation <= previous_generation:
			return false
	elif generation != previous_generation:
		return false
	var sequence := int(stamp.get("sequence", 0))
	var previous_sequence := int(_projection_stamp.get("sequence", 0))
	if not initial and sequence <= previous_sequence:
		return false
	var recovery := str(message.get("msg_type", "")) == "session_baseline"
	if _projection_recovering and not recovery and not initial:
		return false
	if not initial and not recovery and (sequence != previous_sequence + 1 or int(stamp.get("next_tick", -1)) != int(_projection_stamp.get("next_tick", -1)) + 1):
		_request_projection_recovery()
		return false
	var raw := str(message.get("projection_json", ""))
	var projection: Variant = JSON.parse_string(raw)
	if stamp.get("schema", "") != "xace.session_projection.v1" or raw.sha256_text() != str(stamp.get("projection_digest", "")) or not projection is Array or int(stamp.get("next_tick", -1)) < 0 or str(stamp.get("baseline_id", "")).is_empty():
		if initial:
			_fail("Invalid initial projection")
			disconnect_from_runtime("Invalid baseline")
		else:
			_request_projection_recovery()
		return false
	if not initial and int(stamp.next_tick) < int(_projection_stamp.next_tick):
		return false
	message["sync"] = stamp
	message["initial_entities" if initial else "entities"] = projection
	_projection_stamp = stamp.duplicate(true)
	_projection_stamp_json = str(message.sync_json)
	_projection_recovering = false
	return true

func _ack_projection() -> void:
	if _connected:
		_write_message({"msg_type":"baseline_ack", "stamp_json":_projection_stamp_json})

func _request_projection_recovery() -> void:
	if _projection_recovering:
		return
	_projection_recovering = true
	_write_message({"msg_type":"resync_request", "connection_generation":int(_projection_stamp.get("connection_generation", 0))})

func _flush_send_queue() -> void:
	if _send_queue.is_empty() or not _handshake_complete:
		_stats["queued_messages"] = _send_queue.size()
		return
	var pending: Array[Dictionary] = _send_queue
	_send_queue = []
	for message in pending:
		if not _write_message(message):
			_send_queue.append(message)
			break
	_stats["queued_messages"] = _send_queue.size()


func _write_message(message: Dictionary) -> bool:
	var frame: PackedByteArray = _protocol_script.encode_frame(message)
	if frame.is_empty():
		_fail("failed to encode outbound message")
		return false
	var err: int = _tcp.put_data(frame)
	if int(err) != OK:
		_fail("TCP write failed: %s" % error_string(int(err)))
		return false
	_stats["bytes_sent"] = int(_stats["bytes_sent"]) + frame.size()
	_stats["frames_sent"] = int(_stats["frames_sent"]) + 1
	return true


func _reset_connection_state(clear_queue: bool) -> void:
	if native_contract != null:
		native_contract.fence()
	_connected = false
	_handshake_sent = false
	_handshake_complete = false
	_incoming = PackedByteArray()
	if clear_queue:
		_send_queue.clear()
		_stats["queued_messages"] = 0


func _schedule_reconnect() -> void:
	if reconnect_enabled:
		_reconnect_timer = reconnect_delay_sec


func _fail(message: String) -> void:
	_last_error = message
	push_warning("XaceTransport: %s" % message)
	protocol_error.emit(message)


func _emit_stats() -> void:
	stats_changed.emit(stats())


func _load_adapter_scripts() -> void:
	var base_dir := _script_base_dir()
	_protocol_script = load(base_dir.path_join("xace_protocol.gd"))


func _script_base_dir() -> String:
	var own_script: Script = get_script()
	var resource_path := own_script.resource_path if own_script != null else ""
	if resource_path.is_empty():
		return "res://"
	return resource_path.get_base_dir()
