extends Node
# Opt-in node in the developer's own scene; no replacement Player UI.
@export var profile_path := "res://xace-native-profile.json"
var state := "stopped"
var error := ""
var save_root := ""
var save_identity: Dictionary = {}
var runtime_pid := 0
var save_status := "unchecked"
var save_error := ""
var _save_pending := false
var _save_deadline := 0
var host_client: RefCounted
var transport: Node
var manager: Node3D
var collector: Node
var adapter: Node
var profile: Dictionary
var release := ""
var _deadline := 0
var _closing := false

func _ready() -> void:
	if OS.has_feature("editor"):
		var approval_issue: String = load(_base().path_join("xace_native_approval.gd")).validate()
		if not approval_issue.is_empty(): fail(approval_issue);return
	else:
		var stamp: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://xace-export-preflight.json"))
		if not stamp is Dictionary or stamp.get("schema")!="xace.godot.export_preflight.v1" or stamp.get("approved")!=true or stamp.get("profile_sha256")!=FileAccess.get_sha256(profile_path): fail("Native export preflight missing/stale/refused");return
	var decoded: Variant = JSON.parse_string(FileAccess.get_file_as_string(profile_path))
	if not decoded is Dictionary: fail("Native profile missing");return
	profile = decoded
	if profile.get("schema") != "xace.godot.native_profile.v1": fail("Native profile schema mismatch");return
	var relative := str(profile.get("release_directory",""))
	if relative.is_empty() or relative.is_absolute_path() or ".." in relative or "\\" in relative: fail("Relative native release directory required");return
	var base := ProjectSettings.globalize_path("res://") if OS.has_feature("editor") else OS.get_executable_path().get_base_dir()
	release = base.path_join(relative)
	if FileAccess.get_sha256(release.path_join("native-release.json")) != str(profile.get("release_sha256","")): fail("Native release identity mismatch");return
	var world: Variant = JSON.parse_string(FileAccess.get_file_as_string(release.path_join("package/world.json")))
	if not world is Dictionary: fail("Native World missing");return
	manager = load(_base().path_join("xace_native_scene_entities.gd")).new()
	manager.name = "NativeProjection"
	manager.create_visual_nodes = false
	manager.interpolate_transforms = false
	for id in profile.get("objects",{}):
		var node := get_node_or_null(NodePath(str(profile.objects[id])))
		if not node is Node3D or manager.native_objects.values().has(node): fail("Invalid/duplicate native object binding");return
		manager.native_objects[str(id)] = node
	var issue: String = manager.validate(world)
	if not issue.is_empty(): fail(issue);return
	var resources_issue := validate_resources()
	if not resources_issue.is_empty(): fail(resources_issue);return
	add_child(manager)
	host_client = load(_base().path_join("xace_native_host_client.gd")).new()
	var local := OS.get_environment("LOCALAPPDATA")
	if not local.is_absolute_path(): fail("Absolute per-user data directory required");return
	if not host_client.start(release.path_join("xace-player-launcher.exe"),str(profile.get("launcher_sha256","")),release,str(profile.get("release_sha256","")),local.path_join("XACE/NativeHistory"),int(profile.get("controller_id",0))): fail(host_client.error);return
	state = "verifying"
	_deadline = Time.get_ticks_msec()+20000

func _process(_delta: float) -> void:
	if host_client == null or _closing or state == "failed": return
	for message in host_client.poll():
		if message.get("ok") == false:
			if _save_pending and message.get("state")=="refused":
				_save_pending=false
				save_status="refused"
				save_error=str(message.get("message","Save refused"))
				continue
			fail(str(message.get("message","Authority lost")))
			return
		if message.get("result",{}).get("state")=="save_compatible":
			if not _save_pending or message.result.get("restored") != false: fail("Unexpected save response");return
			_save_pending=false
			save_status="compatible-not-restored"
			continue
		if message.get("schema") == "xace.native_host.ready.v1":
			save_root = str(message.save_root)
			save_identity = message.save_identity
			if save_identity.get("game_id") != profile.get("game_id"): fail("Game/save identity mismatch");return
			host_client.send("play")
			state = "starting"
		elif message.get("result",{}).get("state") == "ready":
			connect_session(message.result)
	if not host_client.error.is_empty(): fail(host_client.error);return
	if _save_pending and Time.get_ticks_msec()>_save_deadline: fail("Save check timed out");return
	if state in ["verifying","starting","connecting"] and Time.get_ticks_msec()>_deadline: fail("Native host readiness timed out")

