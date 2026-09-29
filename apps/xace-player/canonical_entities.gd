extends "res://adapter/xace_entity_manager.gd"

var presentation: Node

# Typed canonical components, never a flattened bag or a noun-based visual rule.
func _apply_component_visuals(entity_id: int) -> void:
	var node: Node3D = get_entity_node(entity_id)
	if node == null:
		return
	var components: Dictionary = component_snapshot(entity_id)
	var transform: Dictionary = components.get(1, {}).get("data", {})
	node.position = _fixed_vector(transform.get("position", {}))
	node.scale = _fixed_vector(transform.get("scale", {"x":1000000,"y":1000000,"z":1000000}))
	var q: Dictionary = transform.get("rotation", {"w":1000000})
	node.quaternion = Quaternion(float(q.get("x",0))/1000000.0, float(q.get("y",0))/1000000.0, float(q.get("z",0))/1000000.0, float(q.get("w",1000000))/1000000.0).normalized()
	var visual := node.get_node_or_null("CanonicalVisual") as MeshInstance3D
	if visual == null:
		visual = MeshInstance3D.new()
		visual.name = "CanonicalVisual"
		visual.mesh = BoxMesh.new()
		var material := StandardMaterial3D.new()
		material.albedo_color = Color(0.38,0.6,0.82)
		visual.material_override = material
		node.add_child(visual)
	var collider: Dictionary = components.get(4, {}).get("data", {})
	(visual.mesh as BoxMesh).size = _fixed_vector(collider.get("size", {"x":250000,"y":250000,"z":250000})) if collider.get("shape","") == "BOX" else Vector3.ONE * 0.25
	visual.position = _fixed_vector(collider.get("offset", {}))
	visual.visible = not bool(collider.get("is_trigger", false)) and not node.has_meta("xace_presentation_visual")

func _fixed_vector(value: Dictionary) -> Vector3:
	return Vector3(float(value.get("x",0)),float(value.get("y",0)),float(value.get("z",0)))/1000000.0

func controlled_entities(controller: int) -> Array:
	var result: Array = []
	for id in _components:
		var input: Dictionary = _components[id].get(6, {}).get("data", {})
		if int(input.get("controller_id",0)) == controller and str(input.get("control_type","")) == "HUMAN":
			result.append(int(id))
	result.sort()
	return result

func _script_base_dir() -> String:
	return "res://adapter"

func sync_hierarchy() -> String:
	var parents: Dictionary = {}
	for id in _components:
		parents[int(id)] = int(_components[id].get(1, {}).get("data", {}).get("parent_entity_id",0))
	for id in parents:
		var seen: Dictionary = {}
		var current: int = int(id)
		while current != 0:
			if seen.has(current) or not parents.has(current):
				return "Invalid or unresolved canonical transform parent"
			seen[current] = true
			current = int(parents[current])
	for id in parents:
		var parent: Node = self if parents[id] == 0 else get_entity_node(parents[id])
		var node: Node3D = get_entity_node(id)
		if node.get_parent() != parent:
			node.reparent(parent,false)
	return ""

func apply_playback_commands(_commands: Array) -> void:
	# Player resources are resolved only by the admitted data-only catalog.
	pass

func apply_tick_snapshot(snapshot: Dictionary) -> void:
	super.apply_tick_snapshot(snapshot)
	if presentation != null:
		presentation.apply_snapshot(snapshot)

func rollback_side_effects(message: Dictionary) -> void:
	if presentation != null:
		presentation.rollback(int(message.get("restore_tick",0)))
	super.rollback_side_effects(message)
	if presentation != null:
		presentation.restore_static()
