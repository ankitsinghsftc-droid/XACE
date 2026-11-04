extends SceneTree
# Original test content, created with native Godot APIs before XACE enrollment.
func save_resource(value: Resource, path: String) -> void:
 assert(ResourceSaver.save(value, path) == OK)
 if ResourceLoader.get_resource_uid(path) < 0:
  assert(ResourceSaver.set_uid(path, ResourceUID.create_id()) == OK)

func save_scene(node: Node, path: String) -> void:
 var packed := PackedScene.new()
 assert(packed.pack(node) == OK)
 save_resource(packed, path)

func _init() -> void:
 DirAccess.make_dir_recursive_absolute('res://Game')
 var surface_material := '--surface-material' in OS.get_cmdline_user_args()
 var mesh := BoxMesh.new()
 var material := StandardMaterial3D.new()
 material.albedo_color = Color(0.2, 0.6, 0.8)
 save_resource(material, 'res://Game/CrateMaterial.res')
 if surface_material:mesh.material=load('res://Game/CrateMaterial.res')
 save_resource(mesh, 'res://Game/CrateMesh.res')
 var audio := AudioStreamWAV.new()
 audio.format = AudioStreamWAV.FORMAT_8_BITS
 audio.mix_rate = 22050
 var samples := PackedByteArray()
 samples.resize(2205)
 samples.fill(128)
 audio.data = samples
 save_resource(audio, 'res://Game/Tone.res')
 var animation := Animation.new()
 animation.length = 1.0
 var track := animation.add_track(Animation.TYPE_VALUE)
 animation.track_set_path(track, NodePath('Crate0:position'))
 animation.track_insert_key(track, 0.0, Vector3.ZERO)
 animation.track_insert_key(track, 1.0, Vector3(1, 0, 0))
 save_resource(animation, 'res://Game/Move.res')
 var template := MeshInstance3D.new()
 template.name = 'Crate'
 template.mesh = load('res://Game/CrateMesh.res')
 if not surface_material:template.material_override = load('res://Game/CrateMaterial.res')
 save_scene(template, 'res://Game/Crate.tscn')
 template.free()
 var source := FileAccess.open('res://Game/NativeScore.gd', FileAccess.WRITE)
 source.store_string('extends Node3D\nvar native_score := 0\nfunc _process(_delta: float) -> void:\n native_score += 1\n')
 source.close()
 var world := Node3D.new()
 world.name = 'World'
 for n in range(50):
  var node := (load('res://Game/Crate.tscn') as PackedScene).instantiate()
  node.name = 'Crate' + str(n)
  world.add_child(node)
  node.owner = world
  node.position = Vector3(n % 10, 0, n / 10)
 for group_name in ['North', 'South']:
  var group := Node3D.new()
  group.name = group_name
  world.add_child(group)
  group.owner = world
  var child := Node3D.new()
  child.name = 'DuplicateDisplayName'
  group.add_child(child)
  child.owner = world
 var sound := AudioStreamPlayer3D.new()
 sound.name = 'NativeAudio'
 sound.stream = load('res://Game/Tone.res')
 world.add_child(sound)
 sound.owner = world
 var player := AnimationPlayer.new()
 player.name = 'NativeAnimation'
 var library := AnimationLibrary.new()
 library.add_animation('move', load('res://Game/Move.res'))
 player.add_animation_library('', library)
 world.add_child(player)
 player.owner = world
 var native_logic := Node3D.new()
 native_logic.name = 'UnsupportedCriticalScore'
 native_logic.set_script(load('res://Game/NativeScore.gd'))
 world.add_child(native_logic)
 native_logic.owner = world
 save_scene(world, 'res://Game/World.tscn')
 var annex := Node3D.new()
 annex.name = 'Annex'
 var annex_child := (load('res://Game/Crate.tscn') as PackedScene).instantiate()
 annex.add_child(annex_child)
 annex_child.owner = annex
 save_scene(annex, 'res://Game/Annex.tscn')
 var input := InputEventKey.new()
 input.physical_keycode = KEY_SPACE
 ProjectSettings.set_setting('input/jump', {'deadzone':0.5, 'events':[input]})
 ProjectSettings.set_setting('application/run/main_scene', 'res://Game/World.tscn')
 assert(ProjectSettings.save() == OK)
 var report := {'ok':true, 'phase':'pre-adoption fixture only', 'engine':Engine.get_version_info().string, 'main_scene_children':world.get_child_count(), 'authored_crate_instances':50, 'scenes':['Game/World.tscn','Game/Annex.tscn'], 'native_prefab':'Game/Crate.tscn', 'unsupported_critical_dependency':'Game/NativeScore.gd', 'surface_material':surface_material, 'xace_enrolled':false, 'adoption_verified':false, 'license':'Original test content; CC0-1.0'}
 var output := FileAccess.open('res://fixture-created.json',FileAccess.WRITE)
 output.store_string(JSON.stringify(report))
 output.close()
 world.free()
 annex.free()
 quit(0)
