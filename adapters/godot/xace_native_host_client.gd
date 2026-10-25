extends RefCounted
# NEC014: local lifecycle only. Rust owns admission, gameplay and its child Job.
var pid := 0
var error := ""
var _pipes: Dictionary = {}
var _pending := PackedByteArray()
var _closed := false

static func _hash_valid(value: String) -> bool:
	if value.length() != 64: return false
	for c in value:
		if not c in "0123456789abcdef": return false
	return true

func start(launcher: String, launcher_hash: String, release: String, release_hash: String, history: String, controller: int) -> bool:
	if _closed or pid != 0:
		error = "Native owner client cannot be reused"
		return false
	if OS.get_name() != "Windows" or not launcher.is_absolute_path() or not release.is_absolute_path() or not history.is_absolute_path() or controller <= 0:
		error = "Absolute Windows paths and positive controller required"
		return false
	if not _hash_valid(launcher_hash) or not _hash_valid(release_hash) or FileAccess.get_sha256(launcher) != launcher_hash:
		error = "Pinned native launcher identity mismatch"
		return false
	_pipes = OS.execute_with_pipe(launcher, PackedStringArray(["--native-host", "--source", release, "--expected", release_hash, "--history", history, "--controller", str(controller)]), false)
	if _pipes.is_empty():
		error = "Native owner could not start"
		return false
	pid = int(_pipes.pid)
	return true

func send(action: String, slot: String = "") -> bool:
	if _closed or _pipes.is_empty() or not error.is_empty(): return false
	if not action in ["play", "stop", "verify", "status", "check-save"]:
		error = "Unsupported native lifecycle action"
		return false
	var request := {"action":action}
	if action == "check-save":
		if slot.is_empty() or slot.length() > 64:
			error = "Invalid save slot"
			return false
		for c in slot:
			if not c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_":
				error = "Invalid save slot"
				return false
		request.slot = slot
	var payload := (JSON.stringify(request) + "\n").to_utf8_buffer()
	if payload.size() > 8192: return false
	_pipes.stdio.store_buffer(payload)
	if _pipes.stdio.get_error() != OK:
		error = "Native owner pipe write failed"
		return false
	return true

func poll() -> Array:
	var messages: Array = []
	if _closed or _pipes.is_empty() or not error.is_empty(): return messages
	# Fixed byte budget each frame; never use blocking line reads or unbounded queues.
	var bytes: PackedByteArray = _pipes.stdio.get_buffer(65536)
	_pending.append_array(bytes)
	if _pending.size() > 131072:
		error = "Native owner response limit"
		return messages
	while messages.size() < 64:
		var end := _pending.find(10)
		if end < 0: break
		if end > 65536:
			error = "Native owner line limit"
			return []
		var value: Variant = JSON.parse_string(_pending.slice(0,end).get_string_from_utf8())
		_pending = _pending.slice(end+1)
		if not value is Dictionary:
			error = "Malformed native owner response"
			return []
		messages.append(value)
	var diagnostic: PackedByteArray = _pipes.stderr.get_buffer(2048)
	if not diagnostic.is_empty(): error = "Native owner diagnostic: " + diagnostic.get_string_from_utf8()
	if messages.is_empty() and not OS.is_process_running(pid): error = "Native owner exited"
	return messages

func close() -> void:
	if _closed: return
	_closed = true
	if not _pipes.is_empty():
		# EOF is the Rust ownership contract, including abrupt Godot termination.
		_pipes.stdio.close()
		_pipes.stderr.close()
		_pipes.clear()
	_pending.clear()
