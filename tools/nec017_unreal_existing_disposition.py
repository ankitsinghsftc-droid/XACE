"""Explicit test-owner disposition in a fresh fixture COPY; never automatic import."""
from pathlib import Path
import json
import unreal as u
levels=u.get_editor_subsystem(u.LevelEditorSubsystem);actors=u.get_editor_subsystem(u.EditorActorSubsystem)
assert levels.load_level('/Game/World')
changes=[]
for actor in actors.get_all_level_actors():
 label=actor.get_actor_label()
 if label in ['SpawnMarker','UnsupportedCritical']:
  changes.append(dict(actor=label,action='remove_native_authority_in_copy',native_class=actor.get_class().get_path_name()))
  assert actors.destroy_actor(actor)
 elif actor.get_class()==u.StaticMeshActor.static_class():
  comp=actor.static_mesh_component;before=str(comp.get_collision_enabled())
  actor.modify();comp.modify()
  comp.set_collision_profile_name("NoCollision")
  comp.set_collision_enabled(u.CollisionEnabled.NO_COLLISION)
  changes.append(dict(actor=label,action='disable_native_collision_in_copy',before=before,after=str(comp.get_collision_enabled())))
assert len(changes)==56
assert levels.save_current_level()
(Path(u.Paths.project_dir())/'explicit-disposition.json').write_text(json.dumps(dict(ok=True,changes=changes,automatic_gameplay_conversion=False,geometry_behavior_preserved=False),indent=2),encoding='utf-8')
