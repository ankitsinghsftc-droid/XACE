//! Visibility feedback handler.
//!
//! Visibility feedback is buffered at tick boundaries (I13). This handler
//! validates each engine raycast result, stores it in the one-tick visibility
//! result cache, and queues a deterministic perception write action for
//! Mutation Gate. It does not mutate authoritative component tables directly.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use xace_core::entity_id::EntityID;
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::FeedbackType;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;
use crate::visibility_query::visibility_query::VisibilityQueryResult;
use crate::visibility_query::visibility_result_store::VisibilityResultStore;

#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityPerceptionWriteAction {
    pub observer_entity_id: EntityID,
    pub target_entity_id: EntityID,
    pub can_see: bool,
    pub distance: f32,
    pub generated_frame: u64,
    pub sequence: u64,
}

impl VisibilityPerceptionWriteAction {
    pub fn sort_key(&self) -> (u64, EntityID, EntityID, u64) {
        (
            self.generated_frame,
            self.observer_entity_id,
            self.target_entity_id,
            self.sequence,
        )
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct VisibilityFeedbackMetrics {
    pub results_processed: u64,
    pub visible_count: u64,
    pub occluded_count: u64,
    pub validation_failures: u64,
    pub poison_recoveries: u64,
}

pub struct VisibilityFeedbackHandler {
    actions: Mutex<Vec<VisibilityPerceptionWriteAction>>,
    result_store: Arc<Mutex<VisibilityResultStore>>,
    sequence: AtomicU64,
    metrics: Mutex<VisibilityFeedbackMetrics>,
}

impl VisibilityFeedbackHandler {
    pub fn new() -> Self {
        Self::with_result_store(Arc::new(Mutex::new(VisibilityResultStore::new())))
    }

    pub fn with_result_store(result_store: Arc<Mutex<VisibilityResultStore>>) -> Self {
        Self {
            actions: Mutex::new(Vec::new()),
            result_store,
            sequence: AtomicU64::new(0),
            metrics: Mutex::new(VisibilityFeedbackMetrics::default()),
        }
    }

    pub fn results_processed(&self) -> u64 {
        self.metrics().results_processed
    }

    pub fn visible_count(&self) -> u64 {
        self.metrics().visible_count
    }

    pub fn occluded_count(&self) -> u64 {
        self.metrics().occluded_count
    }

    pub fn validation_failure_count(&self) -> u64 {
        self.metrics().validation_failures
    }

    pub fn pending_action_count(&self) -> usize {
        self.lock_actions().len()
    }

    pub fn stored_result_count(&self) -> usize {
        self.lock_result_store().stored_count()
    }

    pub fn metrics(&self) -> VisibilityFeedbackMetrics {
        self.lock_metrics().clone()
    }

    pub fn drain_actions_sorted(&self) -> Vec<VisibilityPerceptionWriteAction> {
        let mut actions = std::mem::take(&mut *self.lock_actions());
        actions.sort_by_key(VisibilityPerceptionWriteAction::sort_key);
        actions
    }

    pub fn expire_results(&self, current_tick: u64) -> usize {
        self.lock_result_store().expire_tick(current_tick)
    }

    pub fn can_see(&self, observer: EntityID, target: EntityID, current_tick: u64) -> Option<bool> {
        self.lock_result_store()
            .can_see(observer, target, current_tick)
    }

    fn next_sequence(&self) -> u64 {
        self.sequence.fetch_add(1, Ordering::Relaxed)
    }

    fn validation_error(&self, operation: &'static str, message: impl Into<String>) -> XaceError {
        self.lock_metrics().validation_failures += 1;
        recoverable(operation, message)
    }

    fn lock_actions(&self) -> MutexGuard<'_, Vec<VisibilityPerceptionWriteAction>> {
        match self.actions.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_result_store(&self) -> MutexGuard<'_, VisibilityResultStore> {
        match self.result_store.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_metrics(&self) -> MutexGuard<'_, VisibilityFeedbackMetrics> {
        match self.metrics.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }
}

impl Default for VisibilityFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for VisibilityFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Visibility
    }

    fn name(&self) -> &str {
        "VisibilityFeedbackHandler"
    }

    fn can_handle(&self, feedback_type: FeedbackType) -> bool {
        feedback_type == FeedbackType::VisibilityQueryResult
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let result = match payload {
            TypedFeedbackPayload::VisibilityQueryResult(result) => result,
            other => {
                return Err(recoverable(
                    "handle",
                    format!("unexpected payload type {:?}", other.feedback_type()),
                ))
            }
        };

        if result.observer_entity_id == 0 || result.target_entity_id == 0 {
            return Err(self.validation_error(
                "handle",
                format!(
                    "invalid entity IDs observer={} target={}",
                    result.observer_entity_id, result.target_entity_id
                ),
            ));
        }
        if result.observer_entity_id == result.target_entity_id {
            return Err(self.validation_error("handle", "observer and target are the same entity"));
        }
        if !result.distance.is_finite() || result.distance < 0.0 {
            return Err(self.validation_error(
                "handle",
                format!("distance is invalid: {}", result.distance),
            ));
        }

        self.lock_result_store().store(VisibilityQueryResult::new(
            result.observer_entity_id,
            result.target_entity_id,
            result.can_see,
            result.distance,
            result.generated_frame,
        ));
        self.lock_actions().push(VisibilityPerceptionWriteAction {
            observer_entity_id: result.observer_entity_id,
            target_entity_id: result.target_entity_id,
            can_see: result.can_see,
            distance: result.distance,
            generated_frame: result.generated_frame,
            sequence: self.next_sequence(),
        });

        let mut metrics = self.lock_metrics();
        metrics.results_processed += 1;
        if result.can_see {
            metrics.visible_count += 1;
        } else {
            metrics.occluded_count += 1;
        }
        Ok(())
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("VisibilityFeedbackHandler: {}", message.into()),
        context: ErrorContext::new("VisibilityFeedbackHandler", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::{FeedbackType, VisibilityQueryResultFeedback};

    fn vis_result(
        observer: u64,
        target: u64,
        can_see: bool,
        distance: f32,
    ) -> TypedFeedbackPayload {
        TypedFeedbackPayload::VisibilityQueryResult(VisibilityQueryResultFeedback {
            observer_entity_id: observer,
            target_entity_id: target,
            can_see,
            distance,
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_visibility() {
        assert_eq!(
            VisibilityFeedbackHandler::new().kind(),
            FeedbackHandlerKind::Visibility
        );
    }

    #[test]
    fn can_handle_visibility_query_result_only() {
        let handler = VisibilityFeedbackHandler::new();
        assert!(handler.can_handle(FeedbackType::VisibilityQueryResult));
        assert!(!handler.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn handle_visible_result_records_action_and_store() {
        let handler = VisibilityFeedbackHandler::new();
        handler.handle(&vis_result(1, 2, true, 10.0)).unwrap();

        assert_eq!(handler.results_processed(), 1);
        assert_eq!(handler.visible_count(), 1);
        assert_eq!(handler.stored_result_count(), 1);
        assert_eq!(handler.can_see(1, 2, 1), Some(true));
        assert_eq!(handler.drain_actions_sorted()[0].observer_entity_id, 1);
    }

    #[test]
    fn handle_occluded_result_increments_occluded_count() {
        let handler = VisibilityFeedbackHandler::new();
        handler.handle(&vis_result(1, 2, false, 0.0)).unwrap();
        assert_eq!(handler.occluded_count(), 1);
    }

    #[test]
    fn invalid_entities_are_rejected_and_counted() {
        let handler = VisibilityFeedbackHandler::new();
        assert!(handler.handle(&vis_result(0, 2, true, 5.0)).is_err());
        assert!(handler.handle(&vis_result(1, 0, true, 5.0)).is_err());
        assert!(handler.handle(&vis_result(1, 1, true, 5.0)).is_err());
        assert_eq!(handler.validation_failure_count(), 3);
    }

    #[test]
    fn invalid_distance_returns_err() {
        let handler = VisibilityFeedbackHandler::new();
        assert!(handler.handle(&vis_result(1, 2, false, -1.0)).is_err());
        assert!(handler.handle(&vis_result(1, 2, false, f32::NAN)).is_err());
    }

    #[test]
    fn result_expiry_is_exposed() {
        let handler = VisibilityFeedbackHandler::new();
        handler.handle(&vis_result(1, 2, true, 10.0)).unwrap();
        assert_eq!(handler.expire_results(3), 1);
        assert_eq!(handler.stored_result_count(), 0);
    }
}
