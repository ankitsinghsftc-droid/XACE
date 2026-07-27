use std::fs;
use std::path::PathBuf;

use xace_runtime_core::runtime_orchestrator::RuntimeOrchestrator;
use xace_save_engine::{compute_asset_tree_hash, FileSaveEngine};

const TEST_CGS_HASH: &str = "9999999999999999999999999999999999999999999999999999999999999999";

fn temp_root(name: &str) -> PathBuf {
    let root = std::env::temp_dir().join(format!(
        "xace_runtime_checkpoint_{}_{}",
        name,
        std::process::id()
    ));
    let _ = fs::remove_dir_all(&root);
    root
}

fn tick_n(runtime: &mut RuntimeOrchestrator, ticks: usize) {
    for _ in 0..ticks {
        runtime.tick().unwrap();
    }
}

#[test]
fn runtime_checkpoint_save_load_replay_preserves_world_hash() {
    let save_root = temp_root("replay");
    fs::create_dir_all(&save_root).unwrap();
    let cgs_path = save_root.join("game.cgs.json");
    fs::write(&cgs_path, supported_runtime_cgs()).unwrap();
    write_persisted_sgc_plan(&save_root, TEST_CGS_HASH);
    let asset_root = save_root.join("assets");
    fs::create_dir_all(asset_root.join("mesh")).unwrap();
    fs::write(
        asset_root.join("mesh").join("runtime_cube.mesh"),
        b"cube-v1",
    )
    .unwrap();
    let expected_asset_hash = compute_asset_tree_hash(&asset_root).unwrap();
    let save_engine = FileSaveEngine::new(&save_root, "0.1.0");

    let mut original = RuntimeOrchestrator::initialise(&cgs_path).unwrap();
    tick_n(&mut original, 6);
    let checkpoint = original.world_snapshot().unwrap();
    save_engine
        .save_project_session(
            "slot_runtime",
            "Runtime Checkpoint",
            &checkpoint,
            &asset_root,
        )
        .unwrap();

    tick_n(&mut original, 6);
    let original_final_hash = original.world_snapshot().unwrap().world_hash;

    let loaded = save_engine.load_session("slot_runtime").unwrap();
    assert_eq!(loaded.tick, checkpoint.tick);
    assert_eq!(loaded.cgs_hash, checkpoint.cgs_hash);
    assert_eq!(loaded.world_hash, checkpoint.world_hash);

    let mut replayed = RuntimeOrchestrator::initialise(&cgs_path).unwrap();
    replayed.restore_world_snapshot(&loaded).unwrap();
    tick_n(&mut replayed, 6);
    let replayed_final_hash = replayed.world_snapshot().unwrap().world_hash;

    assert_eq!(replayed_final_hash, original_final_hash);

    let slots = save_engine.list_slots().unwrap();
    assert_eq!(slots.len(), 1);
    assert_eq!(slots[0].slot_id, "slot_runtime");
    assert_eq!(slots[0].tick, checkpoint.tick);
    assert_eq!(slots[0].cgs_hash, checkpoint.cgs_hash);
    assert_eq!(slots[0].asset_hash, expected_asset_hash);
    assert_eq!(
        save_engine
            .load_metadata("slot_runtime")
            .unwrap()
            .asset_hash,
        expected_asset_hash
    );

    let _ = fs::remove_dir_all(save_root);
}

fn supported_runtime_cgs() -> String {
    r#"
    {
      "metadata": {
        "name": "Runtime Checkpoint Test",
        "schema_version": "0.1.0",
        "version": "0.1.0",
        "execution_plan_version": 1,
        "cgs_hash": "__TEST_CGS_HASH__"
      },
      "global_systems": [
        {
          "id": "MovementSystem",
          "phase": "Simulation",
          "reads": [1, 5],
          "writes": [1],
          "depends_on": [],
          "deterministic": true
        }
      ],
      "modes": [
        {
          "id": "default",
          "schema_version": "0.1.0",
          "is_default": true,
          "actors": [
            {
              "id": "player",
              "spawn_count": 1,
              "components": [
                {"type_id": 1, "name": "COMP_TRANSFORM_V1", "defaults": {"position_x": 0, "position_y": 0, "position_z": 0}},
                {"type_id": 2, "name": "COMP_IDENTITY_V1", "defaults": {"name": "player"}},
                {"type_id": 5, "name": "COMP_VELOCITY_V1", "defaults": {"vx": 1, "vy": 0, "vz": 0}}
              ]
            }
          ],
          "systems": [],
          "rules": []
        }
      ]
    }
    "#
    .replace("__TEST_CGS_HASH__", TEST_CGS_HASH)
}

fn write_persisted_sgc_plan(root: &std::path::Path, cgs_hash: &str) {
    let plan_dir = root.join(".xace").join("execution_plans");
    fs::create_dir_all(&plan_dir).unwrap();
    fs::write(
        plan_dir.join(format!("{cgs_hash}.plan.json")),
        persisted_sgc_plan(cgs_hash),
    )
    .unwrap();
}

fn persisted_sgc_plan(cgs_hash: &str) -> String {
    format!(
        r#"{{
          "schema_version": "0.1.0",
          "plan_version": 1,
          "adapter_protocol_version": 1,
          "migration_status": "current",
          "created_tick": 0,
          "plan_hash": "{}",
          "compiled_from_cgs_hash": "{}",
          "all_system_ids": ["MovementSystem"],
          "phases": {{
            "2": {{
              "phase": "Simulation",
              "groups": [
                {{
                  "group_id": "Simulation_group_0",
                  "phase": "Simulation",
                  "parallel": false,
                  "systems": ["MovementSystem"],
                  "serialization_constraints": [],
                  "execution_index": 0
                }}
              ],
              "total_system_count": 1
            }}
          }},
          "component_access_sets": {{
            "schema": "xace.sgc.component_access_sets.v1",
            "by_system": {{
              "MovementSystem": {{"reads": [1, 5], "writes": [1]}}
            }},
            "all_reads": [1, 5],
            "all_writes": [1],
            "component_ids": [1, 5]
          }},
          "system_metadata": {{
            "schema": "xace.sgc.system_metadata.v1",
            "systems": {{
              "MovementSystem": {{"display_name": "Movement System", "phase": "Simulation", "depends_on": [], "deterministic": true, "version": {{"major": 1, "minor": 0}}, "description": ""}}
            }}
          }},
          "proof_bundle": {{
            "schema": "xace.sgc.proof_ref.v1",
            "path": ".xace/proof/sgc/{}",
            "compiled_from_cgs_hash": "{}",
            "plan_hash": "{}",
            "input_hash": "{}",
            "validation_hash": "{}"
          }}
        }}"#,
        "d".repeat(64),
        cgs_hash,
        cgs_hash,
        cgs_hash,
        "d".repeat(64),
        "1".repeat(64),
        "2".repeat(64)
    )
}
