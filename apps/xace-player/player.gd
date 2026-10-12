extends Node3D

const Adapter = preload("res://adapter/xace_adapter.gd")
const Transport = preload("res://adapter/xace_transport.gd")
const Entities = preload("res://canonical_entities.gd")
const Presentation = preload("res://presentation.gd")
const Protocol = preload("res://adapter/xace_protocol.gd")
var launch_ready_reported := false
var session_text: Label
var invite_input: LineEdit
var invite_button: Button
var leave_button: Button
var last_session_ui_ms := 0
var displayed_invite_code := ""
var presentation: Node
var adapter: Node
var transport: Node
var entities: Node3D
var camera: Camera3D
var status: Label
var runtime_pid := -1
var package_root := ""
var bindings: Array = []
var controller := 1
var controlled := 0
var previous_input: Dictionary = {}
var instructions := ""
var active := false
var failed := false
var focused := true
var last_snapshot_ms := 0
var started_ms := 0
var connected_once := false
var receipt: Dictionary
var manifest: Dictionary
var session_ticket: Dictionary = {}
var session_ticket_path := ""
var options: Dictionary = {}
var report: Dictionary = {"schema":"xace.player.proof.v1","ticks":[],"inputs":[],"errors":[]}

func _ready() -> void:
	get_tree().auto_accept_quit = false
	for arg in OS.get_cmdline_user_args():
		var parts: PackedStringArray = arg.split("=",true,1)
		if parts.size() == 2:
			options[parts[0]] = parts[1]
	if options.has("--launch-gate"):
		var deadline := Time.get_ticks_msec()+5000
		while Time.get_ticks_msec()<deadline and not FileAccess.file_exists(str(options["--launch-gate"])):
			await get_tree().create_timer(0.025).timeout
		if FileAccess.get_file_as_string(str(options["--launch-gate"])) != str(options.get("--launch-token","")):
			get_tree().quit(1)
			return
	Engine.max_fps = int(options.get("--fps",60))
	var layer := CanvasLayer.new()
	add_child(layer)
	status = Label.new()
	status.position = Vector2(20,18)
	status.add_theme_font_size_override("font_size",20)
	layer.add_child(status)
	status.text = "Verifying game package..."
	receipt = _read_json(str(options.get("--admission", "res://admission.json")))
	var default_package := ProjectSettings.globalize_path("res://package") if OS.has_feature("editor") else OS.get_executable_path().get_base_dir().path_join("package")
	package_root = str(options.get("--package", default_package))
	if not _verify_package():
		_fail("Package verification failed. Reinstall this game package.")
		return
	var settings := _read_json(package_root.path_join("presentation/player/settings.json"))
	bindings = settings.get("bindings",[])
	instructions = str(settings.get("instructions",""))
	controller = int(settings.get("controller_id",1))
	if options.has("--session-ticket"):
		session_ticket = _read_json(str(options["--session-ticket"]))
		controller = int(session_ticket.get("controller_id",0))
	if bindings.is_empty():
		_fail("This package has no supported input bindings.")
		return
	presentation = Presentation.new()
	add_child(presentation)
	var presentation_error: String = presentation.prepare(package_root,manifest,receipt.get("presentation",{}))
	if not presentation_error.is_empty():
		_fail(presentation_error)
		return
	_build_scene()
	var port := int(options.get("--port",17777))
	if options.has("--session-ticket"):
		session_ticket_path = str(options["--session-ticket"])
		if session_ticket.get("schema", "") != "xace.session_ticket.v1" or controller <= 0:
			_fail("This session ticket is invalid. Ask for a new invite.")
			return
		DirAccess.remove_absolute(session_ticket_path)
	else:
		var session_base := ProjectSettings.globalize_path("user://xace-live-"+str(OS.get_process_id())+"-"+str(Time.get_ticks_usec()))
		var ticket_path := session_base+".ticket.json"
		session_ticket_path = ticket_path
		var log_path := session_base+".jsonl"
		var args := PackedStringArray(["--cgs",package_root.path_join("game.cgs.json"),"--sgc-plan",package_root.path_join("execution_plan.json"),"--world",package_root.path_join("world.json"),"--world-manifest",package_root.path_join("world.manifest.json"),"--package-manifest",package_root.path_join("playable.manifest.json"),"--session-ticket-out",ticket_path,"--session-log",log_path,"--session-controller-id",str(controller),"--port",str(port),"--no-control","--input-lockstep-peer","1","--live-session","--no-wait","--live-engine-accept","--quiet"])
		if options.has("--schedule"):
			args.append_array(["--schedule-snapshot-out",str(options["--schedule"])])
		runtime_pid = OS.create_process(package_root.path_join("runtime/xace_runtime.exe"), args, false)
		if runtime_pid <= 0:
			_fail("Could not start the game runtime.")
			return
		if options.has("--report"):
			report["owned_runtime_pid"] = runtime_pid
		var ticket_deadline := Time.get_ticks_msec()+5000
		while Time.get_ticks_msec()<ticket_deadline and not FileAccess.file_exists(ticket_path) and OS.is_process_running(runtime_pid):
			await get_tree().create_timer(0.025).timeout
		session_ticket = _read_json(ticket_path)
		if session_ticket.get("schema","") != "xace.session_ticket.v1" or int(session_ticket.get("controller_id",0)) != controller:
			_fail("Game session identity could not be established.")
			return
		DirAccess.remove_absolute(ticket_path)
	started_ms = Time.get_ticks_msec()
	transport = Transport.new()
	transport.name = "Transport"
	transport.port = port
	transport.host = str(options.get("--session-host","127.0.0.1"))
	transport.cgs_hash = str(manifest.gameplay.cgs_hash)
	if not transport.configure_live_session(session_ticket, FileAccess.get_file_as_string(package_root.path_join("world.json"))):
		_fail("Game world/session contract is unsupported or differs from the admitted package.")
		return
	transport.reconnect_enabled = true
	transport.reconnect_delay_sec = 0.15
	add_child(transport)
	adapter = Adapter.new()
	adapter.name = "Adapter"
	adapter.transport_path = NodePath("../Transport")
	adapter.entity_manager_path = NodePath("../Entities")
	adapter.auto_connect = false
	add_child(adapter)
	adapter.set_process(false)
	adapter.tick_applied.connect(_on_tick)
	adapter.disconnected.connect(_on_disconnect)
	transport.handshake_accepted.connect(_on_handshake)
	transport.message_received.connect(_on_runtime_message)
	transport.handshake_rejected.connect(_fail)
	transport.connect_to_runtime()
	status.text = "Joining game..." if options.has("--session-ticket") else "Starting game..."
	_build_session_controls(layer)

