//! # Adapter Authority Enforcer
//!
//! Enforces Global Invariant I5 and Determinism Rule D13:
//! Engine adapters mirror state only — they NEVER modify authoritative
//! simulation state.
//!
//! ## The Problem This Solves
//! The engine adapter receives `StateDelta` from XACE and sends it to
//! the engine. The engine then sends back `INPUT` and `FEEDBACK` messages.
//! There is a tempting but illegal shortcut: having the engine adapter
//! write directly into the component tables when feedback arrives —
//! bypassing the Mutation Gate entirely.
//!
//! This is forbidden for three reasons:
//! 1. **Determinism (D13)** — direct writes from the adapter break the
//!    fixed mutation ordering that world_hash depends on (D4, D9).
//! 2. **Replay (D14)** — replays that do not include engine feedback
//!    would produce different world state if the adapter wrote directly.
//! 3. **Architecture (I5)** — Layer 6 (engine adapters) must never touch
//!    Layer 5 (runtime) state. The 7-layer architecture has no bypass.
//!
//! ## What This Enforcer Does
//! The `AdapterAuthorityEnforcer` inspects every inbound WireMessage
//! received from the engine and classifies it as:
//!
//! - **Permitted** — INPUT and FEEDBACK messages that the runtime expects
//!   from the engine. These are passed through to the appropriate handlers.
//!
//! - **Attempted mutation** — Any message type that would imply the engine
//!   is trying to modify authoritative state (DELTA, SNAPSHOT sent inbound).
//!   These are rejected with an `AuthorityViolation` error.
//!
//! - **Unexpected** — Valid WireMessage types that should not arrive from
//!   the engine in normal operation (e.g. inbound CONTROL after handshake).
//!   These are logged as warnings but not hard-rejected.
//!
//! ## Integration Point
//! The enforcer sits between the transport's `try_receive_messages()` output
//! and the feedback/input handlers. `EngineAdapterInterface::drain_feedback()`
//! calls `AdapterAuthorityEnforcer::check()` on every received message before
//! routing it downstream.
//!
//! ## Violation Handling
//! Violations produce `XaceError::FatalError` in STRICT mode —
//! an engine adapter attempting to write simulation state is a critical
//! security and correctness violation, not a recoverable condition.
//! In DEV mode, violations are logged and the message is dropped.

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::message_type::MessageType;
use xace_core::wire::wire_message::WireMessage;

// ── Authority Classification ──────────────────────────────────────────────────

/// How a given inbound WireMessage is classified by the enforcer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthorityClassification {
    /// Message is explicitly expected from the engine. Pass to handler.
    Permitted,

    /// Message type implies the engine is attempting to write authoritative
    /// simulation state. Always rejected. Never forwarded.
    AttemptedMutation {
        /// The message type that triggered the violation.
        message_type: MessageType,
        /// Human-readable description of why this type is forbidden inbound.
        reason: &'static str,
    },

    /// Message arrived in a context where it is not expected, but is not
    /// a hard authority violation. Logged and dropped without processing.
    Unexpected {
        message_type: MessageType,
    },
}

impl AuthorityClassification {
    /// Returns true if the message should be forwarded to a handler.
    pub fn is_permitted(&self) -> bool {
        matches!(self, AuthorityClassification::Permitted)
    }

    /// Returns true if this is a hard authority violation.
    pub fn is_violation(&self) -> bool {
        matches!(self, AuthorityClassification::AttemptedMutation { .. })
    }
}

// ── Enforcer Metrics ──────────────────────────────────────────────────────────

/// Accumulated metrics for one AdapterAuthorityEnforcer session.
#[derive(Debug, Clone, Default)]
pub struct EnforcerMetrics {
    /// Total messages checked.
    pub messages_checked: u64,
    /// Total messages classified as Permitted.
    pub permitted_count: u64,
    /// Total AttemptedMutation violations detected.
    pub violation_count: u64,
    /// Total Unexpected messages logged and dropped.
    pub unexpected_count: u64,
}

// ── Enforcer Mode ─────────────────────────────────────────────────────────────

