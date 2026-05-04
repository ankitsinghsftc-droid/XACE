//! # Feedback Router
//!
//! Routes validated `FeedbackMessage` values to the correct handler
//! based on `FeedbackType::handler_kind()`. The single dispatch point
//! between the `FeedbackBuffer` drain and the six handler modules.
//!
//! ## Routing Flow (per tick, at tick START — I13)
//! ```text
//! FeedbackBuffer::drain_sorted()
//!     └── FeedbackValidator::filter_valid()
//!             └── FeedbackRouter::route_all()
//!                     ├── AnimationFeedbackHandler   (AnimationStateUpdate, AnimationEventFired)
//!                     ├── PhysicsFeedbackHandler     (PhysicsSettled)
//!                     ├── VisibilityFeedbackHandler  (VisibilityQueryResult)
//!                     ├── AudioFeedbackHandler       (AudioComplete, AudioPositionUpdate)
//!                     ├── InputFeedbackHandler       (InputDeviceUpdate)
//!                     └── PerformanceFeedbackHandler (PerformanceMetrics)
//!                     [AssetHandler and ErrorHandler are logged only in Phase 7 —
//!                      full Asset Registry integration happens in Phase 7.4]
//! ```
//!
//! ## Handler Trait
//! All handlers implement `FeedbackHandler`. The router holds a
//! `Vec<Box<dyn FeedbackHandler>>` registered at startup. This allows
//! handlers to be enabled/disabled per deployment without touching
//! the router itself.
//!
//! ## Determinism
//! Messages are routed in the order produced by `drain_sorted()` —
//! `(generated_frame ASC, entity_id ASC)`. The router never reorders.
//! Each handler processes its message synchronously before the next
//! message is dispatched. No parallel handler execution.
//!
//! ## Error Policy
//! A handler error for one message does not stop routing of subsequent
//! messages. Errors are accumulated and returned as a batch after all
//! messages have been attempted. The caller logs failures and continues —
//! feedback processing is non-fatal (I13 guarantees timing, not correctness
//! of every individual feedback message).

use xace_core::errors::xace_error::XaceError;
use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackType};

use crate::feedback_message::{FeedbackMessageExt, TypedFeedbackPayload};
use crate::feedback_type_enum::FeedbackTypeExt;

// Re-export so handlers can import FeedbackHandlerKind from this module
pub use crate::feedback_type_enum::FeedbackHandlerKind;

// ── Handler Trait ─────────────────────────────────────────────────────────────

/// A feedback handler processes one category of `FeedbackMessage` values.
///
/// Implement this trait for each of the six handler kinds. The router
/// calls `can_handle()` to check eligibility, then `handle()` to process.
///
/// ## Contract
/// - `handle()` must be deterministic: same input → same mutations (D6, D9)
/// - `handle()` must never mutate component state directly — only via Mutation Gate (I2)
/// - `handle()` must complete without I/O or blocking
/// - `handle()` returns `Ok(())` on success or `Err(RecoverableError)` on failure
pub trait FeedbackHandler: Send + Sync {
    /// Returns the handler kind this implementation services.
    fn kind(&self) -> FeedbackHandlerKind;

    /// Returns true if this handler can process the given feedback type.
    ///
    /// Default implementation: returns true when `ft.handler_kind() == self.kind()`.
    /// Override for handlers that service multiple `FeedbackHandlerKind` values.
    fn can_handle(&self, ft: FeedbackType) -> bool {
        ft.handler_kind() == self.kind()
    }

    /// Processes one typed feedback payload.
    ///
    /// The router has already parsed the payload via `parse_typed()`.
    /// The handler receives a fully typed value, never raw JSON.
    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError>;

    /// Human-readable name for logging.
    fn name(&self) -> &str;
}

// ── Router Metrics ────────────────────────────────────────────────────────────

