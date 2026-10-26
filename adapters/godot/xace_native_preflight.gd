extends SceneTree
# Trusted creator/native package check. Loads the admitted main scene, but marks
# native hosts preflight-only before _ready, so no Rust authority starts.
var hosts: Array = []
func _initialize() -> void: call_deferred("run")
func collect(node: Node) -> void:
	var script: Script = node.get_script()
	if script != null and script.resource_path.get_file()=="xace_native_host.gd":
		node.preflight_only=true
		hosts.append(node)
	for child in node.get_children(): collect(child)
func run() -> void:
	var path := str(ProjectSettings.get_setting("application/run/main_scene",""))
	var packed: Resource = load(path) if ResourceLoader.exists(path) else null
	if not packed is PackedScene: finish(false,"Main scene missing");return
	var scene: Node = packed.instantiate()
	collect(scene)
	if hosts.size()!=1: scene.free();finish(false,"Exactly one approved native host required");return
	root.add_child(scene)
	var host: Node = hosts[0]
	var ok: bool = host.state=="preflight-ready"
	var issue: String = host.error
	scene.free()
	finish(ok,issue)
func finish(ok: bool,issue: String) -> void:
	var args := OS.get_cmdline_user_args()
	if args.size()!=1: quit(2);return
	FileAccess.open(args[0],FileAccess.WRITE).store_string(JSON.stringify({"ok":ok,"error":issue,"packed":not OS.has_feature("editor"),"authority_started":false}))
	quit(0 if ok else 1)