/// How the enforcer handles detected violations.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EnforcerMode {
    /// Violation → `XaceError::FatalError` returned. Session halts.
    /// Use in all production and staging environments.
    Strict,

    /// Violation → logged to stderr, message dropped, session continues.
    /// Use only for debugging suspected adapter misbehaviour.
    Dev,
}

impl std::fmt::Display for EnforcerMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EnforcerMode::Strict => write!(f, "STRICT"),
            EnforcerMode::Dev    => write!(f, "DEV"),
        }
    }
}

// ── Adapter Authority Enforcer ────────────────────────────────────────────────

/// Validates that inbound WireMessages from the engine adapter do not
/// attempt to modify authoritative simulation state (I5, D13).
///
/// ## Permitted Inbound Types
/// - `MessageType::Input`    — player/AI input packets (D12, I14)
/// - `MessageType::Feedback` — engine feedback batch (I13, Audit 6)
/// - `MessageType::Control`  — handshake and ping-pong only
///
/// ## Forbidden Inbound Types
/// - `MessageType::Delta`    — DELTA is XACE→Engine only. Inbound = I5 violation.
/// - `MessageType::Snapshot` — SNAPSHOT is XACE→Engine only. Inbound = I5 violation.
/// - `MessageType::Event`    — Events are generated by the runtime. Inbound = I5 violation.
///
/// Post-handshake CONTROL messages are `Unexpected` (not violations) —
/// the engine may send pings and the adapter may send reconnect signals.
pub struct AdapterAuthorityEnforcer {
    mode: EnforcerMode,
    metrics: EnforcerMetrics,

    /// Whether the handshake has been completed.
    /// CONTROL messages before handshake are Permitted (they ARE the handshake).
    /// CONTROL messages after handshake are Unexpected (warnings only).
    handshake_complete: bool,
}

impl AdapterAuthorityEnforcer {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new enforcer in the given mode, pre-handshake.
    pub fn new(mode: EnforcerMode) -> Self {
        Self {
            mode,
            metrics: EnforcerMetrics::default(),
            handshake_complete: false,
        }
    }

    /// Creates an enforcer in STRICT mode (production default).
    pub fn strict() -> Self {
        Self::new(EnforcerMode::Strict)
    }

    /// Creates an enforcer in DEV mode (debugging only).
    pub fn dev() -> Self {
        Self::new(EnforcerMode::Dev)
    }

    // ── Handshake Lifecycle ───────────────────────────────────────────────────

    /// Marks the handshake as complete.
    ///
    /// After this call, inbound CONTROL messages are classified as
    /// `Unexpected` (logged, dropped) rather than `Permitted`.
    /// Call this after `ProtocolHandshake::process_hello_frame()` succeeds.
    pub fn mark_handshake_complete(&mut self) {
        self.handshake_complete = true;
    }

