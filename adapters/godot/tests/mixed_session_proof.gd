extends SceneTree
var config: Dictionary
var transport: Node
var manager: Node3D
var finished := false
func record(row: Dictionary) -> void:
	var f := FileAccess.open(str(config.transcript),FileAccess.READ_WRITE) if FileAccess.file_exists(str(config.transcript)) else FileAccess.open(str(config.transcript),FileAccess.WRITE)
	f.seek_end()
	f.store_line(JSON.stringify(row))
func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--config="):config=JSON.parse_string(FileAccess.get_file_as_string(arg.trim_prefix("--config=")))
	call_deferred("run")
func run() -> void:
	transport=load("res://xace_transport.gd").new()
	transport.name="Transport"
	transport.port=int(config.port)
	transport.cgs_hash=str(config.cgs_hash)
	transport.reconnect_enabled=false
	assert(transport.configure_live_session(JSON.parse_string(FileAccess.get_file_as_string(str(config.ticket))),FileAccess.get_file_as_string(str(config.world))))
	root.add_child(transport)
	manager=load("res://xace_canonical_entities.gd").new()
	manager.name="Entities"
	manager.create_visual_nodes=false
	manager.interpolate_transforms=false
	root.add_child(manager)
	var adapter: Node=load("res://xace_adapter.gd").new()
	adapter.transport_path=NodePath("../Transport")
	adapter.entity_manager_path=NodePath("../Entities")
	adapter.auto_connect=false
	root.add_child(adapter)
	transport.protocol_error.connect(func(error):record({"kind":"error","message":error}))
	transport.handshake_accepted.connect(func(ack):record({"kind":"ready","peer":transport.native_contract.peer_id,"player":transport.native_contract.player_id,"epoch":ack.sync,"version":Engine.get_version_info().string}))
	transport.message_received.connect(func(m):
		if m.msg_type=="input_tick_request":
			if not adapter.send_input_actions(config.inputs[int(m.tick)],int(m.tick),false):
				record({"kind":"error","message":"Recorded input could not be sent"})
				quit(1)
				return
			record({"kind":"input","tick":int(m.tick),"actions":config.inputs[int(m.tick)]})
		if m.msg_type=="tick_snapshot":
			var applied := true
			for e in m.entities:
				var node: Node3D=manager.get_entity_node(int(e.id))
				applied=applied and node!=null
				for key in e.components:
					applied=applied and manager.component_snapshot(int(e.id)).get(int(key),{}).get("data") == JSON.parse_string(e.components[key])
				if e.components.has("1"):
					applied=applied and node.position.is_equal_approx(manager._fixed_vector(JSON.parse_string(e.components["1"]).position))
			record({"kind":"tick","tick":int(m.tick),"applied":applied,"projection_json":m.projection_json,"sync":m.sync,"events":m.events})
			if int(m.tick)==int(config.stop_tick):
				finished=true
				transport.disconnect_from_runtime("proof leave")
				record({"kind":"done","ok":true})
				quit(0)
	)
	transport.connect_to_runtime()
	await create_timer(180).timeout
	if not finished:quit(1)
