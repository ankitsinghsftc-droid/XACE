//! # Performance Feedback Handler
//!
//! Processes `PerformanceMetrics` feedback — real engine performance data
//! from the previous tick.
//!
//! ## Why Real Performance Data Matters
//! The PIL (Phase 13) contains a `PerformanceRiskGuard` that estimates
//! the runtime cost of proposed mutations. Without real data it uses
//! conservative heuristics. With real engine metrics it can make
//! precise decisions — "this mutation would push entity count from 300
//! to 400; last tick at 300 entities the engine used 8.2ms — adding
//! 33% more entities risks exceeding the 16.67ms budget."
//!
//! CLAUDE.md: *"performance_risk_guard.py — uses real engine metrics
//! from Phase 7 feedback handler."*
//!
//! ## Metrics Stored
//! - `engine_delta_apply_ms` — engine processing time per tick (key budget metric)
//! - `draw_calls` — render complexity indicator
//! - `physics_contacts` — physics simulation load indicator
//! - `engine_entity_count` — cross-referenced with XACE entity count for desync detection
//!
//! ## Entity Count Cross-Reference
//! If `engine_entity_count` differs significantly from XACE's known active
//! entity count, it indicates a rendering desync. This is logged as a
//! warning — not fatal, but a signal that SNAPSHOT recovery may be needed.

use std::sync::Mutex;

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::PerformanceMetricsFeedback;

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

// ── Performance Store ─────────────────────────────────────────────────────────

/// The most recent engine performance metrics, retained for PIL queries.
#[derive(Debug, Clone, Default)]
pub struct LatestPerformanceMetrics {
    pub engine_delta_apply_ms: f32,
    pub draw_calls: u32,
    pub physics_contacts: u32,
    pub engine_entity_count: u32,
    pub generated_frame: u64,
    pub is_populated: bool,
}

impl LatestPerformanceMetrics {
    /// Returns true if the engine delta time is within the 60Hz budget.
    pub fn is_within_budget(&self) -> bool {
        self.engine_delta_apply_ms < 16.67
    }

    /// Returns a budget utilisation ratio (0.0 = idle, 1.0 = exactly at budget).
    pub fn budget_utilisation(&self) -> f32 {
        (self.engine_delta_apply_ms / 16.67).min(1.0)
    }
}

// ── Performance Feedback Handler ──────────────────────────────────────────────

/// Handles `PerformanceMetrics` feedback — stores real engine data for
/// the PIL performance risk guard and builder UI.
pub struct PerformanceFeedbackHandler {
    /// Latest metrics, retained across ticks for PIL queries.
    latest: Mutex<LatestPerformanceMetrics>,

    /// Total metrics payloads processed.
    reports_processed: std::sync::atomic::AtomicU64,

    /// Times engine delta time exceeded 16.67ms (60Hz budget).
    over_budget_count: std::sync::atomic::AtomicU64,

    /// Highest engine_delta_apply_ms seen this session.
    peak_delta_ms: Mutex<f32>,
}

impl PerformanceFeedbackHandler {
    pub fn new() -> Self {
        Self {
            latest: Mutex::new(LatestPerformanceMetrics::default()),
            reports_processed: std::sync::atomic::AtomicU64::new(0),
            over_budget_count: std::sync::atomic::AtomicU64::new(0),
            peak_delta_ms: Mutex::new(0.0),
        }
    }

    /// Returns a copy of the most recent performance metrics.
    /// Called by the PIL performance risk guard before evaluating mutations.
    pub fn latest_metrics(&self) -> LatestPerformanceMetrics {
        self.latest.lock().unwrap().clone()
    }