/// Per-tick and cumulative routing metrics.
#[derive(Debug, Clone, Default)]
pub struct RouterMetrics {
    /// Total messages routed across all ticks.
    pub total_routed: u64,
    /// Total messages that had no registered handler (logged, not fatal).
    pub unhandled_count: u64,
    /// Total handler errors (recoverable — routing continued).
    pub handler_errors: u64,
    /// Messages routed per handler kind (indexed by `FeedbackHandlerKind` name).
    pub routed_by_kind: std::collections::BTreeMap<String, u64>,
    /// Total parse failures (TypedFeedbackPayload::parse_typed returned Err).
    pub parse_failures: u64,
}

// ── Feedback Router ───────────────────────────────────────────────────────────

/// Dispatches validated `FeedbackMessage` values to registered handlers.
///
/// ## Setup
/// ```ignore
/// let mut router = FeedbackRouter::new();
/// router.register(Box::new(AnimationFeedbackHandler::new(mutation_gate.clone())));
/// router.register(Box::new(PhysicsFeedbackHandler::new(mutation_gate.clone())));
/// // ... register remaining handlers ...
/// ```
///
/// ## Per-tick Use
/// ```ignore
/// let messages = buffer.drain_sorted();
/// let messages = validator.filter_valid(messages);
/// let errors = router.route_all(messages);
/// for err in errors { log::warn!("{}", err.message()); }
/// ```
pub struct FeedbackRouter {
    /// Registered handlers. Searched in registration order for each message.
    handlers: Vec<Box<dyn FeedbackHandler>>,

    /// Accumulated routing metrics.
    metrics: RouterMetrics,
}

impl FeedbackRouter {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates an empty router with no handlers registered.
    pub fn new() -> Self {
        Self {
            handlers: Vec::new(),
            metrics: RouterMetrics::default(),
        }
    }

    // ── Handler Registration ──────────────────────────────────────────────────

    /// Registers a feedback handler.
    ///
    /// Called once at session startup for each handler kind.
    /// Registration order does not affect routing — dispatch is by
    /// `FeedbackType::handler_kind()` not by registration index.
    pub fn register(&mut self, handler: Box<dyn FeedbackHandler>) {
        self.handlers.push(handler);
    }

    /// Returns the number of registered handlers.
    pub fn handler_count(&self) -> usize {
        self.handlers.len()
    }

