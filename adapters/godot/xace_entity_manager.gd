extends Node3D
class_name XaceEntityManager

signal entity_spawned(entity_id: int, node: Node3D)
signal entity_updated(entity_id: int, node: Node3D)
signal entity_destroyed(entity_id: int)
signal playback_command_applied(command: Dictionary, applied: bool)

@export var create_visual_nodes := true
@export var default_scale := Vector3(0.8, 1.8, 0.8)
@export var player_color := Color(0.2, 0.45, 1.0, 1.0)
@export var zombie_color := Color(0.2, 0.8, 0.35, 1.0)
@export var neutral_color := Color(0.75, 0.75, 0.78, 1.0)
@export var interpolate_transforms := true
@export var interpolation_speed := 18.0
@export var snap_distance := 8.0

var _nodes: Dictionary = {}
var _components: Dictionary = {}
var _actor_ids: Dictionary = {}
var _target_positions: Dictionary = {}
var _recent_playback_commands: Dictionary = {}
var _last_tick := 0
var _protocol_script: Script


func _ready() -> void:
	_load_adapter_scripts()
	set_process(true)


func _process(delta: float) -> void:
	if not interpolate_transforms:
		return
	var alpha: float = clampf(delta * interpolation_speed, 0.0, 1.0)
	for entity_id in _target_positions.keys():
		var node: Node3D = _nodes.get(entity_id, null)
		if node == null:
			continue
		var target: Vector3 = _target_positions[entity_id]
		if node.position.distance_to(target) > snap_distance:
			node.position = target
		else:
			node.position = node.position.lerp(target, alpha)


func apply_message(message: Dictionary) -> void:
	var kind: String = _protocol_script.classify_message(message)
	if kind == _protocol_script.MSG_HANDSHAKE_ACK:
		apply_handshake_ack(message)
	elif kind == _protocol_script.MSG_TICK_SNAPSHOT:
		apply_tick_snapshot(message)
	elif kind == _protocol_script.WIRE_SNAPSHOT:
		apply_snapshot_payload(_protocol_script.payload_dictionary(message))
	elif kind == _protocol_script.WIRE_DELTA:
		apply_delta_payload(_protocol_script.payload_dictionary(message))


func apply_handshake_ack(ack: Dictionary) -> void:
	if not bool(ack.get("accepted", false)):
		return
	var snapshot: Dictionary = {
		"tick": 0,
		"entities": ack.get("initial_entities", []),
		"spawned_ids": [],
		"destroyed_ids": [],
	}
	apply_tick_snapshot(snapshot)


func apply_tick_snapshot(snapshot: Dictionary) -> void:
	_last_tick = int(snapshot.get("tick", _last_tick))
	var destroyed_ids = snapshot.get("destroyed_ids", [])
	for entity_id in destroyed_ids:
		destroy_entity(int(entity_id))

	var seen: Dictionary = {}
	for entity in snapshot.get("entities", []):
		if typeof(entity) == TYPE_DICTIONARY:
			var entity_id := int(entity.get("id", entity.get("entity_id", 0)))
			if entity_id > 0:
				seen[entity_id] = true
				upsert_legacy_entity(entity)
	apply_playback_commands(snapshot.get("playback_commands", []))


func apply_snapshot_payload(payload: Dictionary) -> void:
	_last_tick = int(payload.get("tick", _last_tick))
	var live_ids: Dictionary = {}
	for entity in payload.get("entities", []):
		if typeof(entity) != TYPE_DICTIONARY:
			continue
		var entity_id := int(entity.get("entity_id", 0))
		if entity_id <= 0:
			continue
		live_ids[entity_id] = true
		upsert_snapshot_entity(entity)

	for entity_id in _nodes.keys():
		if not live_ids.has(entity_id):
			destroy_entity(int(entity_id))


