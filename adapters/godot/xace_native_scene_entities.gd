extends "xace_canonical_entities.gd"
# Explicit existing nodes, never mirrors. Static translation-only hierarchy.
var native_objects: Dictionary = {}
var contract: RefCounted
var native_error := ""

func validate(world: Dictionary) -> String:
	if native_objects.size() != world.get("objects",[]).size(): return "Native World object count differs"
	for object in world.get("objects",[]):
		var node: Node3D = native_objects.get(str(object.id))
		if not is_instance_valid(node): return "Missing native object: " + str(object.id)
		if node.global_position.distance_to(_fixed_vector(object.transform.position)) > 0.00001: return "Native starting position differs: " + str(object.id)
		var parent: Node = node.get_parent()
		var nearest := ""
		while parent != null:
			if parent is Node3D and not parent.transform.basis.is_equal_approx(Basis.IDENTITY): return "Only static translation parents supported"
			for id in native_objects:
				if native_objects[id] == parent and nearest.is_empty(): nearest = str(id)
			parent = parent.get_parent()
		var expected: Array = object.relationships.get("xace.authoring_parent.v1",[])
		if expected != ([] if nearest.is_empty() else [nearest]): return "Native parent differs"
		if not node.basis.is_equal_approx(Basis.IDENTITY) or node is RigidBody3D: return "Native pose/physics profile unsupported"
	return ""

func _ensure_node(entity_id: int, _actor_id: String, _tags: Array) -> Node3D:
	if _nodes.has(entity_id): return _nodes[entity_id]
	for id in contract.bindings:
		if int(contract.bindings[id]) == entity_id and native_objects.has(id):
			var node: Node3D = native_objects[id]
			_nodes[entity_id] = node
			node.set_meta("xace_entity_id",entity_id)
			node.visible = true
			return node
	native_error = "Runtime entity has no approved native object"
	return null

func _apply_component_visuals(entity_id: int) -> void:
	var node: Node3D = get_entity_node(entity_id)
	if not is_instance_valid(node): return
	var pose: Dictionary = component_snapshot(entity_id).get(1,{}).get("data",{})
	node.global_position = _fixed_vector(pose.get("position",{}))

func sync_hierarchy() -> String:
	if not native_error.is_empty(): return native_error
	var ordered: Array = _nodes.keys()
	ordered.sort_custom(func(a,b): return _nodes[a].get_path().get_name_count() < _nodes[b].get_path().get_name_count() if _nodes[a].get_path().get_name_count() != _nodes[b].get_path().get_name_count() else a < b)
	for id in ordered: _apply_component_visuals(int(id))
	return ""

func destroy_entity(entity_id: int) -> void:
	if _nodes.has(entity_id):
		_nodes[entity_id].visible = false
		_nodes.erase(entity_id)
	_target_positions.erase(entity_id)
	_components.erase(entity_id)
	_actor_ids.erase(entity_id)
	_recent_playback_commands.erase(entity_id)
	entity_destroyed.emit(entity_id)
