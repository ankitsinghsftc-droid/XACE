//! # Feedback Validator
//!
//! Validates the structural integrity of `FeedbackMessage` values before
//! they are routed to handlers. A validated message guarantees:
//!
//! - `feedback_type` discriminant is within the known range (0–9)
//! - `entity_id` is non-zero for feedback types that require an entity
//! - `generated_frame` is monotonically non-decreasing within a session
//! - `payload_json` is non-empty and parses as valid JSON
//! - The message is not a duplicate (same frame + entity + type seen before)
//!
//! ## Why Validate Before Routing
//! The engine adapter is not part of the authoritative XACE runtime. Its
//! output is engine-generated and could be malformed due to:
//! - Engine adapter bugs (wrong JSON schema)
//! - Version mismatches (field name changes)
//! - Corrupted SHM or TCP frames
//! - Adversarial input (security boundary — engine adapter is a client)
//!
//! Validation here means handlers never receive malformed input and
//! can assume all preconditions hold without defensive checks.
//!
//! ## Non-Fatal Policy
//! All validation failures are `RecoverableError` — one bad message
//! does not halt the simulation. It is logged and skipped.
//! The session continues with the next message.

use std::collections::{BTreeSet, VecDeque};

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::FeedbackMessage;

use crate::feedback_message::FeedbackMessageExt;
use crate::feedback_type_enum::FeedbackTypeExt;

type DedupeKey = (u64, u64, u8, u64);

// ── Validation Configuration ──────────────────────────────────────────────────

/// Configuration for the `FeedbackValidator`.
#[derive(Debug, Clone)]
pub struct ValidatorConfig {
    /// Whether to reject messages whose `generated_frame` is less than
    /// the last-seen frame. Out-of-order feedback is uncommon but possible
    /// when the engine adapter batches frames with different timestamps.
    /// Default: false — accept out-of-order frames (engines may batch).
    pub reject_out_of_order_frames: bool,

    /// Whether to reject duplicate messages (same frame + entity + type).
    /// Default: true — duplicates are always a bug.
    pub reject_duplicates: bool,

    /// Whether to validate `payload_json` as syntactically valid JSON.
    /// Slightly expensive for large payloads. Default: true.
    pub validate_json_syntax: bool,

    /// Entity types that require a non-zero entity_id.
    /// PerformanceMetrics and AssetResolutionUpdate use entity_id=0.
    /// Default: all types except those two.
    pub require_nonzero_entity_for_all_types: bool,

    /// Maximum accepted JSON payload size in bytes.
    pub max_payload_bytes: usize,

    /// Maximum dedupe keys retained before oldest keys are evicted.
    pub max_dedupe_keys: usize,
}

impl Default for ValidatorConfig {
    fn default() -> Self {
        Self {
            reject_out_of_order_frames: false,
            reject_duplicates: true,
            validate_json_syntax: true,
            require_nonzero_entity_for_all_types: false,
            max_payload_bytes: 256 * 1024,
            max_dedupe_keys: 65_536,
        }
    }
}

// ── Validation Result ─────────────────────────────────────────────────────────

/// The outcome of validating one `FeedbackMessage`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValidationOutcome {
    /// Message passed all checks. Safe to route.
    Valid,
    /// Message failed one or more checks. Skip and log.
    Invalid { reason: String },
}

impl ValidationOutcome {
    pub fn is_valid(&self) -> bool {
        matches!(self, ValidationOutcome::Valid)
    }
}

// ── Validator Metrics ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Default)]
pub struct ValidatorMetrics {
    pub messages_checked: u64,
    pub messages_valid: u64,
    pub messages_invalid: u64,
    pub empty_payload_rejections: u64,
    pub invalid_json_rejections: u64,
    pub duplicate_rejections: u64,
    pub out_of_order_rejections: u64,
    pub null_entity_rejections: u64,
    pub oversized_payload_rejections: u64,
    pub dedupe_evictions: u64,
}