func apply_delta_payload(payload: Dictionary) -> void:
	_last_tick = int(payload.get("tick", _last_tick))
	for spawned in payload.get("spawned_entities", []):
		if typeof(spawned) == TYPE_DICTIONARY:
			upsert_delta_spawn(spawned)
	for addition in payload.get("added_components", []):
		if typeof(addition) == TYPE_DICTIONARY:
			apply_component_addition(addition)
	for entity_id_key in payload.get("modified_entities", {}).keys():
		var update = payload["modified_entities"][entity_id_key]
		if typeof(update) == TYPE_DICTIONARY:
			apply_entity_update(update)
	for removal in payload.get("removed_components", []):
		if typeof(removal) == TYPE_DICTIONARY:
			apply_component_removal(removal)
	for destroyed in payload.get("destroyed_entities", []):
		if typeof(destroyed) == TYPE_DICTIONARY:
			destroy_entity(int(destroyed.get("entity_id", 0)))


func upsert_legacy_entity(entity: Dictionary) -> Node3D:
	var entity_id := int(entity.get("id", entity.get("entity_id", 0)))
	var actor_id := str(entity.get("actor_id", ""))
	var node: Node3D = _ensure_node(entity_id, actor_id, [])
	var component_map: Dictionary = {}
	var raw_components = entity.get("components", {})
	if typeof(raw_components) == TYPE_DICTIONARY:
		for type_id in raw_components.keys():
			var parsed = _parse_component_json(raw_components[type_id])
			component_map[int(type_id)] = {
				"component_type_id": int(type_id),
				"component_type_name": "",
				"data": parsed,
			}
	_components[entity_id] = component_map
	_actor_ids[entity_id] = actor_id
	_apply_component_visuals(entity_id)
	entity_updated.emit(entity_id, node)
	return node


func upsert_snapshot_entity(entity: Dictionary) -> Node3D:
	var entity_id := int(entity.get("entity_id", 0))
	var tags = entity.get("tags", [])
	var actor_id: String = _actor_from_tags(tags)
	var component_map: Dictionary = {}
	var components = entity.get("components", {})
	if typeof(components) == TYPE_DICTIONARY:
		for type_id in components.keys():
			var component = components[type_id]
			if typeof(component) == TYPE_DICTIONARY:
				var parsed = _parse_component_json(component.get("data_json", "{}"))
				component_map[int(component.get("component_type_id", type_id))] = {
					"component_type_id": int(component.get("component_type_id", type_id)),
					"component_type_name": str(component.get("component_type_name", "")),
					"data": parsed,
				}
				if actor_id.is_empty():
					actor_id = _actor_from_component(component, parsed)
	var node: Node3D = _ensure_node(entity_id, actor_id, tags)
	_components[entity_id] = component_map
	_actor_ids[entity_id] = actor_id
	_apply_component_visuals(entity_id)
	entity_updated.emit(entity_id, node)
	return node


func upsert_delta_spawn(spawned: Dictionary) -> Node3D:
	var entity_id := int(spawned.get("entity_id", 0))
	var actor_id := str(spawned.get("actor_id", ""))
	var tags = spawned.get("tags", [])
	var node: Node3D = _ensure_node(entity_id, actor_id, tags)
	var component_map: Dictionary = {}
	for component in spawned.get("initial_components", []):
		if typeof(component) == TYPE_DICTIONARY:
			var type_id := int(component.get("component_type_id", 0))
			component_map[type_id] = {
				"component_type_id": type_id,
				"component_type_name": str(component.get("component_type_name", "")),
				"data": _parse_component_json(component.get("data_json", "{}")),
			}
	_components[entity_id] = component_map
	_actor_ids[entity_id] = actor_id
	_apply_component_visuals(entity_id)
	entity_updated.emit(entity_id, node)
	return node


func apply_component_addition(addition: Dictionary) -> void:
	var entity_id := int(addition.get("entity_id", 0))
	var component = addition.get("component", {})
	var node: Node3D = _ensure_node(entity_id, str(_actor_ids.get(entity_id, "")), [])
	var type_id := int(component.get("component_type_id", 0))
	if not _components.has(entity_id):
		_components[entity_id] = {}
	_components[entity_id][type_id] = {
		"component_type_id": type_id,
		"component_type_name": str(component.get("component_type_name", "")),
		"data": _parse_component_json(component.get("data_json", "{}")),
	}
	_apply_component_visuals(entity_id)
	entity_updated.emit(entity_id, node)


