extends Node

# Only explicit data decoders are used. Package paths never enter ResourceLoader.
var catalog: Dictionary = {}
var world: Dictionary = {}
var resources: Dictionary = {}
var records: Dictionary = {}
var object_entities: Dictionary = {}
var static_nodes: Array[Node] = []
var effects: Dictionary = {}
var seen: Dictionary = {}
var manager: Node
var current_tick := -1
var overlay_enabled := false
var offset := Vector3(12,10,14)
var applied_count := 0
var duplicate_count := 0
var rollback_count := 0

func prepare(root: String, manifest: Dictionary, admission: Dictionary) -> String:
	if admission.get("catalog") == null:
		return ""
	catalog = _json(FileAccess.get_file_as_bytes(root.path_join(str(admission.catalog))))
	world = _json(FileAccess.get_file_as_bytes(root.path_join("world.json")))
	if catalog.get("schema","") != "xace.player.presentation.v1" or catalog.get("world_hash","") != manifest.get("gameplay",{}).get("world",{}).get("artifact",{}).get("content_hash",""):
		return "Presentation does not match this world."
	for profile in world.get("geometry_profiles",[]):
		if bool(profile.get("required",false)) and profile.get("id","") != "world.aabb.v1":
			return "Required geometry profile is unavailable."
	offset = _vector(catalog.get("camera_offset",[12,10,14]))
	overlay_enabled = bool(catalog.get("collision_overlay",false))
	var admitted_paths: Dictionary = {}
	for file in manifest.get("files",[]):
		admitted_paths[str(file.path)] = true
	var staged: Dictionary = {}
	var statuses: Dictionary = {}
	for entry in catalog.get("assets",[]):
		var id: String = str(entry.asset.id)
		var resource: Variant = null
		var path: String = str(entry.get("path","")) if entry.get("path") != null else ""
		if entry.asset.get("status","") == "Linked" and admitted_paths.has(path) and not path.is_empty() and FileAccess.file_exists(root.path_join(path)):
			var data := FileAccess.get_file_as_bytes(root.path_join(path))
			if data.size() <= 16777216:
				resource = _decode(str(entry.format),data)
		if resource == null and bool(entry.get("required",false)):
			return "A required presentation resource could not be prepared: " + id
		staged[id] = {"entry":entry,"resource":resource}
		statuses[id] = {"asset_id":id,"status":"resolved" if resource != null else "fallback","reason":"available" if resource != null else "cosmetic_missing_or_unsupported"}
	resources = staged
	records = statuses
	return ""

func _json(data: PackedByteArray) -> Dictionary:
	var parsed: Variant = JSON.parse_string(data.get_string_from_utf8())
	return parsed if parsed is Dictionary else {}

func _vector(value: Array) -> Vector3:
	return Vector3(float(value[0]),float(value[1]),float(value[2]))

func _color(value: Array) -> Color:
	return Color(float(value[0]),float(value[1]),float(value[2]),float(value[3]))

func _material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	if color.a < 1.0:
		material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	return material

func _decode(format: String, data: PackedByteArray) -> Variant:
	match format:
		"xace.mesh.v1":
			var value := _json(data)
			if value.get("schema","") != format or value.get("vertices",[]).size() > 65536 or value.get("indices",[]).size() > 196608:
				return null
			var surface := SurfaceTool.new()
			surface.begin(Mesh.PRIMITIVE_TRIANGLES)
			for index in value.get("indices",[]):
				if int(index) < 0 or int(index) >= value.get("vertices",[]).size():
					return null
				surface.add_vertex(_vector(value.vertices[int(index)]))
			if value.get("indices",[]).size() < 3:
				return null
			surface.generate_normals()
			return {"mesh":surface.commit(),"material":_material(_color(value.color))}
		"image.png.v1":
			if data.size() < 33 or data.slice(0,8) != PackedByteArray([137,80,78,71,13,10,26,10]):
				return null
			var width: int = (data[16]<<24)|(data[17]<<16)|(data[18]<<8)|data[19]
			var height: int = (data[20]<<24)|(data[21]<<16)|(data[22]<<8)|data[23]
			if width <= 0 or height <= 0 or width > 4096 or height > 4096 or width*height > 4194304:
				return null
			var image := Image.new()
			if image.load_png_from_buffer(data) != OK:
				return null
			return ImageTexture.create_from_image(image)
		"audio.pcm_wav.v1":
			return _wav(data)
		"xace.effect.ring.v1", "xace.camera.impulse.v1":
			var value := _json(data)
			return value if value.get("schema","") == format else null
	return null

