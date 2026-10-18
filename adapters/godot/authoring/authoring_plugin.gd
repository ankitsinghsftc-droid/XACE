@tool
extends EditorPlugin
## Opt-in editor entry point. Runtime Player shares the existing wire protocol,
## never this privileged plugin. Approval is explicit and not persisted.
const Reader = preload("authoring_reader.gd")
const Writer = preload("authoring_writer.gd")
var reader = Reader.new()
var writer = Writer.new()

func _enter_tree() -> void:
	scene_changed.connect(_invalidate)
	scene_saved.connect(_invalidate)
	EditorInterface.get_resource_filesystem().filesystem_changed.connect(_invalidate)
	get_undo_redo().history_changed.connect(_invalidate)
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--xace-authoring-command="):
			call_deferred("_run_host_command", arg.trim_prefix("--xace-authoring-command="))

func _invalidate(_unused: Variant = null) -> void:
	reader.rescan_required = true
	writer.reader.rescan_required = true

func approve_trusted_project() -> void:
	reader.trusted_project = true
	writer.reader.trusted_project = true

func enroll(node: Node, identity: Dictionary, expected_old: Variant = null) -> bool:
	reader.error = ""
	if not reader.editor() or not reader.metadata(identity): return false
	var root := EditorInterface.get_edited_scene_root()
	if root == null or (node != root and not root.is_ancestor_of(node)):
		reader.fail("enrollment requires selected local edited scene")
		return false
	var old: Variant = node.get_meta(reader.META, null)
	if old != expected_old or (old != null and (identity.authoring_id == old.get("authoring_id") or identity.local_id == old.get("local_id"))):
		reader.fail("stale/ambiguous enrollment; explicit distinct identity required")
		return false
	var undo := get_undo_redo()
	undo.create_action("XACE enroll native identity", UndoRedo.MERGE_DISABLE, node)
	var ancestor := node.get_parent()
	while ancestor != null and ancestor != root:
		if not ancestor.scene_file_path.is_empty() and not root.is_editable_instance(ancestor):
			undo.add_do_method(root, "set_editable_instance", ancestor, true)
			undo.add_undo_method(root, "set_editable_instance", ancestor, false)
		ancestor = ancestor.get_parent()
	undo.add_do_method(node, "set_meta", reader.META, identity.duplicate(true))
	if old == null: undo.add_undo_method(node, "remove_meta", reader.META)
	else: undo.add_undo_method(node, "set_meta", reader.META, old.duplicate(true))
	undo.commit_action()
	EditorInterface.mark_scene_as_unsaved()
	_invalidate()
	return true

func rescan(approved_saved_scenes: Array) -> Dictionary:
	# Always re-read disk, even when an editor/file event was missed.
	return reader.capture(approved_saved_scenes)

func _run_host_command(path: String) -> void:
	var command = preload("authoring_command.gd").new()
	get_tree().quit(0 if command.run(path) else 1)
