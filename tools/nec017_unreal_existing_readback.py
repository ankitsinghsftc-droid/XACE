"""Cold native readback of the independently authored Unreal fixture."""
from pathlib import Path
import json
import unreal as u
u.load_module('BinkAudioDecoder')
project=Path(u.Paths.project_dir())
levels=u.get_editor_subsystem(u.LevelEditorSubsystem)
actors=u.get_editor_subsystem(u.EditorActorSubsystem)
assert levels.load_level('/Game/World')
all_actors=actors.get_all_level_actors()
crates=[a for a in all_actors if a.get_actor_label() in ['Crate'+str(i) for i in range(50)]]
assert len(crates)==50
for actor in crates:
 assert actor.get_class()==u.StaticMeshActor.static_class()
 n=int(actor.get_actor_label()[5:]);position=actor.get_actor_location()
 assert (position.x,position.y,position.z)==(n%10*200,n//10*200,0)
 component=actor.static_mesh_component
 assert component.static_mesh.get_path_name()=='/Game/CrateMesh.CrateMesh'
 assert component.get_material(0).get_path_name()=='/Game/CrateMaterial.CrateMaterial'
duplicates=[a for a in all_actors if a.get_actor_label()=='DuplicateDisplayName']
assert len(duplicates)==2
assert sorted(a.get_attach_parent_actor().get_actor_label() for a in duplicates)==['North','South']
assert any(a.get_actor_label()=='SpawnMarker' and isinstance(a,u.PlayerStart) for a in all_actors)
assert any(a.get_actor_label()=='UnsupportedCritical' for a in all_actors)
sequence=u.load_asset('/Game/Move');bindings=sequence.get_bindings();assert len(bindings)==1
tracks=bindings[0].get_tracks();assert len(tracks)==1
channels=tracks[0].get_sections()[0].get_all_channels();keys=channels[0].get_keys()
assert len(keys)==2 and [k.get_value() for k in keys]==[0.0,100.0]
sound=u.load_asset('/Game/Tone');assert isinstance(sound,u.SoundWave)
assert levels.load_level('/Game/Annex')
instances=[a for a in actors.get_all_level_actors() if a.get_actor_label().startswith('PrefabInstance')]
assert len(instances)==2
assert all(a.get_class().get_path_name()=='/Game/Crate.Crate_C' for a in instances)
assert all(a.static_mesh_component.static_mesh.get_path_name()=='/Game/CrateMesh.CrateMesh' for a in instances)
(project/'cold-readback.json').write_text(json.dumps(dict(ok=True,static_mesh_objects=50,prefab_instances=2,scenes=2,native_mesh_material=True,duplicate_labels_and_parentage=True,animation_keyframes=True,audio_resource=True,spawn_marker=True,critical_dependency=True,xace_enrolled=False,adoption_verified=False),indent=2),encoding='utf-8')
