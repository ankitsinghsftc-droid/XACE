extends Control
class_name XaceDebugHUD

@export var refresh_interval_sec := 0.1
@export var start_visible := true

var _adapter: Node
var _elapsed := 0.0
var _root: PanelContainer
var _label: Label
var _last_stats := {}


func _ready() -> void:
	_build_ui()
	visible = start_visible
	set_process(true)


func bind_adapter(adapter: Node) -> void:
	_adapter = adapter
	if _adapter != null:
		if _adapter.has_signal("connected") and not _adapter.is_connected("connected", Callable(self, "_on_connected")):
			_adapter.connect("connected", Callable(self, "_on_connected"))
		if _adapter.has_signal("disconnected") and not _adapter.is_connected("disconnected", Callable(self, "_on_disconnected")):
			_adapter.connect("disconnected", Callable(self, "_on_disconnected"))
	_update_label()


func _process(delta: float) -> void:
	_elapsed += delta
	if _elapsed < refresh_interval_sec:
		return
	_elapsed = 0.0
	_update_label()


func stats_snapshot() -> Dictionary:
	return _last_stats.duplicate(true)


func _build_ui() -> void:
	anchor_right = 1.0
	anchor_bottom = 1.0
	mouse_filter = Control.MOUSE_FILTER_IGNORE

	_root = PanelContainer.new()
	_root.anchor_left = 0.72
	_root.anchor_top = 0.02
	_root.anchor_right = 0.98
	_root.anchor_bottom = 0.30
	add_child(_root)

	_label = Label.new()
	_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_label.text = "XACE\nDisconnected"
	_root.add_child(_label)


func _update_label() -> void:
	var connected: bool = false
	var stats: Dictionary = {}
	if _adapter != null:
		if _adapter.has_method("is_runtime_connected"):
			connected = bool(_adapter.call("is_runtime_connected"))
		if _adapter.has_method("stats"):
			var maybe_stats: Variant = _adapter.call("stats")
			if typeof(maybe_stats) == TYPE_DICTIONARY:
				stats = maybe_stats as Dictionary
	_last_stats = stats.duplicate(true)
	if _label == null:
		return
	_label.text = "XACE\n%s\nTick: %d\nCGS: %s\nSnapshot: %s\nEntities: %d\nSent: %d\nRecv: %d\nQueued: %d" % [
		"Connected" if connected else "Disconnected",
		int(stats.get("last_runtime_tick", 0)),
		_short_hash(str(stats.get("cgs_hash", ""))),
		_short_hash(str(stats.get("snapshot_hash", ""))),
		int(stats.get("entity_count", 0)),
		int(stats.get("frames_sent", 0)),
		int(stats.get("frames_received", 0)),
		int(stats.get("queued_messages", 0)),
	]


func _short_hash(value: String) -> String:
	if value.is_empty():
		return "-"
	return value.left(12)


func _on_connected() -> void:
	_update_label()


func _on_disconnected(_reason: String) -> void:
	_update_label()
