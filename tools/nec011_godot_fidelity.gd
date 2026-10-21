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
    var replacement := AudioStreamWAV.new()
    replacement.format = sound.format
    replacement.mix_rate = sound.mix_rate
    replacement.data = samples
    checks["replacement_saved"] = ResourceSaver.save(replacement,"res://replacement.tres") == OK
    audio.parameters.resource_path = "res://replacement.tres"
    manager.apply_playback_commands([audio])
    checks["replacement_played"] = node.get_node("XaceAudio").stream.resource_path == "res://replacement.tres" and results[-1].applied
    manager._clear_playback_side_effects()
    checks["reset_stops_animation"] = not player.is_playing()
    var ok := true
    for value in checks.values(): ok = ok and bool(value)
    var report := {"ok":ok,"checks":checks,"engine":"godot","version":Engine.get_version_info().string,"actual_native_playback":true,"audible_output_certified":false,"runtime_input_certified":false}
    var output := OS.get_cmdline_user_args()[0]
    FileAccess.open(output,FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
    print(JSON.stringify(report))
    quit(0 if ok else 1)