    /// Returns true if the handshake has been completed.
    pub fn is_handshake_complete(&self) -> bool {
        self.handshake_complete
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Classifies a single inbound WireMessage and enforces the authority rules.
    ///
    /// Returns `Ok(classification)` for Permitted and Unexpected messages.
    /// Returns `Err(XaceError::FatalError)` in STRICT mode for violations.
    /// Returns `Ok(AttemptedMutation)` in DEV mode for violations (logged).
    ///
    /// The caller should:
    /// - Forward `Permitted` messages to the appropriate handler.
    /// - Log and discard `Unexpected` messages.
    /// - Treat `Err` as a session-terminating condition (STRICT mode).
    /// - Treat `Ok(AttemptedMutation)` as a logged warning (DEV mode).
    pub fn check(
        &mut self,
        msg: &WireMessage,
    ) -> Result<AuthorityClassification, XaceError> {
        self.metrics.messages_checked += 1;

        let classification = self.classify(msg);

        match &classification {
            AuthorityClassification::Permitted => {
                self.metrics.permitted_count += 1;
                Ok(classification)
            }

            AuthorityClassification::AttemptedMutation { message_type, reason } => {
                self.metrics.violation_count += 1;
                let violation_msg = format!(
                    "AdapterAuthorityEnforcer: inbound {:?} from engine violates I5/D13 — {}. \
                     Engine adapters must NEVER send {:?} messages to XACE. \
                     world_id='{}' tick={} seq={}",
                    message_type, reason, message_type,
                    msg.world_id, msg.tick, msg.sequence_id
                );

                match self.mode {
                    EnforcerMode::Strict => {
                        eprintln!("[FATAL][I5/D13] {}", violation_msg);
                        Err(XaceError::FatalError {
                            message: violation_msg,
                            context: ErrorContext::new(
                                "AdapterAuthorityEnforcer",
                                "check",
                            )
                            .with_tick(msg.tick)
                            .with_detail("message_type", format!("{:?}", message_type))
                            .with_detail("world_id", &msg.world_id),
                            snapshot_recovery_possible: false,
                        })
                    }
                    EnforcerMode::Dev => {
                        eprintln!("[WARN][I5/D13] {}", violation_msg);
                        Ok(classification)
                    }
                }
            }

            AuthorityClassification::Unexpected { message_type } => {
                self.metrics.unexpected_count += 1;
                eprintln!(
                    "[WARN] AdapterAuthorityEnforcer: unexpected inbound {:?} from engine \
                     at tick {} seq {} — message dropped",
                    message_type, msg.tick, msg.sequence_id
                );
                Ok(classification)
            }
        }
    }

    /// Checks a batch of messages and returns only the Permitted ones.
    ///
    /// In STRICT mode, the first violation aborts the entire batch
    /// and returns `Err`. In DEV mode, violations are logged and skipped.
    pub fn filter_permitted(
        &mut self,
        messages: Vec<WireMessage>,
    ) -> Result<Vec<WireMessage>, XaceError> {
        let mut permitted = Vec::with_capacity(messages.len());

        for msg in messages {
            match self.check(&msg)? {
                AuthorityClassification::Permitted => permitted.push(msg),
                _ => {} // Unexpected and AttemptedMutation (DEV) are dropped
            }
        }

        Ok(permitted)
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns accumulated enforcer metrics.
    pub fn metrics(&self) -> &EnforcerMetrics {
        &self.metrics
    }

    /// Returns the enforcer mode.
    pub fn mode(&self) -> EnforcerMode {
        self.mode
    }

    /// Returns true if any authority violations have been detected.
    pub fn has_violations(&self) -> bool {
        self.metrics.violation_count > 0
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /// Classifies a message type into Permitted / AttemptedMutation / Unexpected.
    fn classify(&self, msg: &WireMessage) -> AuthorityClassification {
        match msg.message_type {
            // ── Always permitted from engine ───────────────────────────────
            MessageType::Input => AuthorityClassification::Permitted,
            MessageType::Feedback => AuthorityClassification::Permitted,

            // ── CONTROL: permitted pre-handshake, unexpected post-handshake
            MessageType::Control => {
                if !self.handshake_complete {
                    AuthorityClassification::Permitted
                } else {
                    AuthorityClassification::Unexpected {
                        message_type: MessageType::Control,
                    }
                }
            }

            // ── Hard violations — engine must never send these inbound ─────

            MessageType::Delta => AuthorityClassification::AttemptedMutation {
                message_type: MessageType::Delta,
                reason: "DELTA messages are XACE→Engine only. \
                         The engine must never send DELTA inbound. \
                         Engine adapters mirror state — they never push state back.",
            },

            MessageType::Snapshot => AuthorityClassification::AttemptedMutation {
                message_type: MessageType::Snapshot,
                reason: "SNAPSHOT messages are XACE→Engine only. \
                         Inbound SNAPSHOT implies the engine is attempting \
                         to overwrite authoritative world state.",
            },

            MessageType::Event => AuthorityClassification::AttemptedMutation {
                message_type: MessageType::Event,
                reason: "EVENT messages originate from the runtime, not the engine. \
                         Inbound EVENT implies the engine is injecting events \
                         into the simulation, bypassing the EventBus contract.",
            },
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::wire_message::WireMessage;

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn input_msg() -> WireMessage {
        WireMessage::new(
            "default", "0.1.0", 1, 1, 1,
            MessageType::Input,
            r#"{"actions":[]}"#,
        )
    }

    fn feedback_msg() -> WireMessage {
        WireMessage::feedback(
            "default", "0.1.0", 1, 1, 1,
            r#"{"tick":1,"messages":[]}"#,
        )
    }

    fn control_msg() -> WireMessage {
        WireMessage::control(
            "default", "0.1.0", 1, 1,
            r#"{"control_type":"Hello"}"#,
        )
    }

    fn delta_msg() -> WireMessage {
        WireMessage::delta(
            "default", "0.1.0", 1, 1, 1,
            r#"{"tick":1}"#,
        )
    }

    fn snapshot_msg() -> WireMessage {
        WireMessage::snapshot(
            "default", "0.1.0", 1, 1, 1,
            r#"{"tick":1,"entities":[]}"#,
        )
    }

    fn event_msg() -> WireMessage {
        WireMessage::new(
            "default", "0.1.0", 1, 1, 1,
            MessageType::Event,
            r#"{"event_type":"EntitySpawned"}"#,
        )
    }

    // ── Permitted Messages ────────────────────────────────────────────────────

    #[test]
    fn input_message_is_permitted() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let result = e.check(&input_msg()).unwrap();
        assert!(result.is_permitted());
        assert_eq!(e.metrics().permitted_count, 1);
    }

    #[test]
    fn feedback_message_is_permitted() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let result = e.check(&feedback_msg()).unwrap();
        assert!(result.is_permitted());
    }

    #[test]
    fn control_message_permitted_before_handshake() {
        let mut e = AdapterAuthorityEnforcer::strict();
        // handshake_complete defaults to false
        let result = e.check(&control_msg()).unwrap();
        assert!(result.is_permitted());
    }

    #[test]
    fn control_message_unexpected_after_handshake() {
        let mut e = AdapterAuthorityEnforcer::strict();
        e.mark_handshake_complete();
        let result = e.check(&control_msg()).unwrap();
        assert!(matches!(
            result,
            AuthorityClassification::Unexpected { message_type: MessageType::Control }
        ));
        assert_eq!(e.metrics().unexpected_count, 1);
    }

    // ── Authority Violations ──────────────────────────────────────────────────

    #[test]
    fn inbound_delta_is_violation_in_strict_mode() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let result = e.check(&delta_msg());
        assert!(result.is_err(), "Inbound DELTA must be fatal in STRICT mode");
        assert_eq!(e.metrics().violation_count, 1);
        assert!(e.has_violations());
    }

    #[test]
    fn inbound_snapshot_is_violation_in_strict_mode() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let result = e.check(&snapshot_msg());
        assert!(result.is_err(), "Inbound SNAPSHOT must be fatal in STRICT mode");
        assert!(e.has_violations());
    }

    #[test]
    fn inbound_event_is_violation_in_strict_mode() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let result = e.check(&event_msg());
        assert!(result.is_err(), "Inbound EVENT must be fatal in STRICT mode");
        assert!(e.has_violations());
    }

