extends "res://adapter/xace_canonical_entities.gd"
# Shared canonical mirror; Player admits presentation only through its catalog.
func _script_base_dir() -> String:
	return "res://adapter"

func apply_playback_commands(_commands: Array) -> void:
	pass
