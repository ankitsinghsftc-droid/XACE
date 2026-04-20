//! # Event Type
//!
//! Defines the complete enumeration of all event types that can flow
//! through the XACE EventBus. Every event emitted by any system must
//! be one of these types — no anonymous or untyped events allowed.
//!
//! ## Why a Central Event Type Registry
//! The SGC uses event type declarations to validate system subscriptions
//! at compile time. A system that subscribes to an event type must
//! declare that subscription in its SystemDefinition. The SGC checks
//! that no system subscribes to an event type that no other system emits.
//!
//! ## Domain Events
//! UCL-level events are defined directly in this enum.
//! DCL domain events use the Domain(String) variant to avoid
//! coupling this core type to optional domain packages.
//! Example: Domain("combat.damage_applied"), Domain("animation.event_fired")
//!
//! ## Determinism (D5)
//! Events are sorted by (creation_tick ASC, creation_phase ASC, event_id ASC)
//! before dispatch. The EventType itself never affects sort order —
//! only the three sort key fields matter for determinism.

use serde::{Deserialize, Serialize};

// ── Event Type ────────────────────────────────────────────────────────────────

/// All event types that can flow through the XACE EventBus.
///
/// Systems subscribe to specific event types in their SystemDefinition.
/// The EventDispatcher routes events to subscribed systems based on type.
/// No dynamic subscription is allowed — all subscriptions are declared
/// in the CGS and frozen into the ExecutionPlan (I4).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum EventType {
    // ── Entity Lifecycle ──────────────────────────────────────────────────
    /// A new entity was spawned into the world this tick.
    /// Emitted by the SpawnSystem after Mutation Gate processes spawn.
    EntitySpawned,

    /// An entity was destroyed this tick.
    /// Emitted by the DestroySystem after Mutation Gate processes destroy.
    EntityDestroyed,

    /// An entity transitioned between Active and Disabled states.
    /// Payload: entity_id, previous_state, new_state.
    EntityStateChanged,

    /// An entity's tags were modified.
    /// Payload: entity_id, added_tags, removed_tags.
    EntityTagsChanged,

    // ── Input Events ──────────────────────────────────────────────────────
    /// A player triggered a named game action this tick.
    /// Payload: controller_id, action_name, intensity (0.0-1.0).
    PlayerActionTriggered,

    /// Input was enabled or disabled on a controlled entity.
    /// Payload: entity_id, is_enabled.
    InputStateChanged,

    /// A new input packet arrived from the network (Phase 15).
    /// Payload: peer_id, tick, action_count.
    NetworkInputReceived,

    // ── Physics Events ────────────────────────────────────────────────────
    /// Two entities began overlapping via trigger colliders.
    /// Payload: trigger_entity_id, entering_entity_id.
    TriggerEntered,

    /// An entity stopped overlapping a trigger collider.
    /// Payload: trigger_entity_id, exiting_entity_id.
    TriggerExited,

    /// Two solid colliders made contact.
    /// Payload: entity_a_id, entity_b_id, contact_point_json.
    CollisionStarted,

    /// Two solid colliders separated.
    /// Payload: entity_a_id, entity_b_id.
    CollisionEnded,

    // ── Game State Events ─────────────────────────────────────────────────
    /// The game phase changed (Initializing → Playing, Playing → GameOver, etc.)
    /// Payload: previous_phase, new_phase.
    GamePhaseChanged,

    /// The match state changed (Idle → Countdown → Active, etc.)
    /// Payload: previous_match_state, new_match_state.
    MatchStateChanged,

    /// A score value changed.
    /// Payload: delta, new_total, reason.
    ScoreChanged,

    /// A match or round ended.
    /// Payload: winning_entity_id (or empty for draw), final_score.
    MatchEnded,

    /// The active game mode changed.
    /// Payload: previous_mode_id, new_mode_id.
    GameModeChanged,

    // ── Spawner Events ────────────────────────────────────────────────────
    /// A spawner entity created a new entity.
    /// Payload: spawner_entity_id, spawned_entity_id, actor_id.
    EntitySpawnedBySpawner,

    /// A spawner reached its maximum entity count.
    /// Payload: spawner_entity_id, max_count.
    SpawnerCapacityReached,

    // ── Lifetime Events ───────────────────────────────────────────────────
    /// An entity's COMP_LIFETIME_V1 expired.
    /// Payload: entity_id, on_expire_action.
    LifetimeExpired,

    // ── Schema / Runtime Events ───────────────────────────────────────────
    /// A MutationTransaction was successfully committed to the CGS.
    /// Payload: transaction_id, usmc_category, required_recompile.
    SchemaMutationApplied,

    /// A WorldSnapshot was taken.
    /// Payload: tick, world_hash.
    SnapshotTaken,

    /// A WorldSnapshot was restored.
    /// Payload: restored_tick, world_hash.
    SnapshotRestored,

    /// The ExecutionPlan was recompiled by the SGC.
    /// Payload: old_plan_version, new_plan_version.
    ExecutionPlanRecompiled,

    // ── Network Events (Phase 15) ─────────────────────────────────────────
    /// A network peer connected to the session.
    /// Payload: peer_id, peer_display_name.
    PeerConnected,

    /// A network peer disconnected from the session.
    /// Payload: peer_id, reason.
    PeerDisconnected,

    /// A desync was detected between peers.
    /// Payload: tick, local_hash, remote_hash.
    DesyncDetected,

    // ── Domain Events (DCL / GCL) ─────────────────────────────────────────
    /// A domain-specific event from a DCL or GCL system.
    ///
    /// Used by all DCL domains to emit events without coupling
    /// this core type to optional domain packages.
    ///
    /// Convention for domain event names:
    /// "{domain}.{event_name}"
    ///
    /// Examples:
    /// - "combat.damage_applied"
    /// - "combat.entity_died"
    /// - "animation.event_fired"
    /// - "animation.state_changed"
    /// - "audio.clip_complete"
    /// - "interaction.dialogue_started"
    /// - "rpg.level_up"
    /// - "rpg.item_picked_up"
    /// - "ai.target_acquired"
    /// - "ai.patrol_completed"
    Domain(String),
}