// ── Feedback Validator ────────────────────────────────────────────────────────

/// Validates `FeedbackMessage` values before they enter the handler pipeline.
///
/// Stateful — tracks last-seen frame and duplicate detection across calls.
/// One instance per tick drain — create fresh for each `drain_sorted()` call
/// or maintain across the session for duplicate detection across ticks.
pub struct FeedbackValidator {
    config: ValidatorConfig,

    /// Last `generated_frame` seen. Used for out-of-order detection.
    last_frame: u64,

    /// Deduplication set: (generated_frame, entity_id, feedback_type_u8, payload_hash).
    /// BTreeSet for deterministic iteration if inspection is needed (D11).
    seen: BTreeSet<DedupeKey>,

    /// Insertion order for bounded dedupe retention.
    seen_order: VecDeque<DedupeKey>,

    metrics: ValidatorMetrics,
}

impl FeedbackValidator {
    // ── Construction ──────────────────────────────────────────────────────────

    pub fn new(config: ValidatorConfig) -> Self {
        Self {
            config,
            last_frame: 0,
            seen: BTreeSet::new(),
            seen_order: VecDeque::new(),
            metrics: ValidatorMetrics::default(),
        }
    }

    pub fn with_defaults() -> Self {
        Self::new(ValidatorConfig::default())
    }

    // ── Primary API ───────────────────────────────────────────────────────────

    /// Validates a single `FeedbackMessage`.
    ///
    /// Returns `ValidationOutcome::Valid` if all checks pass.
    /// Returns `ValidationOutcome::Invalid { reason }` for the first
    /// failing check — subsequent checks are skipped (fail-fast).
    pub fn validate(&mut self, msg: &FeedbackMessage) -> ValidationOutcome {
        self.metrics.messages_checked += 1;

        // ── Check 1: payload_json non-empty ───────────────────────────────
        if msg.payload_json.is_empty() {
            self.metrics.messages_invalid += 1;
            self.metrics.empty_payload_rejections += 1;
            return ValidationOutcome::Invalid {
                reason: format!(
                    "FeedbackMessage payload_json is empty for type {:?} entity={}",
                    msg.feedback_type, msg.entity_id
                ),
            };
        }

        if msg.payload_size_bytes() > self.config.max_payload_bytes {
            self.metrics.messages_invalid += 1;
            self.metrics.oversized_payload_rejections += 1;
            return ValidationOutcome::Invalid {
                reason: format!(
                    "FeedbackMessage payload_json too large for type {:?}: {} bytes > {} bytes",
                    msg.feedback_type,
                    msg.payload_size_bytes(),
                    self.config.max_payload_bytes
                ),
            };
        }

        // ── Check 2: JSON syntax ──────────────────────────────────────────
        if self.config.validate_json_syntax {
            if let Err(e) = serde_json::from_str::<serde_json::Value>(&msg.payload_json) {
                self.metrics.messages_invalid += 1;
                self.metrics.invalid_json_rejections += 1;
                return ValidationOutcome::Invalid {
                    reason: format!(
                        "FeedbackMessage payload_json invalid JSON for type {:?}: {}",
                        msg.feedback_type, e
                    ),
                };
            }
        }

        // ── Check 3: entity_id non-zero for entity-specific types ─────────
        if self.config.require_nonzero_entity_for_all_types
            || msg.feedback_type.requires_entity_id()
        {
            if msg.entity_id == 0 {
                self.metrics.messages_invalid += 1;
                self.metrics.null_entity_rejections += 1;
                return ValidationOutcome::Invalid {
                    reason: format!(
                        "FeedbackMessage entity_id=0 for type {:?} which requires a valid entity",
                        msg.feedback_type
                    ),
                };
            }
        }

        // ── Check 4: Out-of-order frames ──────────────────────────────────
        if self.config.reject_out_of_order_frames && msg.generated_frame < self.last_frame {
            self.metrics.messages_invalid += 1;
            self.metrics.out_of_order_rejections += 1;
            return ValidationOutcome::Invalid {
                reason: format!(
                    "FeedbackMessage generated_frame {} is before last-seen frame {}",
                    msg.generated_frame, self.last_frame
                ),
            };
        }

        // ── Check 5: Duplicate detection ──────────────────────────────────
        if self.config.reject_duplicates {
            let key = msg.dedupe_key();
            if self.seen.contains(&key) {
                self.metrics.messages_invalid += 1;
                self.metrics.duplicate_rejections += 1;
                return ValidationOutcome::Invalid {
                    reason: format!(
                        "Duplicate FeedbackMessage: type={:?} entity={} frame={}",
                        msg.feedback_type, msg.entity_id, msg.generated_frame
                    ),
                };
            }
            self.seen.insert(key);
            self.seen_order.push_back(key);
            self.enforce_dedupe_capacity();
        }

        // All checks passed
        if msg.generated_frame > self.last_frame {
            self.last_frame = msg.generated_frame;
        }
        self.metrics.messages_valid += 1;
        ValidationOutcome::Valid
    }