func apply_entity_update(update: Dictionary) -> void:
	var entity_id := int(update.get("entity_id", 0))
	if entity_id <= 0:
		return
	var node: Node3D = _ensure_node(entity_id, str(_actor_ids.get(entity_id, "")), [])
	if not _components.has(entity_id):
		_components[entity_id] = {}
	var component_updates = update.get("component_updates", {})
	for type_id_key in component_updates.keys():
		var component_update = component_updates[type_id_key]
		if typeof(component_update) != TYPE_DICTIONARY:
			continue
		var type_id := int(component_update.get("component_type_id", type_id_key))
		var current_value = _components[entity_id].get(type_id, {
			"component_type_id": type_id,
			"component_type_name": str(component_update.get("component_type_name", "")),
			"data": {},
		})
		var current: Dictionary = current_value if typeof(current_value) == TYPE_DICTIONARY else {
			"component_type_id": type_id,
			"component_type_name": str(component_update.get("component_type_name", "")),
			"data": {},
		}
		var data = current.get("data", {})
		for change in component_update.get("field_changes", []):
			if typeof(change) == TYPE_DICTIONARY:
				data[str(change.get("field_name", ""))] = _parse_component_json(change.get("value_json", "null"))
		current["data"] = data
		_components[entity_id][type_id] = current
	_apply_component_visuals(entity_id)
	entity_updated.emit(entity_id, node)


func apply_component_removal(removal: Dictionary) -> void:
	var entity_id := int(removal.get("entity_id", 0))
	var type_id := int(removal.get("component_type_id", 0))
	if _components.has(entity_id):
		_components[entity_id].erase(type_id)
	_apply_component_visuals(entity_id)
	if _nodes.has(entity_id):
		entity_updated.emit(entity_id, _nodes[entity_id])


func destroy_entity(entity_id: int) -> void:
	if entity_id <= 0:
		return
	if _nodes.has(entity_id):
		var node: Node = _nodes[entity_id]
		_nodes.erase(entity_id)
		_target_positions.erase(entity_id)
		node.queue_free()
	_components.erase(entity_id)
	_actor_ids.erase(entity_id)
	_recent_playback_commands.erase(entity_id)
	entity_destroyed.emit(entity_id)


func get_entity_node(entity_id: int) -> Node3D:
	return _nodes.get(entity_id, null)


func entity_count() -> int:
	return _nodes.size()


func last_tick() -> int:
	return _last_tick


func component_snapshot(entity_id: int) -> Dictionary:
	return _components.get(entity_id, {}).duplicate(true)


func playback_commands_for_entity(entity_id: int) -> Array:
	return _recent_playback_commands.get(entity_id, []).duplicate(true)


func apply_playback_commands(commands: Array) -> void:
	for command in commands:
		if typeof(command) != TYPE_DICTIONARY:
			continue
		var entity_id := int(command.get("entity_id", 0))
		var node: Node3D = get_entity_node(entity_id)
		if node == null:
			playback_command_applied.emit(command.duplicate(true), false)
			continue
		if not _recent_playback_commands.has(entity_id):
			_recent_playback_commands[entity_id] = []
		_recent_playback_commands[entity_id].append(command.duplicate(true))
		while _recent_playback_commands[entity_id].size() > 32:
			_recent_playback_commands[entity_id].pop_front()
		var applied := _try_apply_playback_command(node, command)
		playback_command_applied.emit(command.duplicate(true), applied)


func _ensure_node(entity_id: int, actor_id: String, tags: Array) -> Node3D:
	if entity_id <= 0:
		return null
	if _nodes.has(entity_id):
		return _nodes[entity_id]

	var node: Node3D = Node3D.new()
	node.name = "XACE_%d_%s" % [entity_id, _safe_name(actor_id)]
	node.set_meta("xace_entity_id", entity_id)
	add_child(node)
	_nodes[entity_id] = node

	if create_visual_nodes:
		_create_default_visual(node, actor_id, tags)

	entity_spawned.emit(entity_id, node)
	return node


func _create_default_visual(node: Node3D, actor_id: String, tags: Array) -> void:
	var mesh_instance: MeshInstance3D = MeshInstance3D.new()
	mesh_instance.name = "Visual"
	var mesh: CapsuleMesh = CapsuleMesh.new()
	mesh.radius = 0.35
	mesh.height = 1.4
	mesh_instance.mesh = mesh
	mesh_instance.material_override = _material_for(actor_id, tags)
	node.add_child(mesh_instance)

	var label: Label3D = Label3D.new()
	label.name = "Label"
	label.text = actor_id if not actor_id.is_empty() else str(node.get_meta("xace_entity_id"))
	label.position = Vector3(0.0, 1.2, 0.0)
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	node.add_child(label)


