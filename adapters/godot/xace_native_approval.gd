@tool
extends RefCounted
# Source approvals are explicit and immutable; generated Godot caches excluded.
static func inventory(directory: String = "res://", prefix: String = "") -> Dictionary:
	var result := {}
	for file in DirAccess.get_files_at(directory):
		var relative := prefix+file
		if relative == "XACEApproval.json": continue
		result[relative] = FileAccess.get_sha256(directory.path_join(file))
	for folder in DirAccess.get_directories_at(directory):
		if prefix.is_empty() and folder in [".godot", ".git", "XACEEvidence"]: continue
		result.merge(inventory(directory.path_join(folder),prefix+folder+"/"))
	return result
static func validate() -> String:
	var approval: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://XACEApproval.json"))
	if not approval is Dictionary or approval.get("schema") != "xace.godot.source_approval.v1": return "Explicit native source approval required"
	if approval.get("godot") != Engine.get_version_info().string: return "Godot version changed since approval"
	if approval.get("files") != inventory(): return "Native sources/resources changed since approval"
	return ""
static func record() -> String:
	if FileAccess.file_exists("res://XACEApproval.json"): return "Retain approval; use a separately reviewed project revision"
	var snapshot := inventory()
	var file := FileAccess.open("res://XACEApproval.json",FileAccess.WRITE)
	if file == null: return "Cannot record native source approval"
	file.store_string(JSON.stringify({"schema":"xace.godot.source_approval.v1","godot":Engine.get_version_info().string,"files":snapshot},"\t"))
	file.close()
	return ""