func _build_session_controls(layer: CanvasLayer) -> void:
	if not options.has("--session-control"):
		return
	var panel := VBoxContainer.new()
	panel.position = Vector2(20,150)
	panel.custom_minimum_size = Vector2(650,0)
	layer.add_child(panel)
	var buttons := HBoxContainer.new()
	panel.add_child(buttons)
	invite_button = Button.new()
	invite_button.text = "Invite friend"
	invite_button.pressed.connect(func(): _session_command("invite"))
	buttons.add_child(invite_button)
	var join_button := Button.new()
	join_button.text = "Join game"
	join_button.pressed.connect(func(): _session_command("join"))
	buttons.add_child(join_button)
	leave_button = Button.new()
	leave_button.text = "Leave session"
	leave_button.pressed.connect(func(): _session_command("leave"))
	buttons.add_child(leave_button)
	invite_input = LineEdit.new()
	invite_input.placeholder_text = "Paste an invite code, then select Join game"
	invite_input.max_length = 4096
	panel.add_child(invite_input)
	var copy := Button.new()
	copy.text = "Copy invite code"
	copy.pressed.connect(func(): DisplayServer.clipboard_set(invite_input.text))
	panel.add_child(copy)
	session_text = Label.new()
	session_text.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	panel.add_child(session_text)

func _session_command(action: String) -> void:
	if action == "join" and not invite_input.text.strip_edges().begins_with("XACE1-"):
		session_text.text = "Paste a complete invite code first."
		return
	var path := str(options.get("--session-control",""))
	var temp := path + ".tmp"
	var file := FileAccess.open(temp,FileAccess.WRITE)
	if file == null:
		session_text.text = "Could not send this request. Restart Player and retry."
		return
	file.store_string(JSON.stringify({"token":str(options.get("--launch-token","")),"action":action,"code":invite_input.text.strip_edges()}))
	file.close()
	if FileAccess.file_exists(path):
		DirAccess.remove_absolute(path)
	DirAccess.rename_absolute(temp,path)
	session_text.text = "Preparing invite..." if action == "invite" else "Working..."

func _update_session_controls() -> void:
	if session_text == null or Time.get_ticks_msec()-last_session_ui_ms < 250:
		return
	last_session_ui_ms = Time.get_ticks_msec()
	var view := _read_json(str(options.get("--session-view","")))
	if view.is_empty():
		return
	if view.has("message"):
		session_text.text = str(view.message)
		return
	invite_button.visible = bool(view.get("hosting",false))
	leave_button.text = "End session" if bool(view.get("hosting",false)) else "Leave session"
	var invite: Dictionary = view.get("invite",{})
	var code := str(invite.get("code",""))
	if not code.is_empty() and code != displayed_invite_code:
		displayed_invite_code = code
		invite_input.text = code
	var message := str(invite.get("message",""))
	var health = view.get("readiness",{}).get("transport_health",null)
	if health != null and str(health) != "connected":
		message += "\n" + str(health)
	for member in view.get("readiness",{}).get("members",[]):
		message += "\nPlayer " + str(int(member.player)) + ": " + str(member.state)
	if not message.is_empty():
		session_text.text = message

