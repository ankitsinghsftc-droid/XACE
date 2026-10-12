extends "res://player.gd"
# Exported proof build only; arbitrary recorded actions use the production adapter.
var mixed: Dictionary
func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--config="):mixed=JSON.parse_string(FileAccess.get_file_as_string(arg.trim_prefix("--config=")))
	super._ready()
func record(row: Dictionary) -> void:
	var path := str(mixed.transcript)
	var f := FileAccess.open(path,FileAccess.READ_WRITE) if FileAccess.file_exists(path) else FileAccess.open(path,FileAccess.WRITE)
	f.seek_end()
	f.store_line(JSON.stringify(row))
func _on_handshake(ack: Dictionary) -> void:
	super._on_handshake(ack)
	record({"kind":"ready","peer":transport.native_contract.peer_id,"player":transport.native_contract.player_id,"epoch":ack.sync,"version":Engine.get_version_info().string})
func _send_input(tick: int) -> void:
	if not adapter.send_input_actions(mixed.inputs[tick],tick,false):
		_fail("Recorded input could not be sent")
		return
	record({"kind":"input","tick":tick,"actions":mixed.inputs[tick]})
func _on_runtime_message(m: Dictionary) -> void:
	super._on_runtime_message(m)
	if m.msg_type!="tick_snapshot":return
	var applied := true
	for e in m.entities:
		var node: Node3D=entities.get_entity_node(int(e.id))
		applied=applied and node!=null
		for key in e.components:
			applied=applied and entities.component_snapshot(int(e.id)).get(int(key),{}).get("data") == JSON.parse_string(e.components[key])
		if e.components.has("1"):
			applied=applied and node.position.is_equal_approx(entities._fixed_vector(JSON.parse_string(e.components["1"]).position))
	if mixed.has("frames"):
		await RenderingServer.frame_post_draw
		get_viewport().get_texture().get_image().save_png(str(mixed.frames).path_join("%04d.png" % int(m.tick)))
	record({"kind":"tick","tick":int(m.tick),"applied":applied,"projection_json":m.projection_json,"sync":m.sync,"events":m.events})
	if int(m.tick)==int(mixed.stop_tick):
		active=false
		transport.reconnect_enabled=false
		_shutdown()
		record({"kind":"done","ok":true})
		get_tree().quit()
func _fail(message: String) -> void:
	record({"kind":"error","message":message})
	super._fail(message)
	get_tree().quit(1)