    /// Validates a batch of messages, returning only the valid ones.
    ///
    /// Invalid messages are logged to stderr (non-fatal).
    /// Returns the valid subset in the original order.
    pub fn filter_valid(&mut self, messages: Vec<FeedbackMessage>) -> Vec<FeedbackMessage> {
        messages
            .into_iter()
            .filter(|msg| {
                let outcome = self.validate(msg);
                if let ValidationOutcome::Invalid { reason } = &outcome {
                    eprintln!("[WARN] FeedbackValidator: {}", reason);
                }
                outcome.is_valid()
            })
            .collect()
    }

    /// Validates and returns an XaceError for invalid messages.
    ///
    /// Convenience wrapper for callers that want errors rather than filtering.
    pub fn validate_or_err(&mut self, msg: &FeedbackMessage) -> Result<(), XaceError> {
        match self.validate(msg) {
            ValidationOutcome::Valid => Ok(()),
            ValidationOutcome::Invalid { reason } => Err(XaceError::RecoverableError {
                message: reason,
                context: ErrorContext::new("FeedbackValidator", "validate_or_err"),
                max_retries: 0,
                retry_count: 0,
            }),
        }
    }

    // ── State Management ──────────────────────────────────────────────────────

    /// Resets frame tracking and duplicate set for a new tick.
    ///
    /// Call at the start of each tick drain to clear duplicate memory
    /// from the previous tick. Frame-tracking continues from last_frame.
    pub fn reset_for_next_tick(&mut self) {
        self.seen.clear();
        self.seen_order.clear();
        // last_frame is intentionally NOT reset — cross-tick out-of-order detection
    }

    /// Full reset — clears all state.
    /// Use on session restart or transport reconnect.
    pub fn reset_all(&mut self) {
        self.seen.clear();
        self.seen_order.clear();
        self.last_frame = 0;
        self.metrics = ValidatorMetrics::default();
    }

    // ── Inspection ────────────────────────────────────────────────────────────

    pub fn metrics(&self) -> &ValidatorMetrics {
        &self.metrics
    }

    pub fn last_seen_frame(&self) -> u64 {
        self.last_frame
    }

    pub fn dedupe_set_size(&self) -> usize {
        self.seen.len()
    }

    fn enforce_dedupe_capacity(&mut self) {
        while self.seen.len() > self.config.max_dedupe_keys {
            if let Some(oldest) = self.seen_order.pop_front() {
                if self.seen.remove(&oldest) {
                    self.metrics.dedupe_evictions += 1;
                }
            } else {
                break;
            }
        }
    }
}

