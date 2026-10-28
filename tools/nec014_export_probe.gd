extends Node3D
var deadline := 0
var done := false
var subscribed := false
var fault_tick := -1
var fault_frames := 0
var audio_started := false
var animation_started := false
var save_stage := 0
var bad_path := ""
var bad_hash := ""
var compatible := false
var incompatible := false
func _ready() -> void: deadline=Time.get_ticks_msec()+30000
func _process(_delta: float) -> void:
	if done: return
	var host := $NativeHost
	if host.state == "failed":
		if "--fault" in OS.get_cmdline_user_args():
			if fault_tick<0: fault_tick=host.adapter._last_runtime_tick
			if fault_tick!=host.adapter._last_runtime_tick: finish(false,"Projection advanced after authority loss");return
			fault_frames+=1
			if fault_frames>=20: finish(true,host.error)
			return
		finish("--expect-refusal" in OS.get_cmdline_user_args(),host.error);return
	if Time.get_ticks_msec()>deadline: finish(false,"Export Play timeout");return
	if host.manager != null and not subscribed:
		subscribed=true
		host.manager.playback_command_applied.connect(func(command,applied):
			var node: Node = host.manager.get_entity_node(int(command.entity_id))
			if node == null: return
			if command.binding_id=="nec014.audio": audio_started = audio_started or (applied and node.get_node("XaceAudio").playing)
			if command.binding_id=="nec014.animation": animation_started = animation_started or (applied and node.get_node("AnimationPlayer").is_playing()))
	if host.state != "playing": return
	host.collector.submit_native_action("proof.move",1.0)
	host.collector.submit_native_action("proof.jump",1.0 if host.adapter._last_runtime_tick%20>=10 else 0.0)
	if host.adapter._last_runtime_tick < 12 or (ResourceLoader.exists("res://tone.tres") and not (audio_started and animation_started)): return
	if "--fault" in OS.get_cmdline_user_args() or "--hold" in OS.get_cmdline_user_args():
		var ready := OS.get_cmdline_user_args()[0]+".ready.json"
		if not FileAccess.file_exists(ready): FileAccess.open(ready,FileAccess.WRITE).store_string(JSON.stringify({"runtime_pid":host.runtime_pid,"owner_pid":host.host_client.pid,"godot_pid":OS.get_process_id(),"tick":host.adapter._last_runtime_tick}))
		return
	if "--smoke" in OS.get_cmdline_user_args(): finish(true,"");return
	if save_stage==0:
		DirAccess.make_dir_recursive_absolute(host.save_root)
		var identity: Dictionary = load("res://xace_native_contract.gd").protocol_integers(host.save_identity)
		var envelope := {"schema":"xace.native_save.v1","identity":identity,"snapshot":{"tick":12},"payload_sha256":'{"tick":12}'.sha256_text()}
		var good_path: String = host.save_root.path_join("slot-nec014-compatible.json")
		bad_path=host.save_root.path_join("slot-nec014-incompatible.json")
		if FileAccess.file_exists(good_path) or FileAccess.file_exists(bad_path): finish(false,"Proof refuses existing saves");return
		var good_file := FileAccess.open(good_path,FileAccess.WRITE)
		good_file.store_string(JSON.stringify(envelope))
		good_file.flush()
		good_file.close()
		identity.game_id="wrong-game"
		var bad_file := FileAccess.open(bad_path,FileAccess.WRITE)
		bad_file.store_string(JSON.stringify(envelope))
		bad_file.flush()
		bad_file.close()
		bad_hash=FileAccess.get_sha256(bad_path)
		host.check_save("nec014-compatible")
		save_stage=1
		return
	if save_stage==1:
		if host.save_status=="checking": return
		compatible=host.save_status=="compatible-not-restored"
		if not compatible: finish(false,"Compatible save refused: "+host.save_error);return
		host.check_save("nec014-incompatible")
		save_stage=2
		return
	if save_stage==2:
		if host.save_status=="checking": return
		incompatible=host.save_status=="refused" and FileAccess.get_sha256(bad_path)==bad_hash
		save_stage=3
	var ok: bool = compatible and incompatible and host.manager.entity_count()==2 and $Existing0/Existing1.global_position.x>7.1
	for node in host.manager._nodes.values(): ok = ok and node in [$Existing0,$Existing0/Existing1] and node.get_node_or_null("CanonicalVisual")==null
	finish(ok,"" if ok else "Export identity/input mismatch")
func finish(ok: bool,why: String) -> void:
	done=true
	var host := $NativeHost
	var report := {"ok":ok,"error":why,"fault_frozen_frames":fault_frames,"native_scene":scene_file_path,"runtime_pid":host.runtime_pid,"owner_pid":host.host_client.pid if host.host_client!=null else 0,"tick":host.adapter._last_runtime_tick if host.adapter!=null else 0,"exported":not OS.has_feature("editor"),"audio_started":audio_started,"animation_started":animation_started,"save_compatible_not_restored":compatible,"incompatible_save_retained":incompatible,"save_root":host.save_root,"save_status":host.save_status,"save_error":host.save_error,"expected_incompatible_hash":bad_hash,"observed_incompatible_hash":FileAccess.get_sha256(bad_path) if not bad_path.is_empty() else ""}
	host.stop()
	FileAccess.open(OS.get_cmdline_user_args()[0],FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
	get_tree().quit(0 if ok else 1)
