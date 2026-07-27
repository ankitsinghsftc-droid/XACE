extends Node
class_name XaceAdapter

signal connected
signal disconnected(reason: String)
signal runtime_error(message: String)
signal tick_applied(tick: int)
signal input_sent(tick: int, sequence_id: int)

@export var auto_connect := true
@export var peer_id := 1
@export var player_id := 1
@export var device_id := "godot"
@export var transport_path: NodePath
@export var entity_manager_path: NodePath
@export var input_collector_path: NodePath
@export var delta_applicator_path: NodePath
@export var debug_hud_path: NodePath

var transport: Node
var entity_manager: Node
var input_collector: Node
var delta_applicator: Node
var debug_hud: Node

var _last_runtime_tick := 0
var _last_sent_input_tick := 0
var _last_sent_actions: Array = []
var _input_packets_sent := 0
var _feedback_payloads_sent := 0
var _runtime_cgs_hash := ""
var _last_snapshot_hash := ""
var _connected := false
var _entity_manager_script: Script
var _protocol_script: Script
var _transport_script: Script


func _ready() -> void:
	_load_adapter_scripts()
	transport = _resolve_or_create_transport()
	entity_manager = _resolve_or_create_entity_manager()
	input_collector = _resolve_optional(input_collector_path)
	delta_applicator = _resolve_optional(delta_applicator_path)
	debug_hud = _resolve_optional(debug_hud_path)

	_wire_transport()
	_wire_debug_hud()

	if auto_connect:
		transport.connect_to_runtime()


func _process(_delta: float) -> void:
	if transport == null or not transport.is_handshake_complete():
		return
	_send_collected_input()


func connect_to_runtime(host: String = "", port: int = 0) -> Error:
	if transport == null:
		transport = _resolve_or_create_transport()
		_wire_transport()
	return transport.connect_to_runtime(host, port)


func disconnect_from_runtime(reason: String = "adapter disconnect") -> void:
	if transport != null:
		transport.disconnect_from_runtime(reason)


func send_input_actions(actions: Array, tick: int = 0, predicted: bool = false) -> bool:
	if transport == null:
		return false
	var send_tick := tick
	if send_tick <= 0:
		send_tick = max(1, _last_runtime_tick + 1)
	var sequence_id: int = int(transport.next_sequence_id())
	var packet: Dictionary = _protocol_script.build_input_packet(
		peer_id,
		send_tick,
		sequence_id,
		actions,
		player_id,
		device_id,
		predicted,
		Time.get_ticks_msec()
	)
	var sent: bool = bool(transport.send_input_packet(packet))
	if sent:
		_input_packets_sent += 1
		_last_sent_input_tick = send_tick
		_last_sent_actions = actions.duplicate(true)
		input_sent.emit(send_tick, sequence_id)
	return sent


func is_runtime_connected() -> bool:
	return _connected


func last_runtime_tick() -> int:
	return _last_runtime_tick


func stats() -> Dictionary:
	if transport == null:
		return {}
	var out: Dictionary = transport.stats()
	out["last_runtime_tick"] = _last_runtime_tick
	out["last_sent_input_tick"] = _last_sent_input_tick
	out["input_packets_sent"] = _input_packets_sent
	out["feedback_payloads_sent"] = _feedback_payloads_sent
	out["entity_count"] = entity_manager.entity_count() if entity_manager != null else 0
	out["cgs_hash"] = _runtime_cgs_hash
	out["snapshot_hash"] = _last_snapshot_hash
	return out


func _wire_transport() -> void:
	if transport == null:
		return
	if not transport.connected.is_connected(_on_transport_connected):
		transport.connected.connect(_on_transport_connected)
	if not transport.disconnected.is_connected(_on_transport_disconnected):
		transport.disconnected.connect(_on_transport_disconnected)
	if not transport.handshake_accepted.is_connected(_on_handshake_accepted):
		transport.handshake_accepted.connect(_on_handshake_accepted)
	if not transport.message_received.is_connected(_on_message_received):
		transport.message_received.connect(_on_message_received)
	if not transport.protocol_error.is_connected(_on_protocol_error):
		transport.protocol_error.connect(_on_protocol_error)


func _wire_debug_hud() -> void:
	if debug_hud == null:
		return
	if debug_hud.has_method("bind_adapter"):
		debug_hud.call("bind_adapter", self)


