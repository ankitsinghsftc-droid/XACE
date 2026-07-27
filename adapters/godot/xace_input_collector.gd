extends Node
class_name XaceInputCollector

signal actions_collected(tick: int, actions: Array)

@export var enabled := true
@export var emit_idle_movement := false
@export var include_pointer := true
@export var action_profile_id := "default_player"
@export var movement_deadzone := 0.01
@export var movement_action := "move"
@export var movement_x_action := "move_x"
@export var movement_z_action := "move_z"
@export var attack_action := "attack"
@export var interact_action := "interact"
@export var dash_action := "dash"

var _pointer_delta := Vector2.ZERO
var _pointer_position := Vector2.ZERO
var _last_collect_tick := -1
var _last_actions: Array = []
var _protocol_script: Script


func get_action_profile() -> Dictionary:
	return {
		"profile_id": action_profile_id,
		"actions": [
			{
				"semantic_action": "Move",
				"wire_actions": [movement_x_action, movement_z_action],
				"godot_actions": ["move_left", "move_right", "move_forward", "move_back"],
				"kind": "axis_2d",
			},
			{
				"semantic_action": "Attack",
				"wire_actions": ["Attack"],
				"godot_actions": [attack_action],
				"kind": "button",
			},
			{
				"semantic_action": "Interact",
				"wire_actions": ["Interact"],
				"godot_actions": [interact_action],
				"kind": "button",
			},
			{
				"semantic_action": "Dash",
				"wire_actions": ["Dash"],
				"godot_actions": [dash_action],
				"kind": "button",
			},
		],
	}


func _ready() -> void:
	_load_adapter_scripts()
	set_process_unhandled_input(true)


func _unhandled_input(event: InputEvent) -> void:
	if not enabled:
		return
	if event is InputEventMouseMotion:
		_pointer_delta += event.relative
		_pointer_position = event.position
	elif event is InputEventScreenDrag:
		_pointer_delta += event.relative
		_pointer_position = event.position
	elif event is InputEventScreenTouch:
		_pointer_position = event.position


func collect_actions(runtime_tick: int) -> Array:
	if not enabled:
		return []
	if _last_collect_tick == runtime_tick:
		return _last_actions.duplicate(true)

	var actions: Array = []
	_append_movement(actions)
	_append_button(actions, attack_action, "Attack", "button")
	_append_button(actions, interact_action, "Interact", "button")
	_append_button(actions, dash_action, "Dash", "button")
	if include_pointer:
		_append_pointer(actions)

	actions.sort_custom(func(left, right): return str(left.get("action", "")) < str(right.get("action", "")))
	_last_collect_tick = runtime_tick
	_last_actions = actions.duplicate(true)
	_pointer_delta = Vector2.ZERO
	if not actions.is_empty():
		actions_collected.emit(runtime_tick, actions.duplicate(true))
	return actions


func last_actions() -> Array:
	return _last_actions.duplicate(true)


func clear_transient_state() -> void:
	_pointer_delta = Vector2.ZERO
	_last_actions = []
	_last_collect_tick = -1


func _append_movement(actions: Array) -> void:
	if not _has_actions(["move_left", "move_right", "move_back", "move_forward"]):
		return
	var axis := Input.get_vector("move_left", "move_right", "move_back", "move_forward")
	if axis.length() <= movement_deadzone and not emit_idle_movement:
		return
	if not movement_action.is_empty():
		actions.append(_protocol_script.build_input_action(
			movement_action,
			axis.x,
			axis.y,
			"axis_2d",
			"changed" if axis.length() > movement_deadzone else "cancelled"
		))
	actions.append(_protocol_script.build_input_action(
		movement_x_action,
		axis.x,
		0.0,
		"axis_1d",
		"changed" if abs(axis.x) > movement_deadzone else "cancelled"
	))
	actions.append(_protocol_script.build_input_action(
		movement_z_action,
		axis.y,
		0.0,
		"axis_1d",
		"changed" if axis.length() > movement_deadzone else "cancelled"
	))


func _append_button(actions: Array, input_action: String, wire_action: String, kind: String) -> void:
	if input_action.is_empty() or not InputMap.has_action(input_action):
		return
	if Input.is_action_just_pressed(input_action):
		actions.append(_protocol_script.build_input_action(wire_action, 1.0, 0.0, kind, "started"))
	elif Input.is_action_pressed(input_action):
		actions.append(_protocol_script.build_input_action(wire_action, 1.0, 0.0, kind, "performed"))
	elif Input.is_action_just_released(input_action):
		actions.append(_protocol_script.build_input_action(wire_action, 0.0, 0.0, kind, "cancelled"))


func _append_pointer(actions: Array) -> void:
	if _pointer_delta == Vector2.ZERO:
		return
	actions.append(_protocol_script.build_input_action(
		"pointer_delta",
		_pointer_delta.x / 1024.0,
		_pointer_delta.y / 1024.0,
		"pointer",
		"changed"
	))
	actions.append(_protocol_script.build_input_action(
		"pointer_position",
		_pointer_position.x / max(1.0, get_viewport().get_visible_rect().size.x),
		_pointer_position.y / max(1.0, get_viewport().get_visible_rect().size.y),
		"pointer",
		"changed"
	))


func _has_actions(names: Array) -> bool:
	for name in names:
		if not InputMap.has_action(str(name)):
			return false
	return true


func _load_adapter_scripts() -> void:
	var base_dir := _script_base_dir()
	_protocol_script = load(base_dir.path_join("xace_protocol.gd"))


func _script_base_dir() -> String:
	var own_script: Script = get_script()
	var resource_path := own_script.resource_path if own_script != null else ""
	if resource_path.is_empty():
		return "res://"
	return resource_path.get_base_dir()
