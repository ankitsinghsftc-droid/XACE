extends Node3D

@export var default_host := "127.0.0.1"
@export var default_port := 7777
@export var default_cgs_hash := ""
@export var camera_follow_enabled := true
@export var camera_target_entity_id := 1
@export var camera_follow_offset := Vector3(0.0, 12.0, 13.0)
@export var camera_follow_lerp_speed := 2.5
@export var camera_bounds_min := Vector2(-12.0, -12.0)
@export var camera_bounds_max := Vector2(12.0, 12.0)

var _adapter: Node
var _entity_manager: Node
var _camera: Camera3D
var _adapter_script: Script
var _debug_hud_script: Script
var _delta_applicator_script: Script
var _entity_manager_script: Script
var _input_collector_script: Script
var _transport_script: Script


func _ready() -> void:
	_load_adapter_scripts()
	_install_default_input_map()
	_build_world()
	_build_xace_nodes()


func _process(delta: float) -> void:
	_update_camera_follow(delta)


func _build_xace_nodes() -> void:
	var config := _runtime_config_from_args()

	var transport: Node = _transport_script.new()
	transport.name = "XaceTransport"
	transport.host = str(config.get("host", default_host))
	transport.port = int(config.get("port", default_port))
	transport.cgs_hash = str(config.get("cgs_hash", default_cgs_hash))
	add_child(transport)

	var entity_manager: Node = _entity_manager_script.new()
	entity_manager.name = "XaceEntityManager"
	add_child(entity_manager)
	_entity_manager = entity_manager

	var input_collector: Node = _input_collector_script.new()
	input_collector.name = "XaceInputCollector"
	input_collector.movement_action = ""
	input_collector.emit_idle_movement = true
	add_child(input_collector)

	var delta_applicator: Node = _delta_applicator_script.new()
	delta_applicator.name = "XaceDeltaApplicator"
	add_child(delta_applicator)

	var hud_layer := CanvasLayer.new()
	hud_layer.name = "XaceHudLayer"
	add_child(hud_layer)

	var hud: Control = _debug_hud_script.new()
	hud.name = "XaceDebugHUD"
	hud_layer.add_child(hud)

	_adapter = _adapter_script.new()
	_adapter.name = "XaceAdapter"
	_adapter.transport_path = NodePath("../XaceTransport")
	_adapter.entity_manager_path = NodePath("../XaceEntityManager")
	_adapter.input_collector_path = NodePath("../XaceInputCollector")
	_adapter.delta_applicator_path = NodePath("../XaceDeltaApplicator")
	_adapter.debug_hud_path = NodePath("../XaceHudLayer/XaceDebugHUD")
	_adapter.auto_connect = true
	_adapter.player_id = 1
	add_child(_adapter)


func _build_world() -> void:
	var floor := MeshInstance3D.new()
	floor.name = "HorrorFloor"
	var plane := PlaneMesh.new()
	plane.size = Vector2(24.0, 24.0)
	floor.mesh = plane
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(0.035, 0.045, 0.06, 1.0)
	material.roughness = 1.0
	floor.material_override = material
	add_child(floor)
	_add_floor_reference_lines()

	var light := DirectionalLight3D.new()
	light.name = "MoonLight"
	light.rotation_degrees = Vector3(-48.0, -30.0, 0.0)
	light.light_energy = 1.2
	add_child(light)

	var camera := Camera3D.new()
	camera.name = "Camera3D"
	camera.position = Vector3(0.0, 12.0, 13.0)
	camera.rotation_degrees = Vector3(-42.0, 0.0, 0.0)
	camera.current = true
	add_child(camera)
	_camera = camera


func _update_camera_follow(delta: float) -> void:
	if not camera_follow_enabled or _camera == null or _entity_manager == null:
		return
	if not _entity_manager.has_method("get_entity_node"):
		return
	var target_node_value: Variant = _entity_manager.call("get_entity_node", camera_target_entity_id)
	if target_node_value == null or not (target_node_value is Node3D):
		return
	var target_node: Node3D = target_node_value as Node3D
	var target_position: Vector3 = target_node.global_position
	var desired: Vector3 = target_position + camera_follow_offset
	desired.x = clampf(desired.x, camera_bounds_min.x + camera_follow_offset.x, camera_bounds_max.x + camera_follow_offset.x)
	desired.z = clampf(desired.z, camera_bounds_min.y + camera_follow_offset.z, camera_bounds_max.y + camera_follow_offset.z)
	var alpha: float = clampf(delta * camera_follow_lerp_speed, 0.0, 1.0)
	_camera.global_position = _camera.global_position.lerp(desired, alpha)
	_camera.look_at(target_position, Vector3.UP)


