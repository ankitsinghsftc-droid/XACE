//! # Event Subscription Registry
//!
//! Maps systems to the event types they want to receive.
//! Subscriptions are static — declared at startup from the
//! ExecutionPlan. No dynamic subscription during simulation (I4).
//!
//! ## Determinism (D5)
//! Subscriptions are stored in BTreeMap for deterministic
//! iteration order when routing events to subscribers.

use std::collections::BTreeMap;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_type::EventType;

// ── Event Subscription Registry ───────────────────────────────────────────────

/// Static registry of system event subscriptions.
///
/// Built once at runtime initialization. Never modified
/// during simulation — subscriptions are fixed (I4).
pub struct EventSubscriptionRegistry {
    /// system_id → set of subscribed EventTypes
    /// BTreeMap for deterministic iteration order (D11).
    subscriptions: BTreeMap<String, Vec<EventType>>,
}

impl EventSubscriptionRegistry {
    pub fn new() -> Self {
        Self {
            subscriptions: BTreeMap::new(),
        }
    }

    /// Registers a system's event subscriptions.
    ///
    /// Returns error if the system is already registered.
    /// Each system registers once at startup.
    pub fn register(
        &mut self,
        system_id: impl Into<String>,
        event_types: Vec<EventType>,
    ) -> Result<(), XaceError> {
        let id = system_id.into();
        if self.subscriptions.contains_key(&id) {
            return Err(XaceError::ValidationFailure {
                message: format!("System '{}' already has event subscriptions registered", id),
                context: ErrorContext::new("EventSubscriptionRegistry", "register"),
                rule_violated: "I4".into(),
                failed_path: format!("system:{}", id),
            });
        }
        self.subscriptions.insert(id, event_types);
        Ok(())
    }

    /// Returns all system IDs subscribed to the given event type.
    /// Result sorted alphabetically for deterministic routing (D11).
    pub fn subscribers_for(&self, event_type: &EventType) -> Vec<&str> {
        let mut result: Vec<&str> = self
            .subscriptions
            .iter()
            .filter(|(_, types)| types.contains(event_type))
            .map(|(id, _)| id.as_str())
            .collect();
        result.sort(); // Deterministic order (D11)
        result
    }

    /// Returns the event types a system is subscribed to.
    pub fn subscriptions_for(&self, system_id: &str) -> &[EventType] {
        self.subscriptions
            .get(system_id)
            .map(|v| v.as_slice())
            .unwrap_or(&[])
    }

    /// Returns true if the system is subscribed to the event type.
    pub fn is_subscribed(&self, system_id: &str, event_type: &EventType) -> bool {
        self.subscriptions
            .get(system_id)
            .map(|types| types.contains(event_type))
            .unwrap_or(false)
    }

    /// Returns the total number of registered systems.
    pub fn system_count(&self) -> usize {
        self.subscriptions.len()
    }
}

impl Default for EventSubscriptionRegistry {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn register_and_query() {
        let mut reg = EventSubscriptionRegistry::new();
        reg.register("sys_combat", vec![EventType::DamageTaken])
            .unwrap();
        assert!(reg.is_subscribed("sys_combat", &EventType::DamageTaken));
        assert!(!reg.is_subscribed("sys_combat", &EventType::EntitySpawned));
    }

    #[test]
    fn subscribers_for_returns_sorted() {
        let mut reg = EventSubscriptionRegistry::new();
        reg.register("sys_z", vec![EventType::DamageTaken]).unwrap();
        reg.register("sys_a", vec![EventType::DamageTaken]).unwrap();
        reg.register("sys_m", vec![EventType::DamageTaken]).unwrap();
        let subs = reg.subscribers_for(&EventType::DamageTaken);
        assert_eq!(subs, vec!["sys_a", "sys_m", "sys_z"]);
    }

    #[test]
    fn duplicate_registration_fails() {
        let mut reg = EventSubscriptionRegistry::new();
        reg.register("sys_combat", vec![EventType::DamageTaken])
            .unwrap();
        assert!(reg
            .register("sys_combat", vec![EventType::EntitySpawned])
            .is_err());
    }

    #[test]
    fn unsubscribed_system_returns_empty() {
        let reg = EventSubscriptionRegistry::new();
        assert_eq!(reg.subscriptions_for("sys_unknown").len(), 0);
    }

    #[test]
    fn no_subscribers_returns_empty() {
        let reg = EventSubscriptionRegistry::new();
        let subs = reg.subscribers_for(&EventType::DamageTaken);
        assert!(subs.is_empty());
    }
}
