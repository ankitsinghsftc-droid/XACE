extends SceneTree
var config: Dictionary
var client: RefCounted
var checks := 0
func _initialize() -> void:
	config = JSON.parse_string(FileAccess.get_file_as_string(OS.get_cmdline_user_args()[0]))
	call_deferred("run")
func receive() -> Dictionary:
	for i in range(1500):
		var rows: Array = client.poll()
		if not rows.is_empty(): return rows[0]
		if not client.error.is_empty(): return {"error":client.error}
		await process_frame
	return {"error":"Response timeout"}
func run() -> void:
	var script: Script = load("res://xace_native_host_client.gd")
	client = script.new()
	if client.start(config.launcher,"0".repeat(64),config.release,config.release_hash,config.history,1): finish(false,"Wrong launcher hash accepted");return
	checks += 1
	client = script.new()
	if not client.start(config.launcher,config.launcher_hash,config.release,config.release_hash,config.history,1): finish(false,client.error);return
	var ready: Dictionary = await receive()
	if ready.get("state") != "stopped": finish(false,str(ready));return
	checks += 1
	for cycle in range(3):
		client.send("play")
		var play: Dictionary = await receive()
		if not play.get("ok",false): finish(false,str(play));return
		var runtime := int(play.result.runtime_pid)
		client.send("play")
		var repeated: Dictionary = await receive()
		if int(repeated.get("result",{}).get("runtime_pid",0)) != runtime: finish(false,"Repeated Play changed runtime");return
		client.send("stop")
		var stopped: Dictionary = await receive()
		if not stopped.get("ok",false): finish(false,str(stopped));return
		checks += 2
	client.send("play")
	var last: Dictionary = await receive()
	if not last.get("ok",false): finish(false,str(last));return
	var owner := int(client.pid)
	var runtime := int(last.result.runtime_pid)
	client.close()
	for i in range(600):
		if not OS.is_process_running(owner) and not OS.is_process_running(runtime):
			checks += 1
			finish(true,"")
			return
		await process_frame
	finish(false,"Owned process survived EOF")
func finish(ok: bool, why: String) -> void:
	if client != null: client.close()
	FileAccess.open(config.report,FileAccess.WRITE).store_string(JSON.stringify({"ok":ok,"checks":checks,"error":why,"godot":Engine.get_version_info().string,"native_scene_play":false,"export_verified":false},"\t"))
	quit(0 if ok else 1)
