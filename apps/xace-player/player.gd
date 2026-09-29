extends Node3D

const Adapter = preload("res://adapter/xace_adapter.gd")
const Transport = preload("res://adapter/xace_transport.gd")
const Entities = preload("res://canonical_entities.gd")
const Presentation = preload("res://presentation.gd")
const Protocol = preload("res://adapter/xace_protocol.gd")
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
var focused := true
var last_snapshot_ms := 0
var started_ms := 0
var connected_once := false
var receipt: Dictionary
var manifest: Dictionary
var options: Dictionary = {}
var report: Dictionary = {"schema":"xace.player.proof.v1","ticks":[],"inputs":[],"errors":[]}

func _ready() -> void:
	get_tree().auto_accept_quit = false
	for arg in OS.get_cmdline_user_args():
		var parts: PackedStringArray = arg.split("=",true,1)
		if parts.size() == 2:
			options[parts[0]] = parts[1]
	Engine.max_fps = int(options.get("--fps",60))
	var layer := CanvasLayer.new()
	add_child(layer)
	status = Label.new()
	status.position = Vector2(20,18)
	status.add_theme_font_size_override("font_size",20)
	layer.add_child(status)
	status.text = "Verifying game package..."
	receipt = _read_json("res://admission.json")
	var default_package := ProjectSettings.globalize_path("res://package") if OS.has_feature("editor") else OS.get_executable_path().get_base_dir().path_join("package")
	package_root = str(options.get("--package", default_package))
	if not _verify_package():
		_fail("Package verification failed. Reinstall this game package.")
		return
	var settings := _read_json(package_root.path_join("presentation/player/settings.json"))
	bindings = settings.get("bindings",[])
	instructions = str(settings.get("instructions",""))
	controller = int(settings.get("controller_id",1))
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
	var args := PackedStringArray(["--cgs",package_root.path_join("game.cgs.json"),"--sgc-plan",package_root.path_join("execution_plan.json"),"--world",package_root.path_join("world.json"),"--world-manifest",package_root.path_join("world.manifest.json"),"--port",str(port),"--no-control","--input-lockstep-peer","1","--live-session","--quiet"])
	if options.has("--schedule"):
		args.append_array(["--schedule-snapshot-out",str(options["--schedule"])])
	runtime_pid = OS.create_process(package_root.path_join("runtime/xace_runtime.exe"), args, false)
	if runtime_pid <= 0:
		_fail("Could not start the game runtime.")
		return
	if options.has("--report"):
		report["owned_runtime_pid"] = runtime_pid
	started_ms = Time.get_ticks_msec()
	transport = Transport.new()
	transport.name = "Transport"
	transport.port = port
	transport.cgs_hash = str(manifest.gameplay.cgs_hash)
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
	transport.handshake_rejected.connect(_fail)
	transport.connect_to_runtime()
	status.text = "Starting game..."

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
	transport.reconnect_enabled = false
	var owned: Array = entities.controlled_entities(controller)
	if owned.is_empty():
		_fail("No local controllable entity is bound to this controller.")
		return
	controlled = int(owned[0])
	adapter.player_id = controlled
	var visual: MeshInstance3D = entities.get_entity_node(controlled).get_node_or_null("CanonicalVisual")
	if visual != null:
		(visual.material_override as StandardMaterial3D).albedo_color = Color(0.95,0.7,0.22)
	active = true
	last_snapshot_ms = Time.get_ticks_msec()
	_send_input(0)

func _on_tick(tick: int) -> void:
	if not active:
		return
	last_snapshot_ms = Time.get_ticks_msec()
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
	_send_input(tick+1)

func _send_input(tick: int) -> void:
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
	if runtime_pid > 0 and not OS.is_process_running(runtime_pid) and active:
		_fail("Game runtime stopped. Gameplay is frozen.")
	if active and Time.get_ticks_msec()-last_snapshot_ms > 5000:
		_fail("Game runtime stopped responding. Gameplay is frozen.")
	if not connected_once and started_ms > 0 and Time.get_ticks_msec()-started_ms > 10000:
		_fail("Could not connect to the game runtime.")
	if active and controlled > 0:
		var target: Node3D = entities.get_entity_node(controlled)
		if target != null:
			camera.position = target.global_position + presentation.camera_offset()
			camera.look_at(target.global_position,Vector3.UP)

func _on_disconnect(reason: String) -> void:
	if connected_once and active:
		_fail("Disconnected from game runtime: "+reason)

func _fail(message: String) -> void:
	active = false
	status.text = message
	report.errors.append(message)
	if transport != null:
		transport.reconnect_enabled = false
	if options.has("--report"):
		_write_report()
	_shutdown()

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
