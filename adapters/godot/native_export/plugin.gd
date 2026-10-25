@tool
extends EditorPlugin
var exporter: EditorExportPlugin
func approval() -> Script:
	return load(ProjectSettings.get_setting("xace/native_adapter_directory","res://").path_join("xace_native_approval.gd"))
func _enter_tree() -> void:
	exporter=load(get_script().resource_path.get_base_dir().path_join("export_hook.gd")).new()
	add_export_plugin(exporter)
	add_tool_menu_item("XACE: approve saved native revision",approve)
func _exit_tree() -> void:
	remove_tool_menu_item("XACE: approve saved native revision")
	remove_export_plugin(exporter)
func approve() -> void:
	EditorInterface.save_all_scenes()
	var issue: String = approval().record()
	if not issue.is_empty(): push_error("[XACE] "+issue)
func _build() -> bool:
	EditorInterface.save_all_scenes()
	var issue: String = approval().validate()
	if not issue.is_empty(): push_error("[XACE] Play refused: "+issue)
	return issue.is_empty()
