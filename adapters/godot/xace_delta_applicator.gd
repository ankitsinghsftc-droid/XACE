extends Node
class_name XaceDeltaApplicator

signal state_applied(tick: int, message_type: String, operation_count: int)
signal feedback_ready(feedback: Dictionary)
signal apply_failed(message: String)

@export var collect_performance_feedback := true
@export var performance_feedback_interval_ticks := 60
@export var collect_live_validation_feedback := true
@export var live_validation_feedback_interval_ticks := 30

var _last_tick := 0
var _messages_applied := 0
var _operations_applied := 0
var _feedback_queue: Array[Dictionary] = []
var _last_performance_feedback_tick := -1
var _last_live_validation_feedback_tick := -1
var _protocol_script: Script


func _ready() -> void:
	_load_adapter_scripts()


func apply_message(message: Dictionary, entity_manager: Node) -> void:
	if entity_manager == null:
		_fail("missing XaceEntityManager")
		return

	var started_us: int = int(Time.get_ticks_usec())
	var kind: String = _protocol_script.classify_message(message)
	var before_count: int = int(entity_manager.entity_count())

	if kind == _protocol_script.MSG_HANDSHAKE_ACK:
		entity_manager.apply_handshake_ack(message)
	elif kind == _protocol_script.MSG_TICK_SNAPSHOT:
		entity_manager.apply_tick_snapshot(message)
	elif kind == _protocol_script.MSG_PLAYBACK_COMMANDS:
		if entity_manager.has_method("apply_playback_commands"):
			entity_manager.call("apply_playback_commands", message.get("commands", []))
	elif kind == _protocol_script.MSG_ADAPTER_SIDE_EFFECT_ROLLBACK:
		apply_side_effect_rollback(message, entity_manager)
	elif kind == _protocol_script.WIRE_SNAPSHOT:
		entity_manager.apply_snapshot_payload(_protocol_script.payload_dictionary(message))
	elif kind == _protocol_script.WIRE_DELTA:
		entity_manager.apply_delta_payload(_protocol_script.payload_dictionary(message))
	else:
		_fail("unsupported state message: %s" % kind)
		return

	var elapsed_ms: float = float(Time.get_ticks_usec() - started_us) / 1000.0
	var tick: int = _extract_tick(message)
	var operation_count: int = _estimate_operation_count(message, before_count, int(entity_manager.entity_count()))
	_last_tick = max(_last_tick, tick)
	_messages_applied += 1
	_operations_applied += operation_count

	if collect_performance_feedback and _should_emit_performance(tick):
		_queue_performance_feedback(tick, elapsed_ms, entity_manager.entity_count())
	if collect_live_validation_feedback and _should_emit_live_validation(tick):
		_queue_live_validation_feedback(tick, kind, operation_count, entity_manager.entity_count(), elapsed_ms)

	state_applied.emit(tick, kind, operation_count)


func apply_side_effect_rollback(message: Dictionary, entity_manager: Node) -> void:
	_feedback_queue.clear()
	_last_tick = int(message.get("restore_tick", _last_tick))
	if entity_manager != null and entity_manager.has_method("rollback_side_effects"):
		entity_manager.call("rollback_side_effects", message)
	elif entity_manager != null and entity_manager.has_method("apply_tick_snapshot"):
		var restored = message.get("restored_snapshot", {})
		if typeof(restored) == TYPE_DICTIONARY:
			entity_manager.call("apply_tick_snapshot", restored)
	state_applied.emit(_last_tick, _protocol_script.MSG_ADAPTER_SIDE_EFFECT_ROLLBACK, 1)

func drain_feedback() -> Array:
	var drained: Array = _feedback_queue.duplicate(true)
	_feedback_queue.clear()
	return drained


func stats() -> Dictionary:
	return {
		"last_tick": _last_tick,
		"messages_applied": _messages_applied,
		"operations_applied": _operations_applied,
		"queued_feedback": _feedback_queue.size(),
	}


func _extract_tick(message: Dictionary) -> int:
	if message.has("tick"):
		return int(message.get("tick", 0))
	var payload: Dictionary = _protocol_script.payload_dictionary(message)
	return int(payload.get("tick", 0))


func _estimate_operation_count(message: Dictionary, before_count: int, after_count: int) -> int:
	var kind: String = _protocol_script.classify_message(message)
	if kind == _protocol_script.MSG_TICK_SNAPSHOT:
		return max(1, abs(after_count - before_count) + int(message.get("entities", []).size()))
	if kind == _protocol_script.MSG_PLAYBACK_COMMANDS:
		return max(1, int(message.get("commands", []).size()))
	var payload: Dictionary = _protocol_script.payload_dictionary(message)
	if kind == _protocol_script.WIRE_SNAPSHOT:
		return max(1, int(payload.get("entities", []).size()))
	if kind != _protocol_script.WIRE_DELTA:
		return 1
	return (
		int(payload.get("spawned_entities", []).size())
		+ int(payload.get("added_components", []).size())
		+ int(payload.get("modified_entities", {}).size())
		+ int(payload.get("removed_components", []).size())
		+ int(payload.get("destroyed_entities", []).size())
	)


func _should_emit_performance(tick: int) -> bool:
	if tick <= 0:
		return false
	if _last_performance_feedback_tick < 0:
		_last_performance_feedback_tick = tick
		return true
	return tick - _last_performance_feedback_tick >= performance_feedback_interval_ticks


func _should_emit_live_validation(tick: int) -> bool:
	if tick <= 0:
		return false
	if _last_live_validation_feedback_tick < 0:
		_last_live_validation_feedback_tick = tick
		return true
	return tick - _last_live_validation_feedback_tick >= live_validation_feedback_interval_ticks


func _queue_performance_feedback(tick: int, elapsed_ms: float, entity_count: int) -> void:
	_last_performance_feedback_tick = tick
	var feedback: Dictionary = {
		"feedback_type": "PerformanceMetrics",
		"entity_id": 0,
		"generated_frame": tick,
		"payload": {
			"engine_delta_apply_ms": elapsed_ms,
			"draw_calls": int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
			"physics_contacts": int(0),
			"engine_entity_count": int(entity_count),
			"generated_frame": tick,
		},
	}
	_feedback_queue.append(feedback)
	feedback_ready.emit(feedback.duplicate(true))


func _queue_live_validation_feedback(
	tick: int,
	message_type: String,
	operation_count: int,
	entity_count: int,
	elapsed_ms: float
) -> void:
	_last_live_validation_feedback_tick = tick
	var feedback: Dictionary = {
		"feedback_type": "PerformanceMetrics",
		"entity_id": 0,
		"generated_frame": tick,
		"payload": {
			"engine_delta_apply_ms": elapsed_ms,
			"draw_calls": int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
			"physics_contacts": int(0),
			"engine_entity_count": int(entity_count),
			"generated_frame": tick,
			"xace_live_validation": true,
			"adapter_engine": "godot",
			"message_type": message_type,
			"operation_count": max(0, operation_count),
			"runtime_tick": tick,
		},
	}
	_feedback_queue.append(feedback)
	feedback_ready.emit(feedback.duplicate(true))


func _fail(message: String) -> void:
	push_warning("XaceDeltaApplicator: %s" % message)
	apply_failed.emit(message)


func _load_adapter_scripts() -> void:
	var base_dir := _script_base_dir()
	_protocol_script = load(base_dir.path_join("xace_protocol.gd"))


func _script_base_dir() -> String:
	var own_script: Script = get_script()
	var resource_path := own_script.resource_path if own_script != null else ""
	if resource_path.is_empty():
		return "res://"
	return resource_path.get_base_dir()