impl EventType {
    /// Returns true if this event type relates to entity lifecycle.
    pub fn is_lifecycle_event(&self) -> bool {
        matches!(
            self,
            EventType::EntitySpawned
                | EventType::EntityDestroyed
                | EventType::EntityStateChanged
                | EventType::EntityTagsChanged
        )
    }

    /// Returns true if this event type relates to physics or collision.
    pub fn is_physics_event(&self) -> bool {
        matches!(
            self,
            EventType::TriggerEntered
                | EventType::TriggerExited
                | EventType::CollisionStarted
                | EventType::CollisionEnded
        )
    }

    /// Returns true if this event type relates to game state.
    pub fn is_game_state_event(&self) -> bool {
        matches!(
            self,
            EventType::GamePhaseChanged
                | EventType::MatchStateChanged
                | EventType::ScoreChanged
                | EventType::MatchEnded
                | EventType::GameModeChanged
        )
    }

    /// Returns true if this is a domain event from DCL or GCL.
    pub fn is_domain_event(&self) -> bool {
        matches!(self, EventType::Domain(_))
    }

    /// Returns true if this event type relates to network state.
    pub fn is_network_event(&self) -> bool {
        matches!(
            self,
            EventType::PeerConnected
                | EventType::PeerDisconnected
                | EventType::DesyncDetected
                | EventType::NetworkInputReceived
        )
    }

    /// Returns the domain prefix for Domain events.
    /// Returns None for non-domain events.
    /// Example: Domain("combat.damage_applied") → Some("combat")
    pub fn domain_prefix(&self) -> Option<&str> {
        if let EventType::Domain(name) = self {
            name.split('.').next()
        } else {
            None
        }
    }