func _try_apply_playback_command(node: Node3D, command: Dictionary) -> bool:
	var kind := str(command.get("playback_kind", "")).to_lower()
	match kind:
		"audio":
			return _try_apply_audio_command(node, command)
		"animation":
			return _try_apply_animation_command(node, command)
		"vfx":
			return _try_apply_vfx_command(node, command)
		_:
			return false


func _try_apply_audio_command(node: Node3D, command: Dictionary) -> bool:
	var stream: AudioStream = _load_command_resource(command)
	var player: AudioStreamPlayer3D = _find_child_of_class(node, "AudioStreamPlayer3D") as AudioStreamPlayer3D
	if player == null and stream != null:
		player = AudioStreamPlayer3D.new()
		player.name = "XaceAudio"
		node.add_child(player)
	if player == null:
		return false
	if stream != null:
		player.stream = stream
	if player.stream == null:
		return false
	player.play()
	return true


func _try_apply_animation_command(node: Node3D, command: Dictionary) -> bool:
	var player: AnimationPlayer = _find_child_of_class(node, "AnimationPlayer") as AnimationPlayer
	if player == null:
		return false
	var action := str(command.get("semantic_action", ""))
	var parameters: Dictionary = _command_parameters(command)
	if parameters.has("animation"):
		action = str(parameters["animation"])
	if parameters.has("state"):
		action = str(parameters["state"])
	if not action.is_empty() and player.has_animation(action):
		player.play(action)
		return true
	var resource: Resource = _load_command_resource(command)
	if resource is Animation and player.has_method("add_animation"):
		var clip_name := _asset_id(command)
		if not action.is_empty():
			clip_name = action
		player.call("add_animation", clip_name, resource)
		player.play(clip_name)
		return true
	return false


func _try_apply_vfx_command(node: Node3D, command: Dictionary) -> bool:
	var resource: Resource = _load_command_resource(command)
	if resource is PackedScene:
		var instance: Node = resource.instantiate()
		if instance is Node:
			instance.name = "XaceVfx"
			node.add_child(instance)
			_start_particles(instance)
			return true
	if _start_particles(node):
		return true
	return false


func _start_particles(root: Node) -> bool:
	var started := false
	if root is GPUParticles3D or root is CPUParticles3D:
		root.set("emitting", true)
		started = true
	for child in root.get_children():
		if child is Node and _start_particles(child):
			started = true
	return started


func _load_command_resource(command: Dictionary) -> Resource:
	var path := _command_resource_path(command)
	if path.is_empty():
		return null
	return load(path)


func _command_resource_path(command: Dictionary) -> String:
	var parameters: Dictionary = _command_parameters(command)
	for key in ["resource_path", "asset_path", "path"]:
		if parameters.has(key):
			var path := str(parameters[key]).strip_edges()
			if not path.is_empty():
				return path
	var asset_id := _asset_id(command)
	if asset_id.begins_with("res://") or asset_id.begins_with("user://"):
		return asset_id
	return ""


func _command_parameters(command: Dictionary) -> Dictionary:
	var parameters = command.get("parameters", {})
	return parameters if typeof(parameters) == TYPE_DICTIONARY else {}


func _asset_id(command: Dictionary) -> String:
	var asset = command.get("asset", {})
	if typeof(asset) == TYPE_DICTIONARY:
		return str(asset.get("id", ""))
	return ""


func _find_child_of_class(root: Node, target_class_name: String) -> Node:
	for child in root.get_children():
		if child.get_class() == target_class_name:
			return child
		var nested := _find_child_of_class(child, target_class_name)
		if nested != null:
			return nested
	return null


