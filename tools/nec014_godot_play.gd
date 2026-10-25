extends SceneTree
var config: Dictionary
var host: Node
var scene: Node3D
var original: Array = []
var started := 0
var done := false
func _initialize() -> void:
	config = JSON.parse_string(FileAccess.get_file_as_string(OS.get_cmdline_user_args()[0]))
	call_deferred("run")
func run() -> void:
	var approval_error: String = load("res://xace_native_approval.gd").record()
	assert(approval_error.is_empty(),approval_error)
	scene = Node3D.new()
	root.add_child(scene)
	var world: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(config.release+"/package/world.json"))
	var nodes: Dictionary = {}
	for object in world.objects:
		var node := Node3D.new()
		node.name = "Existing"+str(nodes.size())
		scene.add_child(node)
		nodes[object.id] = node
		original.append(node)
	for object in world.objects:
		var node: Node3D = nodes[object.id]
		var parent: Array = object.relationships.get("xace.authoring_parent.v1",[])
		if not parent.is_empty(): node.reparent(nodes[parent[0]])
		var pos: Dictionary = object.transform.position
		node.global_position = Vector3(pos.x,pos.y,pos.z)/1000000.0
	host = load("res://xace_native_host.gd").new()
	host.name = "NativeHost"
	host.profile_path = config.profile
	scene.add_child(host)
	started = Time.get_ticks_msec()
func _process(_delta: float) -> bool:
	if done or host == null: return false
	if host.state == "failed": finish(false,host.error);return false
	if Time.get_ticks_msec()-started>30000: finish(false,"Native play timeout");return false
	if host.state != "playing": return false
	host.collector.submit_native_action("proof.move",1.0)
	if host.adapter._last_runtime_tick<12: return false
	var ok: bool = host.manager.entity_count()==2 and original[1].get_parent()==original[0] and original[1].global_position.x>7.1
	for node in host.manager._nodes.values(): ok = ok and original.has(node) and node.get_node_or_null("CanonicalVisual")==null
	finish(ok,"" if ok else "Native identity/hierarchy/input failed")
	return false
func finish(ok: bool,why: String) -> void:
	done = true
	var report := {"ok":ok,"error":why,"state":host.state,"tick":host.adapter._last_runtime_tick if host.manager!=null else 0,"runtime_pid":host.runtime_pid,"owner_pid":host.host_client.pid if host.host_client!=null else 0,"native_scene_identity":ok,"native_parent_preserved":ok,"input_moves_authority":ok,"export_verified":false}
	host.stop()
	FileAccess.open(config.report,FileAccess.WRITE).store_string(JSON.stringify(report,"\t"))
	quit(0 if ok else 1)