func _wav(data: PackedByteArray) -> AudioStreamWAV:
	if data.size() < 44 or data.slice(0,4).get_string_from_ascii() != "RIFF" or data.slice(8,12).get_string_from_ascii() != "WAVE":
		return null
	var at := 12
	var channels := 0
	var bits := 0
	var rate := 0
	var samples := PackedByteArray()
	while at+8 <= data.size():
		var tag := data.slice(at,at+4).get_string_from_ascii()
		var length: int = data.decode_u32(at+4)
		at += 8
		if at+length > data.size():
			return null
		if tag == "fmt ":
			if length < 16 or data.decode_u16(at) != 1:
				return null
			channels = data.decode_u16(at+2)
			rate = data.decode_u32(at+4)
			bits = data.decode_u16(at+14)
		elif tag == "data":
			samples = data.slice(at,at+length)
		at += length+(length%2)
	if channels not in [1,2] or bits not in [8,16] or rate < 8000 or rate > 96000 or samples.is_empty() or samples.size() > rate*channels*(bits/8)*10:
		return null
	if bits == 8:
		for index in samples.size():
			samples[index] = (int(samples[index])-128)&255
	var audio := AudioStreamWAV.new()
	audio.format = AudioStreamWAV.FORMAT_8_BITS if bits == 8 else AudioStreamWAV.FORMAT_16_BITS
	audio.stereo = channels == 2
	audio.mix_rate = rate
	audio.data = samples
	return audio

func bind_world(ack: Dictionary, target: Node) -> String:
	manager = target
	if catalog.is_empty():
		return ""
	if not ack.get("runtime_capabilities",[]).has("xace.world_bindings.v1") or not ack.get("runtime_capabilities",[]).has("xace.presentation_event.v1"):
		return "Runtime lacks the required presentation contract."
	var candidate: Dictionary = ack.get("world_bindings",{})
	for object in world.get("objects",[]):
		var id := int(candidate.get(str(object.id),"0"))
		if id <= 0 or manager.get_entity_node(id) == null:
			return "World object binding is missing: "+str(object.id)
		var geometry: Variant = object.get("geometry")
		if geometry is Dictionary:
			var collider: Dictionary = manager.component_snapshot(id).get(4,{}).get("data",{})
			if collider.get("shape","") != "BOX" or collider.get("size",{}) != geometry.get("size",{}) or collider.get("offset",{}) != geometry.get("offset",{}) or bool(collider.get("is_trigger",false)) != bool(geometry.get("is_trigger",false)) or int(collider.get("layer_mask",1)) != int(geometry.get("layer_mask",1)):
				return "Required canonical geometry differs from the world binding."
	object_entities = candidate.duplicate(true)
	_apply_static()
	return ""

func _remove(node: Node) -> void:
	if is_instance_valid(node):
		if node is AudioStreamPlayer3D:
			(node as AudioStreamPlayer3D).stop()
		if node.get_parent() != null:
			node.get_parent().remove_child(node)
		node.queue_free()

func _apply_static() -> void:
	for node in static_nodes:
		if is_instance_valid(node) and node.get_parent() != null:
			var owner_node := node.get_parent()
			owner_node.remove_meta("xace_presentation_visual")
			var canonical := owner_node.get_node_or_null("CanonicalVisual")
			if canonical != null:
				canonical.visible = bool(node.get_meta("canonical_was_visible",true))
		_remove(node)
	static_nodes.clear()
	for binding in catalog.get("objects",[]):
		var node: Node3D = manager.get_entity_node(int(object_entities.get(binding.object_id,"0")))
		if node == null:
			continue
		var item: Dictionary = resources.get(binding.asset.id,{})
		var resource: Variant = item.get("resource")
		if resource == null:
			continue
		var visual := MeshInstance3D.new()
		visual.name = "PresentationVisual"
		if item.entry.format == "xace.mesh.v1":
			visual.mesh = resource.mesh
			visual.material_override = resource.material
		else:
			visual.mesh = QuadMesh.new()
			var material := _material(Color.WHITE)
			material.albedo_texture = resource
			material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
			material.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
			visual.material_override = material
		node.add_child(visual)
		static_nodes.append(visual)
		node.set_meta("xace_presentation_visual",true)
		var canonical := node.get_node_or_null("CanonicalVisual")
		if canonical != null:
			visual.set_meta("canonical_was_visible",canonical.visible)
			canonical.visible = false
	refresh_overlays()