func _read_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var value: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return value if value is Dictionary else {}

func _verify_package() -> bool:
	# Receipt is trusted Player distribution data produced by XP-007 verification.
	# Package content never supplies its own admission receipt or executable trust.
	if receipt.get("schema","") != "xace.player.admission.v1":
		return false
	if FileAccess.get_sha256(package_root.path_join("playable.manifest.json")) != receipt.get("manifest_sha256",""):
		return false
	manifest = _read_json(package_root.path_join("playable.manifest.json"))
	for record in manifest.get("files",[]):
		var path: String = str(record.get("path",""))
		if path.is_empty() or path.is_absolute_path() or path.contains("..") or path.contains(":") or path.contains("\\"):
			return false
		var full := package_root.path_join(path)
		if not FileAccess.file_exists(full) and receipt.get("presentation",{}).get("optional_paths",[]).has(path):
			continue
		if FileAccess.get_sha256(full) != str(record.get("sha256","")):
			return false
	return not manifest.is_empty() and FileAccess.get_sha256(package_root.path_join("runtime/xace_runtime.exe")) == receipt.get("runtime_sha256","")

func _build_scene() -> void:
	entities = Entities.new()
	entities.name = "Entities"
	entities.presentation = presentation
	entities.create_visual_nodes = false
	entities.interpolate_transforms = false
	add_child(entities)
	camera = Camera3D.new()
	camera.position = Vector3(12,10,14)
	camera.current = true
	add_child(camera)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.environment.ambient_light_color = Color(0.65,0.7,0.85)
	environment.environment.ambient_light_energy = 0.5
	add_child(environment)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-55,-35,0)
	add_child(light)

func _on_handshake(_ack: Dictionary) -> void:
	if failed:
		return
	if options.has("--report"):
		report["initial_entities"] = _ack.get("initial_entities",[])
	var hierarchy_error: String = entities.sync_hierarchy()
	if not hierarchy_error.is_empty():
		_fail(hierarchy_error)
		return
	var binding_error: String = presentation.bind_world(_ack,entities)
	if not binding_error.is_empty():
		_fail(binding_error)
		return
	connected_once = true
	transport.reconnect_enabled = true
	var owned: Array = entities.controlled_entities(controller)
	if owned.is_empty():
		_fail("No local controllable entity is bound to this controller.")
		return
	controlled = int(owned[0])
	if int(_ack.get("assigned_player_id",0)) != controlled or int(_ack.get("assigned_peer_id",0)) != int(session_ticket.get("peer_id",0)):
		_fail("Game session assigned a different player.")
		return
	# The validated transport contract advances at committed ruleset boundaries.
	# The one-use admission ticket still describes the original epoch.
	var expected_epoch: Dictionary = transport.native_contract.offer.get("contract",{}).get("epoch",{})
	if str(_ack.get("session_id","")) != str(expected_epoch.get("session_id","")) or str(_ack.get("authority_incarnation","")) != str(expected_epoch.get("authority_incarnation","")) or int(_ack.get("ruleset_epoch",-1)) != int(expected_epoch.get("ruleset_epoch",-2)):
		_fail("Game session identity changed during connection.")
		return
	adapter.peer_id = int(_ack.get("assigned_peer_id",0))
	adapter.player_id = controlled
	var visual: MeshInstance3D = entities.get_entity_node(controlled).get_node_or_null("CanonicalVisual")
	if visual != null:
		(visual.material_override as StandardMaterial3D).albedo_color = Color(0.95,0.7,0.22)
	active = true
	last_snapshot_ms = Time.get_ticks_msec()
	# The authority explicitly requests each input tick, including idle ticks.

func _on_runtime_message(message: Dictionary) -> void:
	if not active or str(message.get("msg_type", "")) != "input_tick_request":
		return
	_send_input(int(message.get("tick", -1)))

func _on_tick(tick: int) -> void:
	if not active:
		return
	last_snapshot_ms = Time.get_ticks_msec()
	if not launch_ready_reported:
		_launch_status("playing", "")
		launch_ready_reported = true
	var hierarchy_error: String = entities.sync_hierarchy()
	if not hierarchy_error.is_empty():
		_fail(hierarchy_error)
		return
	if options.has("--report") and report.ticks.size() < 8192:
		report.ticks.append({"tick":tick,"components":entities.component_snapshot(controlled)})
	status.text = "XACE Player\n" + ("Playing" if focused else "Window unfocused - input released") + "\n" + instructions + ("\nSome visuals are using placeholders." if presentation.fallback_count() > 0 else "")
	if int(options.get("--proof-ticks",0)) > 0 and tick >= int(options["--proof-ticks"])-1:
		_finish_proof()
		return
	# Input is sent only for an authority request.

