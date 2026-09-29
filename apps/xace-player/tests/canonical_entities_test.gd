extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _entity(id: int, position: Dictionary, parent: int, controller: int) -> Dictionary:
	return {"id":id,"components":{
		"1":JSON.stringify({"position":position,"scale":{"x":1000000,"y":1000000,"z":1000000},"rotation":{"w":1000000,"x":0,"y":0,"z":0},"parent_entity_id":parent}),
		"4":JSON.stringify({"shape":"BOX","size":{"x":2000000,"y":1000000,"z":3000000},"offset":{"x":500000,"y":0,"z":0}}),
		"6":JSON.stringify({"controller_id":controller,"control_type":"HUMAN"}),
		"12345":JSON.stringify({"semantic_type":"project.new_noun.v1","position":{"x":999999999,"y":0,"z":0}})
	}}

func _run() -> void:
	var manager: Node3D = load("res://canonical_entities.gd").new()
	manager.create_visual_nodes = false
	manager.interpolate_transforms = false
	root.add_child(manager)
	manager.apply_handshake_ack({"accepted":true,"initial_entities":[_entity(10,{"x":5000000,"y":0,"z":0},0,0),_entity(42,{"x":1000000,"y":0,"z":0},10,7)]})
	assert(manager.controlled_entities(7)==[42])
	assert(manager.sync_hierarchy()=="")
	var child: Node3D=manager.get_entity_node(42)
	assert(child.position==Vector3(1,0,0))
	assert(child.global_position==Vector3(6,0,0))
	var mesh: MeshInstance3D=child.get_node("CanonicalVisual")
	assert((mesh.mesh as BoxMesh).size==Vector3(2,1,3))
	assert(mesh.position==Vector3(0.5,0,0))
	manager.upsert_legacy_entity(_entity(10,{"x":5000000,"y":0,"z":0},42,0))
	assert(not manager.sync_hierarchy().is_empty())
	assert(child.get_parent()==manager.get_entity_node(10))
	print("XP008 canonical presentation: 8 assertions passed")
	quit()
