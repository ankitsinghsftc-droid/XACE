extends SceneTree
func _initialize():
	var file=FileAccess.open(OS.get_cmdline_user_args()[0],FileAccess.WRITE)
	file.store_string(JSON.stringify({"version":Engine.get_version_info(),"license":Engine.get_license_text(),"copyright":Engine.get_copyright_info(),"licenses":Engine.get_license_info()},"  "))
	file.flush()
	file.close()
	quit()