func _send_input(tick: int) -> void:
	if tick < 0:
		return
	var actions: Array = []
	for binding in bindings:
		var value := 0.0
		if focused:
			value = float(Input.is_physical_key_pressed(int(binding.get("positive",0)))) - float(Input.is_physical_key_pressed(int(binding.get("negative",0))))
		var action: String = str(binding.action)
		var kind: String = str(binding.get("kind","axis_1d"))
		var phase := "cancelled" if value == 0 else "changed"
		if kind == "button" and value != 0:
			phase = "started" if float(previous_input.get(action,0.0)) == 0 else "performed"
		actions.append(Protocol.build_input_action(action,value,0.0,kind,phase))
		previous_input[action] = value
	if adapter.send_input_actions(actions,tick,false) and options.has("--report") and report.inputs.size() < 8192:
		report.inputs.append({"tick":tick,"actions":actions})

func _process(_delta: float) -> void:
	_update_session_controls()
	if runtime_pid > 0 and not OS.is_process_running(runtime_pid) and active:
		_fail("Game runtime stopped. Gameplay is frozen.")
	if active and Time.get_ticks_msec()-last_snapshot_ms > 5000:
		_fail("Game runtime stopped responding. Gameplay is frozen.")
	if connected_once and not active and not failed and Time.get_ticks_msec()-last_snapshot_ms > 10000:
		_fail("Could not reconnect to the game runtime.")
	if not connected_once and started_ms > 0 and Time.get_ticks_msec()-started_ms > 10000:
		_fail("Could not connect to the game runtime.")
	if active and controlled > 0:
		var target: Node3D = entities.get_entity_node(controlled)
		if target != null:
			camera.position = target.global_position + presentation.camera_offset()
			camera.look_at(target.global_position,Vector3.UP)

func _on_disconnect(reason: String) -> void:
	if connected_once and active:
		active = false
		status.text = "Reconnecting to game..."
		last_snapshot_ms = Time.get_ticks_msec()

func _fail(message: String) -> void:
	if failed:
		return
	failed = true
	active = false
	started_ms = 0
	status.text = message
	_launch_status("failed",message)
	report.errors.append(message)
	if transport != null:
		transport.reconnect_enabled = false
	if options.has("--report"):
		_write_report()
	_shutdown()
	if options.has("--report"):
		get_tree().quit()

func _notification(what: int) -> void:
	if what == NOTIFICATION_APPLICATION_FOCUS_OUT:
		focused = false
	elif what == NOTIFICATION_APPLICATION_FOCUS_IN:
		focused = true
	elif what == NOTIFICATION_WM_CLOSE_REQUEST:
		_shutdown()
		get_tree().quit()

func _finish_proof() -> void:
	active = false
	transport.reconnect_enabled = false
	if options.has("--screenshot"):
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(str(options["--screenshot"]))
	_write_report()
	adapter.disconnect_from_runtime("Proof complete")
	await get_tree().create_timer(0.5).timeout
	_shutdown()
	get_tree().quit()

func _write_report() -> void:
	if options.has("--report"):
		if presentation != null:
			report["presentation"] = presentation.readiness_report()
		var file := FileAccess.open(str(options["--report"]),FileAccess.WRITE)
		if file != null:
			file.store_string(JSON.stringify(report))

func _shutdown() -> void:
	active = false
	if not session_ticket_path.is_empty() and FileAccess.file_exists(session_ticket_path):
		DirAccess.remove_absolute(session_ticket_path)
	if adapter != null:
		adapter.disconnect_from_runtime("Player closing")
	# Only the process created by this Player instance is owned here.
	if runtime_pid > 0 and OS.is_process_running(runtime_pid):
		OS.kill(runtime_pid)
	runtime_pid = -1

func _exit_tree() -> void:
	_shutdown()

func _unhandled_key_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_F3 and presentation != null:
		presentation.overlay_enabled = not presentation.overlay_enabled
		presentation.refresh_overlays()

func _launch_status(state: String, message: String) -> void:
	if not options.has("--launch-status"):
		return
	var file := FileAccess.open(str(options["--launch-status"]),FileAccess.WRITE)
	if file != null:
		file.store_string(JSON.stringify({"schema":"xace.player.launch_status.v1","token":str(options.get("--launch-token","")),"state":state,"message":message,"runtime_pid":runtime_pid}))