    #[test]
    fn inbound_delta_in_dev_mode_returns_ok_but_records_violation() {
        let mut e = AdapterAuthorityEnforcer::dev();
        let result = e.check(&delta_msg());
        assert!(result.is_ok(), "DEV mode must return Ok on violation");
        assert_eq!(e.metrics().violation_count, 1);
        assert!(e.has_violations());
        // Classification returned is AttemptedMutation
        assert!(result.unwrap().is_violation());
    }

    #[test]
    fn inbound_snapshot_in_dev_mode_logs_and_continues() {
        let mut e = AdapterAuthorityEnforcer::dev();
        assert!(e.check(&snapshot_msg()).is_ok());
        assert_eq!(e.metrics().violation_count, 1);
    }

    #[test]
    fn multiple_violations_accumulate_count() {
        let mut e = AdapterAuthorityEnforcer::dev();
        e.check(&delta_msg()).ok();
        e.check(&snapshot_msg()).ok();
        e.check(&event_msg()).ok();
        assert_eq!(e.metrics().violation_count, 3);
    }

    // ── filter_permitted ──────────────────────────────────────────────────────

    #[test]
    fn filter_permitted_keeps_only_input_and_feedback() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let messages = vec![input_msg(), feedback_msg(), control_msg()];
        // control_msg pre-handshake is Permitted too
        let result = e.filter_permitted(messages).unwrap();
        assert_eq!(result.len(), 3); // all permitted pre-handshake
    }

    #[test]
    fn filter_permitted_aborts_on_violation_in_strict() {
        let mut e = AdapterAuthorityEnforcer::strict();
        e.mark_handshake_complete();
        let messages = vec![input_msg(), delta_msg(), feedback_msg()];
        // delta_msg is a violation — strict mode aborts
        let result = e.filter_permitted(messages);
        assert!(result.is_err());
    }

    #[test]
    fn filter_permitted_skips_violations_in_dev() {
        let mut e = AdapterAuthorityEnforcer::dev();
        e.mark_handshake_complete();
        let messages = vec![input_msg(), delta_msg(), feedback_msg()];
        let permitted = e.filter_permitted(messages).unwrap();
        // input and feedback are permitted; delta is logged and skipped
        assert_eq!(permitted.len(), 2);
        assert!(permitted.iter().all(|m| {
            matches!(m.message_type, MessageType::Input | MessageType::Feedback)
        }));
    }

    #[test]
    fn filter_permitted_empty_input_returns_empty() {
        let mut e = AdapterAuthorityEnforcer::strict();
        let result = e.filter_permitted(vec![]).unwrap();
        assert!(result.is_empty());
    }

    // ── Handshake Lifecycle ───────────────────────────────────────────────────

    #[test]
    fn mark_handshake_complete_changes_control_classification() {
        let mut e = AdapterAuthorityEnforcer::strict();
        assert!(!e.is_handshake_complete());

        // Pre-handshake: control is Permitted
        let r1 = e.check(&control_msg()).unwrap();
        assert!(r1.is_permitted());

        e.mark_handshake_complete();
        assert!(e.is_handshake_complete());

        // Post-handshake: control is Unexpected
        let r2 = e.check(&control_msg()).unwrap();
        assert!(matches!(r2, AuthorityClassification::Unexpected { .. }));
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_start_at_zero() {
        let e = AdapterAuthorityEnforcer::strict();
        let m = e.metrics();
        assert_eq!(m.messages_checked, 0);
        assert_eq!(m.permitted_count, 0);
        assert_eq!(m.violation_count, 0);
        assert_eq!(m.unexpected_count, 0);
    }

    #[test]
    fn messages_checked_increments_for_every_message() {
        let mut e = AdapterAuthorityEnforcer::dev();
        e.check(&input_msg()).ok();
        e.check(&feedback_msg()).ok();
        e.check(&delta_msg()).ok(); // violation but dev mode
        assert_eq!(e.metrics().messages_checked, 3);
    }

    // ── Mode Accessor ─────────────────────────────────────────────────────────

    #[test]
    fn mode_accessor_returns_correct_mode() {
        assert_eq!(AdapterAuthorityEnforcer::strict().mode(), EnforcerMode::Strict);
        assert_eq!(AdapterAuthorityEnforcer::dev().mode(), EnforcerMode::Dev);
    }

    // ── Classification Helpers ────────────────────────────────────────────────

    #[test]
    fn attempted_mutation_is_violation() {
        let c = AuthorityClassification::AttemptedMutation {
            message_type: MessageType::Delta,
            reason: "test",
        };
        assert!(c.is_violation());
        assert!(!c.is_permitted());
    }

    #[test]
    fn permitted_is_not_violation() {
        assert!(AuthorityClassification::Permitted.is_permitted());
        assert!(!AuthorityClassification::Permitted.is_violation());
    }

    #[test]
    fn unexpected_is_neither_permitted_nor_violation() {
        let c = AuthorityClassification::Unexpected {
            message_type: MessageType::Control,
        };
        assert!(!c.is_permitted());
        assert!(!c.is_violation());
    }
}