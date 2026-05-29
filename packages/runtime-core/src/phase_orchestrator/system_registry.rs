//! # System Registry
//!
//! Stores and retrieves ISystem implementations by system ID.
//! The PhaseOrchestrator looks up systems here during tick execution.
//!
//! ## Design
//! Systems are registered at runtime initialization from the compiled
//! schema package. Once registered, the set of systems is fixed for
//! the lifetime of the ExecutionPlan. No dynamic system registration
//! during simulation.
//!
//! ## Determinism (D1)
//! System execution order is defined only by the ExecutionPlan.
//! The SystemRegistry stores systems but never decides order.
//! Order comes entirely from the ExecutionPlan passed to the
//! PhaseOrchestrator at tick start.

use std::collections::BTreeMap;
use xace_core::contracts::interfaces::ISystem;
use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── System Registry ───────────────────────────────────────────────────────────

/// Registry of all ISystem implementations available at runtime.
///
/// Systems are registered by system_id (string) during initialization.
/// The PhaseOrchestrator looks up systems by ID from the ExecutionPlan.
///
/// BTreeMap for deterministic iteration order (D11).
pub struct SystemRegistry {
    /// system_id → Box<dyn ISystem>
    /// BTreeMap guarantees alphabetical system_id ordering (D11).
    systems: BTreeMap<String, Box<dyn ISystem>>,
}

impl SystemRegistry {
    pub fn new() -> Self {
        Self {
            systems: BTreeMap::new(),
        }
    }

    /// Registers a system implementation.
    ///
    /// Returns error if a system with the same ID is already registered.
    /// System IDs must be unique — duplicate IDs indicate a bug in the
    /// schema compilation pipeline.
    pub fn register(&mut self, system: Box<dyn ISystem>) -> Result<(), XaceError> {
        let id = system.system_id().to_string();
        if self.systems.contains_key(&id) {
            return Err(XaceError::ValidationFailure {
                message: format!(
                    "System '{}' is already registered — duplicate system IDs \
                     are not allowed",
                    id
                ),
                context: ErrorContext::new("SystemRegistry", "register"),
                rule_violated: "no_duplicate_systems".into(),
                failed_path: format!("system:{}", id),
            });
        }
        self.systems.insert(id, system);
        Ok(())
    }

    /// Returns a reference to the system with the given ID.
    /// Returns None if no system with that ID is registered.
    pub fn get(&self, system_id: &str) -> Option<&dyn ISystem> {
        self.systems.get(system_id).map(|s| s.as_ref())
    }

    /// Returns true if a system with the given ID is registered.
    pub fn has_system(&self, system_id: &str) -> bool {
        self.systems.contains_key(system_id)
    }

    /// Returns the number of registered systems.
    pub fn system_count(&self) -> usize {
        self.systems.len()
    }

    /// Returns all registered system IDs sorted alphabetically (D11).
    pub fn all_system_ids(&self) -> Vec<&str> {
        self.systems.keys().map(|s| s.as_str()).collect()
    }

    /// Validates that all system IDs in the given list are registered.
    ///
    /// Called by the PhaseOrchestrator before executing an ExecutionPlan
    /// to ensure all required systems are available.
    pub fn validate_execution_plan_systems(&self, system_ids: &[&str]) -> Result<(), XaceError> {
        for &system_id in system_ids {
            if !self.has_system(system_id) {
                return Err(XaceError::ValidationFailure {
                    message: format!(
                        "ExecutionPlan references system '{}' which is not \
                         registered in SystemRegistry — ensure all systems \
                         are registered before execution",
                        system_id
                    ),
                    context: ErrorContext::new("SystemRegistry", "validate_execution_plan_systems"),
                    rule_violated: "D1".into(),
                    failed_path: format!("system:{}", system_id),
                });
            }
        }
        Ok(())
    }
}

impl Default for SystemRegistry {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::contracts::interfaces::ISystemContext;

    struct MockSystem {
        id: String,
        reads: Vec<u32>,
        writes: Vec<u32>,
    }

    impl ISystem for MockSystem {
        fn system_id(&self) -> &str {
            &self.id
        }
        fn execute(&self, _: &mut dyn ISystemContext) -> Result<(), XaceError> {
            Ok(())
        }
        fn declared_reads(&self) -> &[u32] {
            &self.reads
        }
        fn declared_writes(&self) -> &[u32] {
            &self.writes
        }
    }

    fn mock_system(id: &str) -> Box<dyn ISystem> {
        Box::new(MockSystem {
            id: id.to_string(),
            reads: vec![],
            writes: vec![],
        })
    }

    #[test]
    fn register_and_get() {
        let mut reg = SystemRegistry::new();
        reg.register(mock_system("sys_movement")).unwrap();
        assert!(reg.get("sys_movement").is_some());
        assert_eq!(reg.get("sys_movement").unwrap().system_id(), "sys_movement");
    }

    #[test]
    fn duplicate_registration_fails() {
        let mut reg = SystemRegistry::new();
        reg.register(mock_system("sys_movement")).unwrap();
        assert!(reg.register(mock_system("sys_movement")).is_err());
    }

    #[test]
    fn get_nonexistent_returns_none() {
        let reg = SystemRegistry::new();
        assert!(reg.get("sys_nonexistent").is_none());
    }

    #[test]
    fn all_system_ids_sorted() {
        let mut reg = SystemRegistry::new();
        reg.register(mock_system("sys_movement")).unwrap();
        reg.register(mock_system("sys_ai")).unwrap();
        reg.register(mock_system("sys_damage")).unwrap();
        let ids = reg.all_system_ids();
        assert_eq!(ids, vec!["sys_ai", "sys_damage", "sys_movement"]);
    }

    #[test]
    fn validate_plan_systems_all_registered() {
        let mut reg = SystemRegistry::new();
        reg.register(mock_system("sys_a")).unwrap();
        reg.register(mock_system("sys_b")).unwrap();
        assert!(reg
            .validate_execution_plan_systems(&["sys_a", "sys_b"])
            .is_ok());
    }

    #[test]
    fn validate_plan_systems_missing_fails() {
        let mut reg = SystemRegistry::new();
        reg.register(mock_system("sys_a")).unwrap();
        assert!(reg
            .validate_execution_plan_systems(&["sys_a", "sys_missing"])
            .is_err());
    }

    #[test]
    fn system_count_correct() {
        let mut reg = SystemRegistry::new();
        assert_eq!(reg.system_count(), 0);
        reg.register(mock_system("sys_a")).unwrap();
        reg.register(mock_system("sys_b")).unwrap();
        assert_eq!(reg.system_count(), 2);
    }
}
