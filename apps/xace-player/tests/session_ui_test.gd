extends SceneTree

func _initialize() -> void:
	var folder := OS.get_cmdline_user_args()[0]
	DirAccess.make_dir_recursive_absolute(folder)
	var player = load("res://player.gd").new()
	var command := folder.path_join("command.json")
	var view := folder.path_join("view.json")
	player.options = {"--session-control":command,"--session-view":view,"--launch-token":"test-owner"}
	var layer := CanvasLayer.new()
	root.add_child(layer)
	player._build_session_controls(layer)
	player.invite_input.text = "XACE1-friend"
	player._session_command("join")
	var request: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(command))
	assert(request.action == "join" and request.code == "XACE1-friend" and request.token == "test-owner")
	var file := FileAccess.open(view,FileAccess.WRITE)
	file.store_string(JSON.stringify({"hosting":true,"invite":{"code":"XACE1-host","message":"Share this code"},"readiness":{"transport_health":"Relay connection lost. End this session and retry.","members":[{"player":1,"state":"Playing"},{"player":2,"state":"Joining"}]}}))
	file.close()
	player.last_session_ui_ms = -1000
	player._update_session_controls()
	assert(player.invite_input.text == "XACE1-host")
	assert(player.leave_button.text == "End session")
	assert(player.session_text.text.contains("Player 2: Joining"))
	assert(player.session_text.text.contains("Relay connection lost"))
	player.invite_input.text = "XACE1-pasted-new"
	player.last_session_ui_ms = -1000
	player._update_session_controls()
	assert(player.invite_input.text == "XACE1-pasted-new")
	player._session_command("leave")
	request = JSON.parse_string(FileAccess.get_file_as_string(command))
	assert(request.action == "leave")
	player.free()
	layer.free()
	DirAccess.remove_absolute(command)
	DirAccess.remove_absolute(view)
	print("XP-014/015 native Player controls: invite, join, readiness, paste preservation and leave PASS")
	quit(0)