func _apply_component_visuals(entity_id: int) -> void:
	var node: Node3D = _nodes.get(entity_id, null)
	if node == null:
		return
	var data: Dictionary = _flatten_component_data(_components.get(entity_id, {}))
	var position = _extract_vec3(data, ["position", "translation", "pos"])
	if position == null:
		position = _extract_flat_vec3(data, "position")
	if position != null:
		if interpolate_transforms and _target_positions.has(entity_id):
			_target_positions[entity_id] = position
		else:
			node.position = position
			_target_positions[entity_id] = position
	var scale = _extract_vec3(data, ["scale"])
	if scale == null:
		scale = _extract_flat_vec3(data, "scale", Vector3.ONE)
	if scale != null:
		node.scale = scale
	elif node.scale == Vector3.ONE:
		node.scale = default_scale
	var health = _extract_number(data, ["health", "hp", "current_health", "current"])
	var label: Node = node.get_node_or_null("Label")
	if label != null and label is Label3D:
		var actor := str(_actor_ids.get(entity_id, ""))
		var suffix := ""
		if health != null:
			suffix = " %.0f" % float(health)
		label.text = ("%s%s" % [actor if not actor.is_empty() else str(entity_id), suffix]).strip_edges()


func _flatten_component_data(component_map: Dictionary) -> Dictionary:
	var out: Dictionary = {}
	for component in component_map.values():
		if typeof(component) != TYPE_DICTIONARY:
			continue
		var data = component.get("data", {})
		if typeof(data) == TYPE_DICTIONARY:
			for key in data.keys():
				out[str(key)] = data[key]
	return out


func _extract_vec3(data: Dictionary, names: Array) -> Variant:
	for name in names:
		if not data.has(name):
			continue
		var value = data[name]
		if typeof(value) == TYPE_DICTIONARY:
			return Vector3(float(value.get("x", 0.0)), float(value.get("y", 0.0)), float(value.get("z", 0.0)))
		if typeof(value) == TYPE_ARRAY and value.size() >= 3:
			return Vector3(float(value[0]), float(value[1]), float(value[2]))
	return null


func _extract_flat_vec3(data: Dictionary, prefix: String, fallback: Vector3 = Vector3.ZERO) -> Variant:
	var x_key := "%s_x" % prefix
	var y_key := "%s_y" % prefix
	var z_key := "%s_z" % prefix
	if data.has(x_key) or data.has(y_key) or data.has(z_key):
		return Vector3(
			float(data.get(x_key, fallback.x)),
			float(data.get(y_key, fallback.y)),
			float(data.get(z_key, fallback.z))
		)
	return null


func _extract_number(data: Dictionary, names: Array) -> Variant:
	for name in names:
		if data.has(name):
			return float(data[name])
	return null


func _parse_component_json(value) -> Variant:
	if typeof(value) == TYPE_DICTIONARY or typeof(value) == TYPE_ARRAY:
		return value
	if typeof(value) != TYPE_STRING:
		return value
	var parsed = JSON.parse_string(value)
	if parsed == null and value != "null":
		return {}
	return parsed


func _actor_from_tags(tags: Array) -> String:
	for tag in tags:
		var lowered := str(tag).to_lower()
		if lowered.contains("player"):
			return "Player"
		if lowered.contains("zombie") or lowered.contains("enemy"):
			return "Zombie"
	return ""


func _actor_from_component(component: Dictionary, parsed) -> String:
	var name := str(component.get("component_type_name", "")).to_lower()
	if typeof(parsed) == TYPE_DICTIONARY:
		for key in ["name", "actor_id", "kind"]:
			if parsed.has(key):
				return str(parsed[key])
	return name


func _material_for(actor_id: String, tags: Array) -> StandardMaterial3D:
	var material: StandardMaterial3D = StandardMaterial3D.new()
	var lowered := actor_id.to_lower()
	for tag in tags:
		lowered += " " + str(tag).to_lower()
	if lowered.contains("player"):
		material.albedo_color = player_color
	elif lowered.contains("zombie") or lowered.contains("enemy"):
		material.albedo_color = zombie_color
	else:
		material.albedo_color = neutral_color
	return material


func _safe_name(value: String) -> String:
	var cleaned := value.strip_edges().replace(" ", "_")
	if cleaned.is_empty():
		return "Entity"
	return cleaned


func _load_adapter_scripts() -> void:
	var base_dir := _script_base_dir()
	_protocol_script = load(base_dir.path_join("xace_protocol.gd"))


func _script_base_dir() -> String:
	var own_script: Script = get_script()
	var resource_path := own_script.resource_path if own_script != null else ""
	if resource_path.is_empty():
		return "res://"
	return resource_path.get_base_dir()