func _add_floor_reference_lines() -> void:
	var line_material := StandardMaterial3D.new()
	line_material.albedo_color = Color(0.28, 0.36, 0.46, 1.0)
	line_material.emission_enabled = true
	line_material.emission = Color(0.08, 0.12, 0.16, 1.0)
	for x in range(-12, 13, 4):
		_add_floor_line(Vector3(float(x), 0.03, -12.0), Vector3(float(x), 0.03, 12.0), line_material)
	for z in range(-12, 13, 4):
		_add_floor_line(Vector3(-12.0, 0.03, float(z)), Vector3(12.0, 0.03, float(z)), line_material)
	var boundary_material := StandardMaterial3D.new()
	boundary_material.albedo_color = Color(0.85, 0.18, 0.18, 1.0)
	boundary_material.emission_enabled = true
	boundary_material.emission = Color(0.18, 0.03, 0.03, 1.0)
	_add_floor_line(Vector3(-12.0, 0.05, -12.0), Vector3(12.0, 0.05, -12.0), boundary_material)
	_add_floor_line(Vector3(12.0, 0.05, -12.0), Vector3(12.0, 0.05, 12.0), boundary_material)
	_add_floor_line(Vector3(12.0, 0.05, 12.0), Vector3(-12.0, 0.05, 12.0), boundary_material)
	_add_floor_line(Vector3(-12.0, 0.05, 12.0), Vector3(-12.0, 0.05, -12.0), boundary_material)


func _add_floor_line(start: Vector3, end: Vector3, material: StandardMaterial3D) -> void:
	var mesh_instance := MeshInstance3D.new()
	var mesh := BoxMesh.new()
	var delta := end - start
	mesh.size = Vector3(0.08, 0.04, max(0.08, delta.length()))
	mesh_instance.mesh = mesh
	mesh_instance.material_override = material
	mesh_instance.position = (start + end) * 0.5
	add_child(mesh_instance)
	mesh_instance.look_at(end, Vector3.UP)


func _install_default_input_map() -> void:
	_add_action_key("move_left", KEY_A)
	_add_action_key("move_left", KEY_LEFT)
	_add_action_key("move_right", KEY_D)
	_add_action_key("move_right", KEY_RIGHT)
	_add_action_key("move_forward", KEY_W)
	_add_action_key("move_forward", KEY_UP)
	_add_action_key("move_back", KEY_S)
	_add_action_key("move_back", KEY_DOWN)
	_add_action_key("attack", KEY_SPACE)
	_add_action_key("interact", KEY_E)
	_add_action_key("dash", KEY_SHIFT)


func _add_action_key(action_name: String, keycode: int) -> void:
	if not InputMap.has_action(action_name):
		InputMap.add_action(action_name)
	var event := InputEventKey.new()
	event.physical_keycode = keycode
	for existing in InputMap.action_get_events(action_name):
		if existing is InputEventKey and existing.physical_keycode == keycode:
			return
	InputMap.action_add_event(action_name, event)


func _runtime_config_from_args() -> Dictionary:
	var config := {
		"host": default_host,
		"port": default_port,
		"cgs_hash": default_cgs_hash,
	}
	var args := OS.get_cmdline_args()
	args.append_array(OS.get_cmdline_user_args())
	for arg in args:
		if arg.begins_with("--xace-host="):
			config["host"] = arg.substr("--xace-host=".length())
		elif arg.begins_with("--xace-port="):
			config["port"] = int(arg.substr("--xace-port=".length()))
		elif arg.begins_with("--xace-cgs-hash="):
			config["cgs_hash"] = arg.substr("--xace-cgs-hash=".length())
	return config


func _load_adapter_scripts() -> void:
	var base_dir := _script_base_dir()
	_adapter_script = load(base_dir.path_join("xace_adapter.gd"))
	_debug_hud_script = load(base_dir.path_join("xace_debug_hud.gd"))
	_delta_applicator_script = load(base_dir.path_join("xace_delta_applicator.gd"))
	_entity_manager_script = load(base_dir.path_join("xace_entity_manager.gd"))
	_input_collector_script = load(base_dir.path_join("xace_input_collector.gd"))
	_transport_script = load(base_dir.path_join("xace_transport.gd"))


func _script_base_dir() -> String:
	var own_script: Script = get_script()
	var resource_path := own_script.resource_path if own_script != null else ""
	if resource_path.is_empty():
		return "res://"
	return resource_path.get_base_dir()
