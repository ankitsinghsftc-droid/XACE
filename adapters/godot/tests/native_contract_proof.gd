extends SceneTree
func _initialize() -> void:
	call_deferred("_run")
func _run() -> void:
	var options: Dictionary = {}
	for arg in OS.get_cmdline_user_args():
		var parts := arg.split("=",true,1)
		if parts.size() == 2: options[parts[0]] = parts[1]
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(str(options["--fixture"])))
	var policy: Script = load("res://xace_native_contract.gd")
	var results: Array = []
	for case in fixture.cases:
		var session: RefCounted = policy.new()
		var configured: bool = session.configure(JSON.parse_string(fixture.ticket_json),fixture.world_json)
		var ok := configured
		for message in case.messages:
			ok = session.verify(message.duplicate(true)) == "accept" and ok
		var result: String = session.verify(case.message.duplicate(true))
		results.append({"name":str(case.name),"result":result,"ok":ok and result == case.expected})
	var session: RefCounted = policy.new()
	assert(session.configure(JSON.parse_string(fixture.ticket_json),fixture.world_json))
	var baseline: Dictionary = fixture.baseline.duplicate(true)
	assert(session.verify(baseline) == "accept")
	var manager: Node3D = load("res://xace_canonical_entities.gd").new()
	manager.create_visual_nodes = false
	manager.interpolate_transforms = false
	root.add_child(manager)
	manager.apply_handshake_ack(baseline)
	var hierarchy: String = manager.sync_hierarchy()
	manager.bind_semantics(session)
	var marker: Node3D = manager.get_entity_node(42)
	var solid: MeshInstance3D = manager.get_entity_node(77).get_node("CanonicalVisual")
	var normal: Vector3 = marker.basis.orthonormalized() * Vector3(0,0,1)
	var position := marker.global_position
	var geometry_ok: bool = marker.global_position.is_equal_approx(Vector3(6,2,3)) and normal.is_equal_approx(Vector3(1,0,0)) and (solid.mesh as BoxMesh).size == Vector3(2,4,6) and hierarchy.is_empty() and marker.get_meta("xace_object_id") == "marker"
	var packet := {"tick":7,"peer_id":2,"player_id":42}
	geometry_ok = geometry_ok and marker.get_meta("xace_world_objects").size() == 2
	var input_ok: bool = not session.can_send(packet) and session.request(7) and session.can_send(packet)
	session.sent = true
	input_ok = input_ok and not session.can_send(packet) and not session.request(7)
	manager.destroy_entity(10)
	await process_frame
	var independent_lifetime: bool = is_instance_valid(marker) and manager.get_entity_node(42) == marker and marker.get_parent() == manager
	var ok: bool = geometry_ok and input_ok and independent_lifetime
	for result in results: ok = bool(result.ok) and ok
	var report := {"schema":"xace.native_contract_proof.v1","engine":"godot","version":Engine.get_version_info().string,"ok":ok,"cases":results,"geometry":geometry_ok,"input_fence":input_ok,"independent_entity_lifetimes":independent_lifetime,"position":[position.x,position.y,position.z],"normal":[normal.x,normal.y,normal.z]}
	FileAccess.open(str(options["--report"]),FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
	print(JSON.stringify(report))
	quit(0 if ok else 1)
