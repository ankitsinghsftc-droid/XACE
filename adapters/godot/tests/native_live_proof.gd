extends SceneTree
var options: Dictionary = {}
var transport: Node
var manager: Node3D
var adapter: Node
var ticks: Array = []
var owners: Dictionary = {}
var errors: Array = []
var reconnected := false
var finished := false
func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var parts := arg.split("=",true,1)
		if parts.size() == 2: options[parts[0]] = parts[1]
	call_deferred("_run")
func _run() -> void:
	transport = load("res://xace_transport.gd").new()
	transport.name = "Transport"
	transport.port = int(options["--port"])
	transport.cgs_hash = str(JSON.parse_string(FileAccess.get_file_as_string(str(options["--cgs"]))).metadata.cgs_hash)
	transport.reconnect_enabled = true
	transport.reconnect_delay_sec = 0.1
	assert(transport.configure_live_session(JSON.parse_string(FileAccess.get_file_as_string(str(options["--ticket"]))), FileAccess.get_file_as_string(str(options["--world"]))))
	root.add_child(transport)
	manager = load("res://xace_canonical_entities.gd").new()
	manager.name = "Entities"
	manager.create_visual_nodes = false
	manager.interpolate_transforms = false
	root.add_child(manager)
	var collector: Node = load("res://xace_input_collector.gd").new()
	collector.name = "Input"
	root.add_child(collector)
	adapter = load("res://xace_adapter.gd").new()
	adapter.name = "Adapter"
	adapter.transport_path = NodePath("../Transport")
	adapter.entity_manager_path = NodePath("../Entities")
	adapter.input_collector_path = NodePath("../Input")
	adapter.auto_connect = false
	root.add_child(adapter)
	transport.protocol_error.connect(func(message: String): errors.append(message))
	transport.handshake_accepted.connect(func(ack: Dictionary): owners[int(ack.assigned_player_id)] = true)
	adapter.tick_applied.connect(_tick)
	transport.connect_to_runtime()
	await create_timer(30).timeout
	if not finished: _finish(false)
func _tick(tick: int) -> void:
	ticks.append(tick)
	if ticks.size() == 3 and not reconnected:
		reconnected = true
		transport.disconnect_from_runtime("XP-016 reconnect proof")
	if ticks.size() >= 8 and int(transport.native_contract.stamp.get("connection_generation", 0)) == 2:
		_finish(true)
func _finish(success: bool) -> void:
	if finished: return
	finished = true
	var report := {"schema":"xace.native_live_proof.v1","engine":"godot","ok":success and errors.is_empty() and owners.size()==1,"ticks":ticks,"owners":owners.keys(),"generation":int(transport.native_contract.stamp.get("connection_generation",0)),"bound_objects":transport.native_contract.bindings.size(),"errors":errors}
	FileAccess.open(str(options["--report"]),FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
	transport.disconnect_from_runtime("proof completed")
	quit(0 if report.ok else 1)