func _send_collected_input() -> void:
	if input_collector == null or not input_collector.has_method("collect_actions"):
		return
	var collected_actions: Variant = input_collector.call("collect_actions", _last_runtime_tick)
	if typeof(collected_actions) != TYPE_ARRAY:
		return
	var actions_value: Array = collected_actions as Array
	if actions_value.is_empty():
		return
	var target_tick: int = int(max(1, _last_runtime_tick + 1))
	if target_tick == _last_sent_input_tick and actions_value == _last_sent_actions:
		return
	send_input_actions(actions_value, target_tick, true)


func _on_transport_connected() -> void:
	_connected = true
	connected.emit()


func _on_transport_disconnected(reason: String) -> void:
	_connected = false
	_last_sent_actions = []
	disconnected.emit(reason)


func _on_handshake_accepted(ack: Dictionary) -> void:
	_runtime_cgs_hash = str(ack.get("cgs_hash", ""))
	if entity_manager != null:
		entity_manager.apply_handshake_ack(ack)


func _on_message_received(message: Dictionary) -> void:
	if delta_applicator != null and delta_applicator.has_method("apply_message"):
		delta_applicator.call("apply_message", message, entity_manager)
	elif entity_manager != null:
		entity_manager.apply_message(message)

	var tick: int = _extract_tick(message)
	if tick >= 0:
		_last_runtime_tick = max(_last_runtime_tick, tick)
		_last_snapshot_hash = _snapshot_hash(message)
		tick_applied.emit(_last_runtime_tick)

	_flush_feedback()


func _on_protocol_error(message: String) -> void:
	runtime_error.emit(message)


func _flush_feedback() -> void:
	if transport == null or delta_applicator == null:
		return
	if not transport.has_method("send_feedback_payload") or not delta_applicator.has_method("drain_feedback"):
		return
	var drained_feedback: Variant = delta_applicator.call("drain_feedback")
	if typeof(drained_feedback) != TYPE_ARRAY:
		return
	var feedback_value: Array = drained_feedback as Array
	if feedback_value.is_empty():
		return
	var sent: bool = bool(transport.call("send_feedback_payload", _last_runtime_tick, feedback_value))
	if sent:
		_feedback_payloads_sent += 1


func _extract_tick(message: Dictionary) -> int:
	if message.has("tick"):
		return int(message.get("tick", -1))
	var payload: Dictionary = _protocol_script.payload_dictionary(message)
	if payload.has("tick"):
		return int(payload.get("tick", -1))
	return -1


func _snapshot_hash(message: Dictionary) -> String:
	var proof: Dictionary = {
		"tick": message.get("tick", 0),
		"entities": message.get("entities", []),
		"spawned_ids": message.get("spawned_ids", []),
		"destroyed_ids": message.get("destroyed_ids", []),
		"events": message.get("events", []),
		"playback_commands": message.get("playback_commands", []),
	}
	var json_text := JSON.stringify(_sort_value(proof))
	var digest := json_text.sha256_text()
	return digest.left(12)


func _sort_value(value):
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


func _resolve_or_create_transport() -> Node:
	var existing = _resolve_optional(transport_path)
	if existing != null and existing.get_script() == _transport_script:
		return existing
	var node: Node = _transport_script.new()
	node.name = "XaceTransport"
	add_child(node)
	return node


func _resolve_or_create_entity_manager() -> Node:
	var existing = _resolve_optional(entity_manager_path)
	if existing != null and existing.get_script() == _entity_manager_script:
		return existing
	var node: Node = _entity_manager_script.new()
	node.name = "XaceEntityManager"
	add_child(node)
	return node


func _resolve_optional(path: NodePath) -> Node:
	if String(path).is_empty():
		return null
	return get_node_or_null(path)


func _load_adapter_scripts() -> void:
	var base_dir := _script_base_dir()
	_entity_manager_script = load(base_dir.path_join("xace_entity_manager.gd"))
	_protocol_script = load(base_dir.path_join("xace_protocol.gd"))
	_transport_script = load(base_dir.path_join("xace_transport.gd"))


func _script_base_dir() -> String:
	var own_script: Script = get_script()
	var resource_path := own_script.resource_path if own_script != null else ""
	if resource_path.is_empty():
		return "res://"
	return resource_path.get_base_dir()
