//! Verify and bind immutable compiled world artifacts before the first tick.
use crate::{cgs_loader::SpawnSummary, query_engine::QueryEngine};
use anyhow::{bail, Result};
use std::{collections::BTreeMap, path::Path};
use xace_core::{
    wire::session_contract::ContractId,
    world::{v3::WorldContractV3, WorldContract, WorldManifest},
};

pub fn bind_compiled_world(
    world_path: &Path,
    manifest_path: &Path,
    summary: &SpawnSummary,
    queries: &mut QueryEngine,
) -> Result<()> {
    for path in [world_path, manifest_path] {
        if std::fs::metadata(path)?.len() > 16 * 1024 * 1024 {
            bail!("world artifact exceeds size limit");
        }
    }
    let bytes = std::fs::read(world_path)?;
    let manifest: WorldManifest = serde_json::from_slice(&std::fs::read(manifest_path)?)?;
    let hash = summary
        .cgs_hash
        .clone()
        .try_into()
        .map_err(anyhow::Error::msg)?;
    let version = summary
        .schema_version
        .clone()
        .try_into()
        .map_err(anyhow::Error::msg)?;
    let mode: ContractId = summary
        .mode_id
        .clone()
        .try_into()
        .map_err(anyhow::Error::msg)?;
    if manifest.world.mode_id != mode {
        bail!("world differs from active mode");
    }
    match manifest.world.contract_version {
        2 => {
            let world = WorldContract::from_bytes(&bytes).map_err(anyhow::Error::msg)?;
            manifest
                .verify(&world, &hash, &version)
                .map_err(anyhow::Error::msg)?;
            let mut actors = BTreeMap::new();
            for object in &world.objects {
                let actor = summary
                    .spawned_actors
                    .iter()
                    .find(|a| a.actor_id == String::from(object.actor_id.clone()))
                    .ok_or_else(|| anyhow::anyhow!("missing world actor"))?;
                if actor.entity_ids.len() != 1 {
                    bail!("legacy world requires one actor instance");
                }
                actors.insert(object.actor_id.clone(), actor.entity_ids[0]);
            }
            queries
                .bind_world_geometry(&world, &actors)
                .map_err(|e| anyhow::anyhow!("{e}"))?;
        }
        3 => {
            let world = WorldContractV3::from_bytes(&bytes).map_err(anyhow::Error::msg)?;
            world
                .verify_manifest(&manifest, &hash, &version)
                .map_err(anyhow::Error::msg)?;
            let mut instances = BTreeMap::new();
            for actor in &summary.spawned_actors {
                let id: ContractId = actor
                    .actor_id
                    .clone()
                    .try_into()
                    .map_err(anyhow::Error::msg)?;
                for (index, entity) in actor.entity_ids.iter().enumerate() {
                    instances.insert((id.clone(), index as u32), *entity);
                }
            }
            queries
                .bind_world_v3(&world, &instances)
                .map_err(|e| anyhow::anyhow!("{e}"))?;
        }
        _ => bail!("unsupported compiled world version"),
    }
    Ok(())
}
