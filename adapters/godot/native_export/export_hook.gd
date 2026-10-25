@tool
extends EditorExportPlugin
func _get_name() -> String: return "XaceNativeExport"
func _export_begin(features: PackedStringArray, _debug: bool, _path: String, _flags: int) -> void:
	var approval: Script = load(ProjectSettings.get_setting("xace/native_adapter_directory","res://").path_join("xace_native_approval.gd"))
	var issue: String = approval.validate()
	if not "windows" in features or not "x86_64" in features: issue="Windows x64 native profile required"
	var stamp := {"schema":"xace.godot.export_preflight.v1","approved":issue.is_empty(),"error":issue,"source_approval_sha256":FileAccess.get_sha256("res://XACEApproval.json"),"profile_sha256":FileAccess.get_sha256("res://xace-native-profile.json")}
	# The callback has no cancellation return value. A refused export carries an
	# explicit runtime refusal stamp; the creator wrapper must also refuse receipt.
	add_file("res://xace-export-preflight.json",JSON.stringify(stamp).to_utf8_buffer(),false)
	if not issue.is_empty(): push_error("[XACE] Export refused: "+issue)