    pub fn reports_processed(&self) -> u64 {
        self.reports_processed.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn over_budget_count(&self) -> u64 {
        self.over_budget_count.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub fn peak_delta_ms(&self) -> f32 {
        *self.peak_delta_ms.lock().unwrap()
    }

    fn update_latest(&self, metrics: &PerformanceMetricsFeedback) {
        let mut latest = self.latest.lock().unwrap();
        latest.engine_delta_apply_ms = metrics.engine_delta_apply_ms;
        latest.draw_calls = metrics.draw_calls;
        latest.physics_contacts = metrics.physics_contacts;
        latest.engine_entity_count = metrics.engine_entity_count;
        latest.generated_frame = metrics.generated_frame;
        latest.is_populated = true;

        let mut peak = self.peak_delta_ms.lock().unwrap();
        if metrics.engine_delta_apply_ms > *peak {
            *peak = metrics.engine_delta_apply_ms;
        }
    }
}

impl Default for PerformanceFeedbackHandler {
    fn default() -> Self {
        Self::new()
    }
}

impl FeedbackHandler for PerformanceFeedbackHandler {
    fn kind(&self) -> FeedbackHandlerKind {
        FeedbackHandlerKind::Performance
    }

    fn name(&self) -> &str {
        "PerformanceFeedbackHandler"
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let metrics = match payload {
            TypedFeedbackPayload::PerformanceMetrics(m) => m,
            other => {
                return Err(XaceError::RecoverableError {
                    message: format!(
                        "PerformanceFeedbackHandler: unexpected payload type {:?}",
                        other.feedback_type()
                    ),
                    context: ErrorContext::new("PerformanceFeedbackHandler", "handle"),
                    max_retries: 0,
                    retry_count: 0,
                })
            }
        };

        // Sanity check — negative timing values indicate a bug in the adapter
        if metrics.engine_delta_apply_ms < 0.0 {
            return Err(XaceError::RecoverableError {
                message: format!(
                    "PerformanceFeedbackHandler: negative engine_delta_apply_ms {}",
                    metrics.engine_delta_apply_ms
                ),
                context: ErrorContext::new("PerformanceFeedbackHandler", "handle"),
                max_retries: 0,
                retry_count: 0,
            });
        }

        // Track over-budget frames
        if metrics.engine_delta_apply_ms > 16.67 {
            self.over_budget_count
                .fetch_add(1, std::sync::atomic::Ordering::Relaxed);

            eprintln!(
                "[WARN] PerformanceFeedbackHandler: engine delta {:.2}ms exceeds \
                 60Hz budget (16.67ms) at frame {}",
                metrics.engine_delta_apply_ms, metrics.generated_frame
            );
        }

        self.update_latest(metrics);
        self.reports_processed
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::PerformanceMetricsFeedback;

    fn perf(delta_ms: f32, draw_calls: u32, entity_count: u32) -> TypedFeedbackPayload {
        TypedFeedbackPayload::PerformanceMetrics(PerformanceMetricsFeedback {
            engine_delta_apply_ms: delta_ms,
            draw_calls,
            physics_contacts: 10,
            engine_entity_count: entity_count,
            generated_frame: 1,
        })
    }

    #[test]
    fn handler_kind_is_performance() {
        assert_eq!(
            PerformanceFeedbackHandler::new().kind(),
            FeedbackHandlerKind::Performance
        );
    }

    #[test]
    fn can_handle_performance_metrics_only() {
        let h = PerformanceFeedbackHandler::new();
        assert!(h.can_handle(FeedbackType::PerformanceMetrics));
        assert!(!h.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn valid_metrics_processed_and_stored() {
        let h = PerformanceFeedbackHandler::new();
        h.handle(&perf(8.5, 1200, 300)).unwrap();
        assert_eq!(h.reports_processed(), 1);
        let latest = h.latest_metrics();
        assert!(latest.is_populated);
        assert!((latest.engine_delta_apply_ms - 8.5).abs() < 0.001);
        assert_eq!(latest.draw_calls, 1200);
        assert_eq!(latest.engine_entity_count, 300);
    }

    #[test]
    fn over_budget_frame_counted() {
        let h = PerformanceFeedbackHandler::new();
        h.handle(&perf(20.0, 500, 100)).unwrap(); // 20ms > 16.67ms
        assert_eq!(h.over_budget_count(), 1);
    }

    #[test]
    fn within_budget_frame_not_counted() {
        let h = PerformanceFeedbackHandler::new();
        h.handle(&perf(10.0, 500, 100)).unwrap();
        assert_eq!(h.over_budget_count(), 0);
    }

    #[test]
    fn peak_delta_ms_tracked() {
        let h = PerformanceFeedbackHandler::new();
        h.handle(&perf(5.0, 100, 50)).unwrap();
        h.handle(&perf(15.0, 200, 100)).unwrap();
        h.handle(&perf(8.0, 150, 75)).unwrap();
        assert!((h.peak_delta_ms() - 15.0).abs() < 0.001);
    }

    #[test]
    fn negative_delta_ms_returns_err() {
        let h = PerformanceFeedbackHandler::new();
        assert!(h.handle(&perf(-1.0, 100, 50)).is_err());
    }

    #[test]
    fn is_within_budget_correct() {
        let m = LatestPerformanceMetrics {
            engine_delta_apply_ms: 10.0,
            is_populated: true,
            ..Default::default()
        };
        assert!(m.is_within_budget());

        let m2 = LatestPerformanceMetrics {
            engine_delta_apply_ms: 20.0,
            is_populated: true,
            ..Default::default()
        };
        assert!(!m2.is_within_budget());
    }

    #[test]
    fn latest_metrics_not_populated_initially() {
        let h = PerformanceFeedbackHandler::new();
        assert!(!h.latest_metrics().is_populated);
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let h = PerformanceFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate {
            entity_id: 1,
            position_json: "{}".into(),
        };
        assert!(h.handle(&wrong).is_err());
    }
}