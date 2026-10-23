extends SceneTree
var checks: Dictionary = {}
func _initialize() -> void:
    call_deferred("run")
func run() -> void:
    var manager: Node3D = load("res://xace_canonical_entities.gd").new()
    manager.create_visual_nodes = false
    root.add_child(manager)
    var node: Node3D = manager._ensure_node(42, "echo", [])
    var player := AnimationPlayer.new()
    node.add_child(player)
    var animation := Animation.new()
    animation.length = 1.0
    var library := AnimationLibrary.new()
    library.add_animation("echo", animation)
    player.add_animation_library("", library)
    var sound := AudioStreamWAV.new()
    sound.format = AudioStreamWAV.FORMAT_8_BITS
    sound.mix_rate = 8000
    var samples := PackedByteArray()
    samples.resize(8000)
    samples.fill(128)
    sound.data = samples
    checks["resource_saved"] = ResourceSaver.save(sound,"res://tone.tres") == OK
    var results: Array = []
    manager.playback_command_applied.connect(func(command: Dictionary, applied: bool): results.append({"binding":command.binding_id,"applied":applied}))
    var audio := {"entity_id":42,"binding_id":"audio","playback_kind":"Audio","semantic_action":"echo","asset":{"id":"tone","asset_type":"AudioClip","status":"Linked"},"parameters":{"resource_path":"res://tone.tres"}}
    var anim := {"entity_id":42,"binding_id":"animation","playback_kind":"Animation","semantic_action":"echo","asset":{"id":"echo","asset_type":"AnimationClip","status":"Linked"},"parameters":{"animation":"echo"}}
    manager.apply_playback_commands([audio,anim])
    checks["audio_started"] = node.get_node("XaceAudio").playing
    checks["animation_started"] = player.is_playing() and player.current_animation == "echo"
    checks["both_applied"] = results.size() == 2 and results[0].applied and results[1].applied
    var missing := anim.duplicate(true)
    missing.binding_id = "missing"
    missing.parameters = {"animation":"absent"}
    manager.apply_playback_commands([missing])
    checks["missing_refused"] = not results[-1].applied
    var fallback := missing.duplicate(true)
    fallback.binding_id = "cosmetic"
    fallback.parameters = {"animation":"absent","allow_fallback":true}
    manager.apply_playback_commands([fallback])
    checks["explicit_cosmetic_fallback"] = results[-1].applied
    fallback.parameters.xace_binding_required = "true"
    manager.apply_playback_commands([fallback])
    checks["required_binding_refuses_fallback"] = not results[-1].applied and manager._semantic_binding_status(fallback,false) != "fallback"
    var replacement := AudioStreamWAV.new()
    replacement.format = sound.format
    replacement.mix_rate = sound.mix_rate
    replacement.data = samples
    checks["replacement_saved"] = ResourceSaver.save(replacement,"res://replacement.tres") == OK
    audio.parameters.resource_path = "res://replacement.tres"
    manager.apply_playback_commands([audio])
    checks["replacement_played"] = node.get_node("XaceAudio").stream.resource_path == "res://replacement.tres" and results[-1].applied
    audio.parameters.resource_path = "res://does-not-exist.tres"
    audio.parameters.xace_binding_status = "resolved"
    manager.apply_playback_commands([audio])
    checks["missing_audio_refused"] = not results[-1].applied
    checks["declared_resolved_cannot_hide_failure"] = manager._semantic_binding_status(audio, false) == "missing"
    var absent_entity := audio.duplicate(true)
    absent_entity.entity_id = 999
    absent_entity.parameters.xace_binding_status = "fallback"
    checks["failed_fallback_blocks"] = manager._semantic_binding_status(absent_entity, false) == "missing"
    manager._clear_playback_side_effects()
    checks["reset_stops_animation"] = not player.is_playing()
    var collector: Node = load("res://xace_input_collector.gd").new()
    collector.include_pointer = false
    collector.emit_idle_movement = true
    root.add_child(collector)
    for action in ["move_left","move_right","move_back","move_forward"]:
        InputMap.add_action(action)
    Input.action_press("move_right",1.0)
    var actions: Array = collector.collect_actions(7)
    var mapped := false
    for action in actions:
        if action.action == "move_x": mapped = action.kind == "axis_1d" and action.value == 1.0
    checks["declared_inputmap_axis_sampled"] = mapped
    Input.action_release("move_right")
    checks["same_tick_input_is_stable"] = collector.collect_actions(7) == actions
    var released: Array = collector.collect_actions(8)
    var cancelled := false
    for action in released:
        if action.action == "move_x": cancelled = action.value == 0.0 and action.phase == "cancelled"
    checks["next_tick_observes_release"] = cancelled
    var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://session-fixture.json"))
    var session: RefCounted = load("res://xace_native_contract.gd").new()
    var protocol: Script = load("res://xace_protocol.gd")
    var packet: Dictionary = protocol.build_input_packet(2,7,1,actions,42,"godot",false,0)
    var configured: bool = session.configure(JSON.parse_string(fixture.ticket_json),fixture.world_json)
    checks["mapped_packet_authority_tick"] = configured and session.verify(fixture.baseline) == "accept" and not session.can_send(packet) and session.request(7) and session.can_send(packet)
    packet.tick = 8
    checks["mapped_packet_wrong_tick_refused"] = not session.can_send(packet)
    var ok := true
    for value in checks.values(): ok = ok and bool(value)
    var report := {"ok":ok,"checks":checks,"engine":"godot","version":Engine.get_version_info().string,"actual_native_playback":true,"audible_output_certified":false,"runtime_input_certified":false}
    var output := OS.get_cmdline_user_args()[0]
    FileAccess.open(output,FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
    print(JSON.stringify(report))
    quit(0 if ok else 1)