func connect_session(result: Dictionary) -> void:
	if state != "starting" or result.get("release") != profile.release_sha256: fail("Unexpected native readiness");return
	var endpoint := str(result.endpoint).split(":")
	if endpoint.size()!=2 or endpoint[0]!="127.0.0.1" or not endpoint[1].is_valid_int(): fail("Invalid local native endpoint");return
	runtime_pid = int(result.runtime_pid)
	var ticket: Variant = JSON.parse_string(FileAccess.get_file_as_string(str(result.ticket)))
	if not ticket is Dictionary: fail("Native ticket missing");return
	transport = load(_base().path_join("xace_transport.gd")).new()
	transport.name = "Transport"
	transport.auto_connect = false
	transport.reconnect_enabled = false
	transport.port = int(endpoint[1])
	if not transport.configure_live_session(ticket,FileAccess.get_file_as_string(release.path_join("package/world.json"))): fail("Native ticket refused");return
	manager.contract = transport.native_contract
	add_child(transport)
	collector = load(_base().path_join("xace_input_collector.gd")).new()
	collector.name = "Input"
	for binding in profile.get("input_bindings",[]): collector.live_bindings.append(binding)
	add_child(collector)
	adapter = load(_base().path_join("xace_adapter.gd")).new()
	adapter.name = "Adapter"
	adapter.auto_connect = false
	adapter.transport_path = NodePath("../Transport")
	adapter.entity_manager_path = NodePath("../NativeProjection")
	adapter.input_collector_path = NodePath("../Input")
	add_child(adapter)
	transport.protocol_error.connect(fail)
	transport.handshake_rejected.connect(fail)
	transport.disconnected.connect(func(why):
		if state == "playing" and not _closing: fail(why))
	transport.handshake_accepted.connect(func(_ack): state="playing")
	manager.playback_command_applied.connect(func(_command,applied):
		if not applied: fail("Native playback failed"))
	state = "connecting"
	transport.connect_to_runtime()

func fail(why: String) -> void:
	error = why
	state = "failed"
	push_error("[XACE] "+why)
	stop()
func stop() -> void:
	if _closing: return
	_closing = true
	if transport != null: transport.disconnect_from_runtime("native host_client stopped")
	if host_client != null: host_client.close()
func _exit_tree() -> void: stop()
func _base() -> String: return get_script().resource_path.get_base_dir()

func validate_resources() -> String:
	var manifest: Variant = JSON.parse_string(FileAccess.get_file_as_string(release.path_join("package/playable.manifest.json")))
	if not manifest is Dictionary or str(manifest.get("presentation_variants",{}).get("player",{}).get("content_hash","")).length()!=64: return "Native player presentation identity missing"
	var game: Variant = JSON.parse_string(FileAccess.get_file_as_string(release.path_join("package/game.cgs.json")))
	if not game is Dictionary: return "Native game definition missing"
	for binding in game.get("semantic_bindings",{}).get("bindings",[]):
		var parameters: Dictionary = binding.get("parameters",{})
		if str(parameters.get("xace_binding_required","false")) != "true": continue
		match str(binding.get("playback_kind","")):
			"Audio":
				var path := str(parameters.get("resource_path",""))
				if not path.begins_with("res://") or ".." in path: return "Required packed audio path invalid"
				var sound: Resource = load(path) if ResourceLoader.exists(path) else null
				if not sound is AudioStream or sound.get_length() <= 0: return "Required packed audio missing"
			"Animation":
				var animation := str(parameters.get("animation",binding.get("semantic_action","")))
				for node in manager.native_objects.values():
					var player: Node = manager._find_child_of_class(node,"AnimationPlayer")
					if player == null or not player.has_animation(animation): return "Required native animation missing"
			_: return "Required native playback profile unsupported"
	return ""

func check_save(slot: String) -> bool:
	if state != "playing" or _save_pending: return false
	if not host_client.send("check-save",slot): return false
	_save_pending=true
	_save_deadline=Time.get_ticks_msec()+20000
	save_status="checking"
	save_error=""
	return true