// ── Helper: Entity Requirement ────────────────────────────────────────────────

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::FeedbackType;

    fn valid_msg(ft: FeedbackType, entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: ft,
            entity_id,
            generated_frame: frame,
            payload_json: "{}".into(),
        }
    }

    fn invalid_json_msg(ft: FeedbackType, entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: ft,
            entity_id,
            generated_frame: frame,
            payload_json: "not json".into(),
        }
    }

    fn empty_payload_msg(ft: FeedbackType) -> FeedbackMessage {
        FeedbackMessage {
            feedback_type: ft,
            entity_id: 1,
            generated_frame: 1,
            payload_json: String::new(),
        }
    }

    // ── Valid Messages ────────────────────────────────────────────────────────

    #[test]
    fn valid_message_passes() {
        let mut v = FeedbackValidator::with_defaults();
        let outcome = v.validate(&valid_msg(FeedbackType::PhysicsSettled, 1, 1));
        assert!(outcome.is_valid());
        assert_eq!(v.metrics().messages_valid, 1);
    }

    #[test]
    fn performance_metrics_with_entity_zero_valid() {
        let mut v = FeedbackValidator::with_defaults();
        // PerformanceMetrics doesn't require non-zero entity
        let outcome = v.validate(&valid_msg(FeedbackType::PerformanceMetrics, 0, 1));
        assert!(outcome.is_valid());
    }

    #[test]
    fn asset_resolution_with_entity_zero_valid() {
        let mut v = FeedbackValidator::with_defaults();
        let outcome = v.validate(&valid_msg(FeedbackType::AssetResolutionUpdate, 0, 1));
        assert!(outcome.is_valid());
    }

    // ── Empty Payload ─────────────────────────────────────────────────────────

    #[test]
    fn empty_payload_rejected() {
        let mut v = FeedbackValidator::with_defaults();
        let outcome = v.validate(&empty_payload_msg(FeedbackType::PhysicsSettled));
        assert!(!outcome.is_valid());
        assert_eq!(v.metrics().empty_payload_rejections, 1);
    }

    // ── Invalid JSON ──────────────────────────────────────────────────────────

    #[test]
    fn invalid_json_rejected() {
        let mut v = FeedbackValidator::with_defaults();
        let outcome = v.validate(&invalid_json_msg(FeedbackType::PhysicsSettled, 1, 1));
        assert!(!outcome.is_valid());
        assert_eq!(v.metrics().invalid_json_rejections, 1);
    }

    #[test]
    fn invalid_json_not_rejected_when_syntax_check_disabled() {
        let mut v = FeedbackValidator::new(ValidatorConfig {
            validate_json_syntax: false,
            ..Default::default()
        });
        let outcome = v.validate(&invalid_json_msg(FeedbackType::PerformanceMetrics, 0, 1));
        assert!(outcome.is_valid());
    }

    // ── Null Entity ───────────────────────────────────────────────────────────

    #[test]
    fn entity_zero_rejected_for_physics_settled() {
        let mut v = FeedbackValidator::with_defaults();
        let outcome = v.validate(&valid_msg(FeedbackType::PhysicsSettled, 0, 1));
        assert!(!outcome.is_valid());
        assert_eq!(v.metrics().null_entity_rejections, 1);
    }

    #[test]
    fn entity_zero_allowed_for_device_level_input_feedback() {
        let mut v = FeedbackValidator::with_defaults();
        let outcome = v.validate(&valid_msg(FeedbackType::InputDeviceUpdate, 0, 1));
        assert!(outcome.is_valid());
    }

    // ── Duplicate Detection ───────────────────────────────────────────────────

    #[test]
    fn duplicate_message_rejected() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&valid_msg(FeedbackType::AnimationStateUpdate, 1, 5));
        let outcome = v.validate(&valid_msg(FeedbackType::AnimationStateUpdate, 1, 5));
        assert!(!outcome.is_valid());
        assert_eq!(v.metrics().duplicate_rejections, 1);
    }

    #[test]
    fn same_type_different_entity_not_duplicate() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&valid_msg(FeedbackType::PhysicsSettled, 1, 5));
        let outcome = v.validate(&valid_msg(FeedbackType::PhysicsSettled, 2, 5));
        assert!(outcome.is_valid());
    }

    #[test]
    fn same_type_same_entity_different_frame_not_duplicate() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&valid_msg(FeedbackType::AnimationStateUpdate, 1, 5));
        let outcome = v.validate(&valid_msg(FeedbackType::AnimationStateUpdate, 1, 6));
        assert!(outcome.is_valid());
    }

    #[test]
    fn same_frame_entity_type_with_different_payload_is_not_duplicate() {
        let mut v = FeedbackValidator::with_defaults();
        let mut a = valid_msg(FeedbackType::EngineError, 1, 5);
        a.payload_json = r#"{"error":"a"}"#.into();
        let mut b = valid_msg(FeedbackType::EngineError, 1, 5);
        b.payload_json = r#"{"error":"b"}"#.into();

        assert!(v.validate(&a).is_valid());
        assert!(v.validate(&b).is_valid());
    }

    #[test]
    fn oversized_payload_rejected() {
        let mut v = FeedbackValidator::new(ValidatorConfig {
            max_payload_bytes: 1,
            ..Default::default()
        });
        let outcome = v.validate(&valid_msg(FeedbackType::PerformanceMetrics, 0, 1));
        assert!(!outcome.is_valid());
        assert_eq!(v.metrics().oversized_payload_rejections, 1);
    }

    #[test]
    fn reset_for_next_tick_clears_duplicates() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&valid_msg(FeedbackType::AnimationStateUpdate, 1, 5));
        v.reset_for_next_tick();
        // Same message should be valid again after tick reset
        let outcome = v.validate(&valid_msg(FeedbackType::AnimationStateUpdate, 1, 5));
        assert!(outcome.is_valid(), "Duplicate allowed after tick reset");
    }

    // ── Out-of-Order ──────────────────────────────────────────────────────────

    #[test]
    fn out_of_order_rejected_when_configured() {
        let mut v = FeedbackValidator::new(ValidatorConfig {
            reject_out_of_order_frames: true,
            reject_duplicates: false,
            ..Default::default()
        });
        v.validate(&valid_msg(FeedbackType::PhysicsSettled, 1, 10));
        let outcome = v.validate(&valid_msg(FeedbackType::PhysicsSettled, 2, 5)); // frame 5 < 10
        assert!(!outcome.is_valid());
        assert_eq!(v.metrics().out_of_order_rejections, 1);
    }

    #[test]
    fn out_of_order_allowed_by_default() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&valid_msg(FeedbackType::PhysicsSettled, 1, 10));
        let outcome = v.validate(&valid_msg(FeedbackType::PhysicsSettled, 2, 5));
        assert!(outcome.is_valid());
    }

    // ── filter_valid ──────────────────────────────────────────────────────────

    #[test]
    fn filter_valid_keeps_only_valid_messages() {
        let mut v = FeedbackValidator::with_defaults();
        let messages = vec![
            valid_msg(FeedbackType::PhysicsSettled, 1, 1),
            empty_payload_msg(FeedbackType::AudioComplete),
            valid_msg(FeedbackType::AnimationStateUpdate, 2, 2),
        ];
        let valid = v.filter_valid(messages);
        assert_eq!(valid.len(), 2);
    }

    // ── Metrics ───────────────────────────────────────────────────────────────

    #[test]
    fn metrics_count_valid_and_invalid() {
        let mut v = FeedbackValidator::with_defaults();
        v.validate(&valid_msg(FeedbackType::PhysicsSettled, 1, 1));
        v.validate(&valid_msg(FeedbackType::AudioComplete, 2, 2));
        v.validate(&empty_payload_msg(FeedbackType::EngineError));

        let m = v.metrics();
        assert_eq!(m.messages_checked, 3);
        assert_eq!(m.messages_valid, 2);
        assert_eq!(m.messages_invalid, 1);
    }
}