    /// Returns true if a handler is registered for the given feedback type.
    pub fn has_handler_for(&self, ft: FeedbackType) -> bool {
        self.handlers.iter().any(|h| h.can_handle(ft))
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Routes a single `FeedbackMessage` to its handler.
    ///
    /// Parse step: `FeedbackMessageExt::parse_typed()` is called first.
    /// If parsing fails, the message is skipped (parse failure counted in metrics).
    ///
    /// Dispatch step: the first registered handler whose `can_handle()` returns
    /// true for this message's `FeedbackType` processes it.
    ///
    /// Returns `Ok(())` if handled successfully or no handler was registered.
    /// Returns `Err` only if the handler itself returned an error.
    pub fn route(&mut self, message: &FeedbackMessage) -> Result<(), XaceError> {
        // Parse the typed payload
        let typed = match message.parse_typed() {
            Ok(t) => t,
            Err(e) => {
                self.metrics.parse_failures += 1;
                return Err(e);
            }
        };

        let ft = message.feedback_type;

        // Find the registered handler for this type
        let handler = self.handlers.iter().find(|h| h.can_handle(ft));

        match handler {
            Some(h) => {
                let kind_name = h.kind().to_string();
                let result = h.handle(&typed);

                *self.metrics.routed_by_kind
                    .entry(kind_name)
                    .or_insert(0) += 1;
                self.metrics.total_routed += 1;

                if let Err(ref e) = result {
                    self.metrics.handler_errors += 1;
                    eprintln!(
                        "[WARN] FeedbackRouter: handler error for {:?} entity={} frame={}: {}",
                        ft, message.entity_id, message.generated_frame,
                        e.message()
                    );
                }
                result
            }
            None => {
                // No handler registered for this type — log and continue
                self.metrics.unhandled_count += 1;
                eprintln!(
                    "[WARN] FeedbackRouter: no handler registered for {:?} \
                     (entity={} frame={})",
                    ft, message.entity_id, message.generated_frame
                );
                Ok(())
            }
        }
    }

    /// Routes a batch of validated messages in order.
    ///
    /// Processes every message regardless of individual handler errors.
    /// Returns all errors accumulated across the batch — caller logs them.
    /// Order is preserved: messages are routed in the exact order received
    /// from `drain_sorted()`.
    pub fn route_all(&mut self, messages: Vec<FeedbackMessage>) -> Vec<XaceError> {
        let mut errors = Vec::new();
        for msg in &messages {
            if let Err(e) = self.route(msg) {
                errors.push(e);
            }
        }
        errors
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    /// Returns accumulated routing metrics.
    pub fn metrics(&self) -> &RouterMetrics {
        &self.metrics
    }

    /// Resets per-session metrics. Called between sessions.
    pub fn reset_metrics(&mut self) {
        self.metrics = RouterMetrics::default();
    }
}

impl Default for FeedbackRouter {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::FeedbackType;
    use std::sync::{Arc, Mutex};

    // ── Mock Handler ──────────────────────────────────────────────────────────

    /// Captures all handled payloads for assertions.
    struct MockHandler {
        kind: FeedbackHandlerKind,
        handled: Arc<Mutex<Vec<FeedbackType>>>,
        should_fail: bool,
    }

    impl MockHandler {
        fn new(kind: FeedbackHandlerKind) -> (Self, Arc<Mutex<Vec<FeedbackType>>>) {
            let handled = Arc::new(Mutex::new(Vec::new()));
            let h = Self { kind, handled: handled.clone(), should_fail: false };
            (h, handled)
        }

        fn failing(kind: FeedbackHandlerKind) -> Self {
            Self { kind, handled: Arc::new(Mutex::new(Vec::new())), should_fail: true }
        }
    }

    impl FeedbackHandler for MockHandler {
        fn kind(&self) -> FeedbackHandlerKind { self.kind }
        fn name(&self) -> &str { "MockHandler" }
        fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
            if self.should_fail {
                return Err(XaceError::RecoverableError {
                    message: "mock handler failure".into(),
                    context: ErrorContext::new("MockHandler", "handle"),
                    max_retries: 0,
                    retry_count: 0,
                });
            }
            self.handled.lock().unwrap().push(payload.feedback_type());
            Ok(())
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    fn physics_msg(entity_id: u64, frame: u64) -> FeedbackMessage {
        use xace_core::wire::feedback_payload::PhysicsSettledFeedback;
        FeedbackMessage {
            feedback_type: FeedbackType::PhysicsSettled,
            entity_id,
            generated_frame: frame,
            payload_json: serde_json::to_string(&PhysicsSettledFeedback {
                entity_id,
                final_position_json: r#"{"x":0,"y":0,"z":0}"#.into(),
                final_rotation_json: r#"{"x":0,"y":0,"z":0,"w":1}"#.into(),
                generated_frame: frame,
            }).unwrap(),
        }
    }

    fn perf_msg(frame: u64) -> FeedbackMessage {
        use xace_core::wire::feedback_payload::PerformanceMetricsFeedback;
        FeedbackMessage {
            feedback_type: FeedbackType::PerformanceMetrics,
            entity_id: 0,
            generated_frame: frame,
            payload_json: serde_json::to_string(&PerformanceMetricsFeedback {
                engine_delta_apply_ms: 1.0,
                draw_calls: 100,
                physics_contacts: 10,
                engine_entity_count: 50,
                generated_frame: frame,
            }).unwrap(),
        }
    }

    // ── Registration ─────────────────────────────────────────────────────────

    #[test]
    fn empty_router_has_no_handlers() {
        let r = FeedbackRouter::new();
        assert_eq!(r.handler_count(), 0);
    }

    #[test]
    fn register_increases_handler_count() {
        let mut r = FeedbackRouter::new();
        let (h, _) = MockHandler::new(FeedbackHandlerKind::Physics);
        r.register(Box::new(h));
        assert_eq!(r.handler_count(), 1);
    }

    #[test]
    fn has_handler_for_correct() {
        let mut r = FeedbackRouter::new();
        let (h, _) = MockHandler::new(FeedbackHandlerKind::Physics);
        r.register(Box::new(h));
        assert!(r.has_handler_for(FeedbackType::PhysicsSettled));
        assert!(!r.has_handler_for(FeedbackType::AudioComplete));
    }

    // ── Routing ───────────────────────────────────────────────────────────────

    #[test]
    fn route_dispatches_to_correct_handler() {
        let mut r = FeedbackRouter::new();
        let (h, handled) = MockHandler::new(FeedbackHandlerKind::Physics);
        r.register(Box::new(h));

        r.route(&physics_msg(1, 1)).unwrap();
        assert_eq!(handled.lock().unwrap().len(), 1);
        assert_eq!(handled.lock().unwrap()[0], FeedbackType::PhysicsSettled);
    }

    #[test]
    fn route_unhandled_type_returns_ok_not_err() {
        let mut r = FeedbackRouter::new();
        // No handler registered for PhysicsSettled
        let result = r.route(&physics_msg(1, 1));
        assert!(result.is_ok());
        assert_eq!(r.metrics().unhandled_count, 1);
    }

    #[test]
    fn route_does_not_dispatch_to_wrong_handler() {
        let mut r = FeedbackRouter::new();
        let (h, handled) = MockHandler::new(FeedbackHandlerKind::Performance);
        r.register(Box::new(h));
        // PhysicsSettled should not go to Performance handler
        r.route(&physics_msg(1, 1)).ok();
        assert_eq!(handled.lock().unwrap().len(), 0);
        assert_eq!(r.metrics().unhandled_count, 1);
    }

    #[test]
    fn handler_error_returned_but_routing_continues() {
        let mut r = FeedbackRouter::new();
        r.register(Box::new(MockHandler::failing(FeedbackHandlerKind::Physics)));

        let result = r.route(&physics_msg(1, 1));
        assert!(result.is_err());
        assert_eq!(r.metrics().handler_errors, 1);
    }

    #[test]
    fn route_all_processes_all_messages_despite_errors() {
        let mut r = FeedbackRouter::new();
        r.register(Box::new(MockHandler::failing(FeedbackHandlerKind::Physics)));
        let (ph, perf_handled) = MockHandler::new(FeedbackHandlerKind::Performance);
        r.register(Box::new(ph));

        let msgs = vec![physics_msg(1, 1), physics_msg(2, 2), perf_msg(3)];
        let errors = r.route_all(msgs);
        // Two physics errors accumulated
        assert_eq!(errors.len(), 2);
        // Performance message still routed despite physics failures
        assert_eq!(perf_handled.lock().unwrap().len(), 1);
    }

    #[test]
    fn route_all_empty_batch_returns_no_errors() {
        let mut r = FeedbackRouter::new();
        let errors = r.route_all(vec![]);
        assert!(errors.is_empty());
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_routed_by_kind() {
        let mut r = FeedbackRouter::new();
        let (h, _) = MockHandler::new(FeedbackHandlerKind::Physics);
        r.register(Box::new(h));

        r.route(&physics_msg(1, 1)).ok();
        r.route(&physics_msg(2, 2)).ok();

        let m = r.metrics();
        assert_eq!(m.total_routed, 2);
        assert_eq!(m.routed_by_kind.get("PhysicsHandler"), Some(&2));
    }

    #[test]
    fn metrics_reset_clears_all() {
        let mut r = FeedbackRouter::new();
        let (h, _) = MockHandler::new(FeedbackHandlerKind::Physics);
        r.register(Box::new(h));
        r.route(&physics_msg(1, 1)).ok();
        r.reset_metrics();
        assert_eq!(r.metrics().total_routed, 0);
        assert_eq!(r.metrics().unhandled_count, 0);
    }

    #[test]
    fn parse_failure_counted_in_metrics() {
        let mut r = FeedbackRouter::new();
        let (h, _) = MockHandler::new(FeedbackHandlerKind::Physics);
        r.register(Box::new(h));

        let bad_msg = FeedbackMessage {
            feedback_type: FeedbackType::PhysicsSettled,
            entity_id: 1,
            generated_frame: 1,
            payload_json: "not valid json".into(),
        };
        r.route(&bad_msg).ok();
        assert_eq!(r.metrics().parse_failures, 1);
    }
}