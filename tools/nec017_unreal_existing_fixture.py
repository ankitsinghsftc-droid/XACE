"""Native Unreal-only pre-adoption fixture. Run by installed PythonScriptPlugin.
No XACE code or generated CGS is loaded. Failure leaves its new directory intact.
"""
import json
from pathlib import Path
import unreal as u
u.load_module("BinkAudioDecoder")

project = Path(u.Paths.project_dir())
assets = u.AssetToolsHelpers.get_asset_tools()
actors = u.get_editor_subsystem(u.EditorActorSubsystem)
levels = u.get_editor_subsystem(u.LevelEditorSubsystem)
assert levels.new_level('/Game/World')
mesh = u.EditorAssetLibrary.duplicate_asset('/Engine/BasicShapes/Cube', '/Game/CrateMesh')
material = u.EditorAssetLibrary.duplicate_asset('/Engine/BasicShapes/BasicShapeMaterial', '/Game/CrateMaterial')
assert mesh and material
factory = u.BlueprintFactory()
factory.set_editor_property('parent_class', u.StaticMeshActor)
blueprint = assets.create_asset('Crate', '/Game', u.Blueprint, factory)
u.BlueprintEditorLibrary.compile_blueprint(blueprint)
crate_class = blueprint.generated_class()
cdo = u.get_default_object(crate_class)
cdo.static_mesh_component.set_static_mesh(mesh)
cdo.static_mesh_component.set_material(0, material)
u.BlueprintEditorLibrary.compile_blueprint(blueprint)
assert u.EditorAssetLibrary.save_loaded_asset(blueprint)
crates = []
for index in range(50):
    actor = actors.spawn_actor_from_class(u.StaticMeshActor, u.Vector(index % 10 * 200, index // 10 * 200, 0))
    actor.static_mesh_component.set_static_mesh(mesh)
    actor.static_mesh_component.set_material(0, material)
    actor.set_actor_label('Crate' + str(index))
    crates.append(actor)
for label in ['North', 'South']:
    parent = actors.spawn_actor_from_class(u.StaticMeshActor, u.Vector())
    parent.set_actor_label(label)
    child = actors.spawn_actor_from_class(u.StaticMeshActor, u.Vector())
    child.set_actor_label('DuplicateDisplayName')
    assert child.attach_to_actor(parent, '', u.AttachmentRule.KEEP_WORLD, u.AttachmentRule.KEEP_WORLD, u.AttachmentRule.KEEP_WORLD, False)
spawn = actors.spawn_actor_from_class(u.PlayerStart, u.Vector(0, 0, 200))
spawn.set_actor_label('SpawnMarker')
# A native audio asset, not a JSON stand-in.
import_task = u.AssetImportTask()
import_task.set_editor_property('filename', str(project / 'SourceContent' / 'Tone.wav'))
import_task.set_editor_property('destination_path', '/Game')
import_task.set_editor_property('automated', True)
import_task.set_editor_property('save', True)
assets.import_asset_tasks([import_task])
assert import_task.imported_object_paths
sequence = assets.create_asset('Move', '/Game', u.LevelSequence, u.LevelSequenceFactoryNew())
sequence.set_playback_start(0)
sequence.set_playback_end(30)
binding = sequence.add_possessable(crates[0])
track = binding.add_track(u.MovieScene3DTransformTrack)
section = track.add_section()
section.set_range(0, 30)
channels = section.get_all_channels()
assert len(channels) >= 3
channels[0].add_key(u.FrameNumber(0), 0.0)
channels[0].add_key(u.FrameNumber(30), 100.0)
# An intentionally opaque Blueprint dependency. No claim of translated script.
critical_factory = u.BlueprintFactory()
critical_factory.set_editor_property('parent_class', u.Actor)
critical = assets.create_asset('UnsupportedCritical', '/Game', u.Blueprint, critical_factory)
u.BlueprintEditorLibrary.compile_blueprint(critical)
actors.spawn_actor_from_class(critical.generated_class(), u.Vector()).set_actor_label('UnsupportedCritical')
assert u.EditorAssetLibrary.save_directory('/Game', only_if_is_dirty=False, recursive=True)
assert levels.save_current_level()
assert levels.new_level('/Game/Annex')
for i in range(2):
    actors.spawn_actor_from_class(crate_class, u.Vector(i * 200, 0, 0)).set_actor_label('PrefabInstance' + str(i))
assert levels.save_current_level()
report = dict(ok=True, phase='independent native creation only', authored_static_mesh_objects=50, prefab_instances=2,
    scenes=['Content/World.umap', 'Content/Annex.umap'], prefab='Content/Crate.uasset',
    animation='Content/Move.uasset', audio=list(import_task.imported_object_paths),
    unsupported_dependency='Content/UnsupportedCritical.uasset', xace_enrolled=False,
    adoption_verified=False, supported_behavior_mapping_verified=False,
    license='Original arrangement and tone; mesh/material derived from installed Unreal Engine basic content, subject to Unreal license; no public redistribution certification',
    engine=u.SystemLibrary.get_engine_version())
(project / 'fixture-created.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