func refresh_overlays() -> void:
	if manager == null:
		return
	for id in manager._components:
		var node: Node3D = manager.get_entity_node(id)
		if node == null:
			continue
		var overlay := node.get_node_or_null("CollisionGuide") as MeshInstance3D
		if overlay == null:
			overlay = MeshInstance3D.new()
			overlay.name = "CollisionGuide"
			node.add_child(overlay)
		var collider: Dictionary = manager.component_snapshot(id).get(4,{}).get("data",{})
		overlay.visible = overlay_enabled and collider.get("shape","") == "BOX"
		if not overlay.visible:
			continue
		var half: Vector3 = manager._fixed_vector(collider.get("size",{}))*0.5
		var mesh := ImmediateMesh.new()
		mesh.surface_begin(Mesh.PRIMITIVE_LINES)
		for a in range(8):
			for axis in [1,2,4]:
				var b: int = a^axis
				if b <= a:
					continue
				for corner in [a,b]:
					mesh.surface_add_vertex(Vector3(half.x if corner&1 else -half.x,half.y if corner&2 else -half.y,half.z if corner&4 else -half.z))
		mesh.surface_end()
		overlay.mesh = mesh
		overlay.position = manager._fixed_vector(collider.get("offset",{}))
		var material := _material(Color(0.25,1.0,0.5))
		material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		material.no_depth_test = true
		overlay.material_override = material

func apply_snapshot(snapshot: Dictionary) -> void:
	var tick := int(snapshot.get("tick",0))
	if tick < current_tick:
		return
	current_tick = tick
	for key in seen.keys():
		if int(seen[key]) < tick-1200:
			seen.erase(key)
	for event in snapshot.get("events",[]):
		var data: Dictionary = event.get("data",{})
		if data.get("schema","") != "xace.presentation_event.v1" or int(data.get("tick",-1)) != tick:
			continue
		for binding in catalog.get("events",[]):
			if binding.event_name != event.get("event_type",""):
				continue
			var key := str(data.get("occurrence_id",""))+":"+str(binding.binding_id)
			if seen.has(key):
				duplicate_count += 1
				continue
			if seen.size() >= 8192:
				continue
			seen[key] = tick
			var entity: int = int(event.get("entity_id",0)) if binding.entity_selector == "source" else int(data.get("target_entity_id","0"))
			_spawn(key,entity,binding.asset.id,tick)
	_update_effects(tick)

func _spawn(key: String, entity: int, asset_id: String, tick: int) -> void:
	if manager == null or effects.size() >= 256:
		return
	var source: Node3D = manager.get_entity_node(entity)
	if source == null:
		return
	var item: Dictionary = resources.get(asset_id,{})
	if item.is_empty():
		return
	var resource: Variant = item.get("resource")
	var format: String = str(item.entry.format)
	if resource == null and item.entry.fallback == "silent":
		return
	var node: Node3D = null
	var duration := 30
	if format == "audio.pcm_wav.v1" and resource != null:
		var audio := AudioStreamPlayer3D.new()
		audio.stream = resource
		node = audio
		duration = 600
	elif format == "xace.camera.impulse.v1" and resource != null:
		duration = int(resource.duration_ticks)
	else:
		var visual := MeshInstance3D.new()
		var mesh := TorusMesh.new()
		var radius: float = float(resource.radius) if resource != null and format == "xace.effect.ring.v1" else 0.6
		mesh.inner_radius = radius*0.9
		mesh.outer_radius = radius
		visual.mesh = mesh
		var color: Color = _color(resource.color) if resource != null and format == "xace.effect.ring.v1" else Color(1,0.6,0.1,0.8)
		var material := _material(color)
		material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		visual.material_override = material
		node = visual
		if resource != null:
			duration = int(resource.duration_ticks)
	if node != null:
		manager.add_child(node)
		node.global_position = source.global_position
		if node is AudioStreamPlayer3D:
			(node as AudioStreamPlayer3D).play()
	effects[key] = {"node":node,"start":tick,"duration":duration,"format":format,"resource":resource}
	applied_count += 1

func _update_effects(tick: int) -> void:
	for key in effects.keys():
		var effect: Dictionary = effects[key]
		var age: int = tick-int(effect.start)
		if age >= int(effect.duration):
			if effect.node != null:
				_remove(effect.node)
			effects.erase(key)
		elif effect.node is MeshInstance3D:
			effect.node.scale = Vector3.ONE*maxf(0.1,float(age+1)/float(effect.duration))

func camera_offset() -> Vector3:
	var result := offset
	for effect in effects.values():
		if effect.format == "xace.camera.impulse.v1" and effect.resource != null:
			var weight := 1.0-float(current_tick-int(effect.start))/float(effect.duration)
			result += _vector(effect.resource.offset)*maxf(weight,0.0)
	return result

func rollback(tick: int) -> void:
	for effect in effects.values():
		if effect.node != null:
			_remove(effect.node)
	effects.clear()
	seen.clear()
	current_tick = tick-1
	rollback_count += 1

func restore_static() -> void:
	_apply_static()

func readiness_report() -> Dictionary:
	return {"schema":"xace.player.presentation_status.v1","records":records.values(),"world_bindings":object_entities,"active_effects":effects.size(),"applied_effects":applied_count,"duplicate_events":duplicate_count,"rollbacks":rollback_count}

func fallback_count() -> int:
	var count := 0
	for record in records.values():
		if record.status == "fallback":
			count += 1
	return count
