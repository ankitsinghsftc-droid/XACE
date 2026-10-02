extends SceneTree

func _initialize() -> void:
    call_deferred("_run")

func _run() -> void:
    var p: Node = load("res://presentation.gd").new()
    root.add_child(p)
    var manifest: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://package/playable.manifest.json"))
    var admission: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://admission.json")).presentation
    assert(p.prepare("res://package",manifest,admission)=="")
    assert(p.fallback_count()==0)
    assert(p.resources.sound.resource is AudioStreamWAV)
    assert(p.resources.floor_skin.resource.mesh is ArrayMesh)
    var image := Image.create(2,2,false,Image.FORMAT_RGBA8)
    image.fill(Color.WHITE)
    assert(p._decode("image.png.v1",image.save_png_to_buffer()) is ImageTexture)
    assert(p._decode("godot.packed_scene.v1",PackedByteArray())==null)
    assert(p._decode("audio.pcm_wav.v1",PackedByteArray())==null)
    var manager: Node3D = load("res://canonical_entities.gd").new()
    manager.create_visual_nodes=false
    root.add_child(manager)
    var entities: Array = []
    var mappings := {}
    var next := 1
    for object in p.world.objects:
        var collider: Dictionary = object.get("geometry",{}).duplicate(true)
        collider["shape"]="BOX"
        entities.append({"id":next,"components":{"1":JSON.stringify(object.transform),"4":JSON.stringify(collider)}})
        mappings[object.id]=str(next)
        next+=1
    manager.apply_handshake_ack({"accepted":true,"initial_entities":entities})
    var ack := {"runtime_capabilities":["xace.world_bindings.v1","xace.presentation_event.v1"],"world_bindings":mappings}
    assert(p.bind_world(ack,manager)=="")
    assert(p.static_nodes.size()==4)
    var node: Node3D = manager.get_entity_node(int(mappings.floor))
    assert(node.has_meta("xace_presentation_visual"))
    assert(node.get_node("CollisionGuide").visible)
    p.resources.floor_skin.resource=null
    p.restore_static()
    assert(not node.has_meta("xace_presentation_visual"))
    assert(node.get_node("CanonicalVisual").visible)
    assert(p.static_nodes.size()==3)
    # A renderer cannot certify a collider that disagrees with canonical geometry.
    p.world.objects[0].geometry.size.x=123
    assert(not p.bind_world(ack,manager).is_empty())
    var restricted := manifest.duplicate(true)
    restricted.files = restricted.files.filter(func(file): return file.path != "presentation/resources/pulse.json")
    assert(p.prepare("res://package",restricted,admission)=="")
    assert(p.resources.pulse.resource==null)
    p.rollback(0)
    assert(p.effects.is_empty())
    print("XP009 presentation: 19 assertions passed")
    quit()
