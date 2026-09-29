//! External input can enter component state only through this scheduled system.
use crate::cgs_loader::{type_ids, RuntimeSchedulePlan};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::{ErrorContext, XaceError};

pub const SYSTEM_ID: &str = "EngineInputSystem";
pub type PendingInput = Arc<Mutex<BTreeMap<u64, String>>>;

pub struct EngineInputSystem(pub PendingInput);
impl ISystem for EngineInputSystem {
    fn system_id(&self) -> &str {
        SYSTEM_ID
    }
    fn declared_reads(&self) -> &[u32] {
        &[]
    }
    fn declared_writes(&self) -> &[u32] {
        &[type_ids::INPUT]
    }
    fn execute(&self, ctx: &mut dyn ISystemContext) -> Result<(), XaceError> {
        let pending = self.0.lock().map_err(|_| XaceError::ValidationFailure {
            message: "input staging lock poisoned".into(),
            context: ErrorContext::new(SYSTEM_ID, "execute"),
            rule_violated: "input_staging".into(),
            failed_path: SYSTEM_ID.into(),
        })?;
        // The queue remains intact until tick success/reset. The gate owns writes.
        for (&entity, value) in pending.iter() {
            ctx.submit_mutation(entity, type_ids::INPUT, value.clone())?;
        }
        Ok(())
    }
}

/// Ingress must be an explicit singleton first Input group, never runtime-inserted.
pub fn validate_schedule(plan: &RuntimeSchedulePlan) -> Result<bool, String> {
    let ingress: Vec<_> = plan
        .groups
        .iter()
        .filter(|g| g.systems.iter().any(|s| s == SYSTEM_ID))
        .collect();
    if ingress.is_empty() {
        return Ok(false);
    }
    let group = ingress[0];
    let first_input = plan.groups.iter().find(|g| g.phase == "Input");
    let access = plan.system_access.get(SYSTEM_ID);
    if ingress.len() != 1
        || group.phase != "Input"
        || group.parallel
        || group.systems.len() != 1
        || first_input != Some(group)
        || !access.is_some_and(|a| a.reads.is_empty() && a.writes == vec![type_ids::INPUT])
    {
        return Err("EngineInputSystem must be the first singleton sequential Input group with reads=[] and writes=[6]; recompile the CGS through Factory/SGC".into());
    }
    Ok(true)
}
