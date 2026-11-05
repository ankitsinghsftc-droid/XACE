from pathlib import Path
import json
import unreal as u
levels=u.get_editor_subsystem(u.LevelEditorSubsystem);actors=u.get_editor_subsystem(u.EditorActorSubsystem)
assert levels.load_level('/Game/World')
rows=actors.get_all_level_actors()
assert not any(a.get_actor_label() in ['SpawnMarker','UnsupportedCritical'] for a in rows)
meshes=[a for a in rows if a.get_class()==u.StaticMeshActor.static_class()]
assert len(meshes)==54
assert all(a.static_mesh_component.get_collision_enabled()==u.CollisionEnabled.NO_COLLISION for a in meshes)
(Path(u.Paths.project_dir())/'disposition-cold.json').write_text(json.dumps(dict(ok=True,cold_native_collision_disabled=54,removed_native_authority_actors=2)),encoding='utf-8')