    /// Returns a canonical string name for this event type.
    /// Used for logging, debugging, and NLTL translation.
    pub fn name(&self) -> String {
        match self {
            EventType::EntitySpawned => "EntitySpawned".into(),
            EventType::EntityDestroyed => "EntityDestroyed".into(),
            EventType::EntityStateChanged => "EntityStateChanged".into(),
            EventType::EntityTagsChanged => "EntityTagsChanged".into(),
            EventType::PlayerActionTriggered => "PlayerActionTriggered".into(),
            EventType::InputStateChanged => "InputStateChanged".into(),
            EventType::NetworkInputReceived => "NetworkInputReceived".into(),
            EventType::TriggerEntered => "TriggerEntered".into(),
            EventType::TriggerExited => "TriggerExited".into(),
            EventType::CollisionStarted => "CollisionStarted".into(),
            EventType::CollisionEnded => "CollisionEnded".into(),
            EventType::GamePhaseChanged => "GamePhaseChanged".into(),
            EventType::MatchStateChanged => "MatchStateChanged".into(),
            EventType::ScoreChanged => "ScoreChanged".into(),
            EventType::MatchEnded => "MatchEnded".into(),
            EventType::GameModeChanged => "GameModeChanged".into(),
            EventType::EntitySpawnedBySpawner => "EntitySpawnedBySpawner".into(),
            EventType::SpawnerCapacityReached => "SpawnerCapacityReached".into(),
            EventType::LifetimeExpired => "LifetimeExpired".into(),
            EventType::SchemaMutationApplied => "SchemaMutationApplied".into(),
            EventType::SnapshotTaken => "SnapshotTaken".into(),
            EventType::SnapshotRestored => "SnapshotRestored".into(),
            EventType::ExecutionPlanRecompiled => "ExecutionPlanRecompiled".into(),
            EventType::PeerConnected => "PeerConnected".into(),
            EventType::PeerDisconnected => "PeerDisconnected".into(),
            EventType::DesyncDetected => "DesyncDetected".into(),
            EventType::Domain(name) => format!("Domain({})", name),
        }
    }
}

impl std::fmt::Display for EventType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lifecycle_events_classified_correctly() {
        assert!(EventType::EntitySpawned.is_lifecycle_event());
        assert!(EventType::EntityDestroyed.is_lifecycle_event());
        assert!(!EventType::ScoreChanged.is_lifecycle_event());
    }

    #[test]
    fn physics_events_classified_correctly() {
        assert!(EventType::TriggerEntered.is_physics_event());
        assert!(EventType::CollisionStarted.is_physics_event());
        assert!(!EventType::EntitySpawned.is_physics_event());
    }

    #[test]
    fn game_state_events_classified_correctly() {
        assert!(EventType::GamePhaseChanged.is_game_state_event());
        assert!(EventType::ScoreChanged.is_game_state_event());
        assert!(!EventType::TriggerEntered.is_game_state_event());
    }

    #[test]
    fn domain_event_detected() {
        let e = EventType::Domain("combat.damage_applied".into());
        assert!(e.is_domain_event());
        assert!(!EventType::EntitySpawned.is_domain_event());
    }

    #[test]
    fn domain_prefix_extracted_correctly() {
        let e = EventType::Domain("combat.damage_applied".into());
        assert_eq!(e.domain_prefix(), Some("combat"));
    }

    #[test]
    fn non_domain_has_no_prefix() {
        assert_eq!(EventType::EntitySpawned.domain_prefix(), None);
    }

    #[test]
    fn network_events_classified_correctly() {
        assert!(EventType::PeerConnected.is_network_event());
        assert!(EventType::DesyncDetected.is_network_event());
        assert!(!EventType::EntitySpawned.is_network_event());
    }

    #[test]
    fn event_type_name_correct() {
        assert_eq!(EventType::EntitySpawned.name(), "EntitySpawned");
        assert_eq!(
            EventType::Domain("rpg.level_up".into()).name(),
            "Domain(rpg.level_up)"
        );
    }

    #[test]
    fn display_matches_name() {
        let types = vec![
            EventType::EntitySpawned,
            EventType::TriggerEntered,
            EventType::ScoreChanged,
        ];
        for t in types {
            assert_eq!(t.to_string(), t.name());
        }
    }

    #[test]
    fn domain_event_equality() {
        let a = EventType::Domain("combat.damage_applied".into());
        let b = EventType::Domain("combat.damage_applied".into());
        let c = EventType::Domain("combat.entity_died".into());
        assert_eq!(a, b);
        assert_ne!(a, c);
    }

    #[test]
    fn event_type_hashable() {
        use std::collections::HashSet;
        let mut set = HashSet::new();
        set.insert(EventType::EntitySpawned);
        set.insert(EventType::EntityDestroyed);
        set.insert(EventType::Domain("combat.damage".into()));
        assert_eq!(set.len(), 3);
    }
}