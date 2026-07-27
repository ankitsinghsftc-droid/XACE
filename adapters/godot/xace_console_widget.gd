extends Control
class_name XaceConsoleWidget

signal prompt_submitted(prompt: String)
signal apply_requested()
signal cancel_requested()
signal closed

enum ConsoleState {
	IDLE,
	PROMPT_SUBMITTED,
	PREVIEW_RECEIVED,
	USER_DECISION,
	APPLYING,
	ERROR,
}

@export var toggle_action := "xace_console"
@export var start_visible := false
@export var max_log_lines := 200

var _state := ConsoleState.IDLE
var _adapter: Node
var _root: PanelContainer
var _prompt: LineEdit
var _submit_button: Button
var _apply_button: Button
var _cancel_button: Button
var _state_label: Label
var _confidence: ProgressBar
var _log: RichTextLabel
var _log_lines: Array[String] = []


func _ready() -> void:
	_build_ui()
	visible = start_visible
	_set_state(ConsoleState.IDLE)


func _unhandled_input(event: InputEvent) -> void:
	if toggle_action.is_empty() or not InputMap.has_action(toggle_action):
		return
	if event.is_action_pressed(toggle_action):
		visible = not visible
		if not visible:
			closed.emit()
		get_viewport().set_input_as_handled()


func bind_adapter(adapter: Node) -> void:
	_adapter = adapter
	if _adapter != null:
		if _adapter.has_signal("runtime_error") and not _adapter.is_connected("runtime_error", Callable(self, "_on_runtime_error")):
			_adapter.connect("runtime_error", Callable(self, "_on_runtime_error"))
		if _adapter.has_signal("tick_applied") and not _adapter.is_connected("tick_applied", Callable(self, "_on_tick_applied")):
			_adapter.connect("tick_applied", Callable(self, "_on_tick_applied"))


func receive_preview(summary: String, confidence: float) -> void:
	_log_line("preview: %s" % summary)
	_confidence.value = clampf(confidence, 0.0, 1.0) * 100.0
	_set_state(ConsoleState.USER_DECISION)


func submit_prompt() -> void:
	var text := _prompt.text.strip_edges()
	if text.is_empty():
		return
	_prompt.clear()
	_log_line("> %s" % text)
	_set_state(ConsoleState.PROMPT_SUBMITTED)
	prompt_submitted.emit(text)


func set_error(message: String) -> void:
	_log_line("error: %s" % message)
	_set_state(ConsoleState.ERROR)


func state_name() -> String:
	match _state:
		ConsoleState.IDLE:
			return "Idle"
		ConsoleState.PROMPT_SUBMITTED:
			return "PromptSubmitted"
		ConsoleState.PREVIEW_RECEIVED:
			return "PreviewReceived"
		ConsoleState.USER_DECISION:
			return "UserDecision"
		ConsoleState.APPLYING:
			return "Applying"
		ConsoleState.ERROR:
			return "Error"
		_:
			return "Unknown"


func _build_ui() -> void:
	anchor_right = 1.0
	anchor_bottom = 1.0
	mouse_filter = Control.MOUSE_FILTER_STOP

	_root = PanelContainer.new()
	_root.name = "ConsolePanel"
	_root.anchor_left = 0.02
	_root.anchor_top = 0.62
	_root.anchor_right = 0.55
	_root.anchor_bottom = 0.98
	add_child(_root)

	var layout := VBoxContainer.new()
	layout.name = "Layout"
	layout.add_theme_constant_override("separation", 6)
	_root.add_child(layout)

	_state_label = Label.new()
	_state_label.text = "Idle"
	layout.add_child(_state_label)

	_log = RichTextLabel.new()
	_log.name = "Log"
	_log.fit_content = false
	_log.scroll_following = true
	_log.custom_minimum_size = Vector2(360, 120)
	layout.add_child(_log)

	_confidence = ProgressBar.new()
	_confidence.name = "Confidence"
	_confidence.min_value = 0
	_confidence.max_value = 100
	_confidence.value = 0
	layout.add_child(_confidence)

	var input_row := HBoxContainer.new()
	input_row.name = "InputRow"
	layout.add_child(input_row)

	_prompt = LineEdit.new()
	_prompt.name = "Prompt"
	_prompt.placeholder_text = "Describe an edit"
	_prompt.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	input_row.add_child(_prompt)

	_submit_button = Button.new()
	_submit_button.text = "Send"
	input_row.add_child(_submit_button)

	var decision_row := HBoxContainer.new()
	decision_row.name = "DecisionRow"
	layout.add_child(decision_row)

	_apply_button = Button.new()
	_apply_button.text = "Apply"
	decision_row.add_child(_apply_button)

	_cancel_button = Button.new()
	_cancel_button.text = "Cancel"
	decision_row.add_child(_cancel_button)

	_prompt.text_submitted.connect(func(_text): submit_prompt())
	_submit_button.pressed.connect(submit_prompt)
	_apply_button.pressed.connect(_on_apply_pressed)
	_cancel_button.pressed.connect(_on_cancel_pressed)


func _set_state(next_state: int) -> void:
	_state = next_state
	if _state_label != null:
		_state_label.text = state_name()
	var can_prompt := _state == ConsoleState.IDLE or _state == ConsoleState.ERROR
	var can_decide := _state == ConsoleState.USER_DECISION
	if _prompt != null:
		_prompt.editable = can_prompt
	if _submit_button != null:
		_submit_button.disabled = not can_prompt
	if _apply_button != null:
		_apply_button.disabled = not can_decide
	if _cancel_button != null:
		_cancel_button.disabled = not can_decide and _state != ConsoleState.PROMPT_SUBMITTED


func _on_apply_pressed() -> void:
	_log_line("apply requested")
	_set_state(ConsoleState.APPLYING)
	apply_requested.emit()


func _on_cancel_pressed() -> void:
	_log_line("cancelled")
	_set_state(ConsoleState.IDLE)
	cancel_requested.emit()


func _on_runtime_error(message: String) -> void:
	set_error(message)


func _on_tick_applied(tick: int) -> void:
	if _state == ConsoleState.APPLYING:
		_log_line("applied at tick %d" % tick)
		_set_state(ConsoleState.IDLE)


func _log_line(text: String) -> void:
	_log_lines.append(text)
	while _log_lines.size() > max_log_lines:
		_log_lines.pop_front()
	if _log != null:
		_log.text = "\n".join(_log_lines)
