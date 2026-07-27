//! Performance feedback handler.
//!
//! Performance feedback feeds the PIL `PerformanceRiskGuard` with real engine
//! data. This handler keeps deterministic rolling metrics and exposes a compact
//! map containing `avg_tick_ms`, matching the guard contract in
//! `performance_risk_guard.py`.

use std::collections::{BTreeMap, VecDeque};
use std::sync::{Mutex, MutexGuard};

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::feedback_payload::{FeedbackType, PerformanceMetricsFeedback};

use crate::feedback_message::TypedFeedbackPayload;
use crate::feedback_router::FeedbackHandler;
use crate::feedback_type_enum::FeedbackHandlerKind;

pub const DEFAULT_FRAME_BUDGET_MS: f32 = 16.67;
pub const DEFAULT_HISTORY_LIMIT: usize = 240;

#[derive(Debug, Clone, Default, PartialEq)]
pub struct LatestPerformanceMetrics {
    pub engine_delta_apply_ms: f32,
    pub draw_calls: u32,
    pub physics_contacts: u32,
    pub engine_entity_count: u32,
    pub generated_frame: u64,
    pub is_populated: bool,
}

impl LatestPerformanceMetrics {
    pub fn is_within_budget(&self) -> bool {
        self.engine_delta_apply_ms <= DEFAULT_FRAME_BUDGET_MS
    }

    pub fn budget_utilisation(&self) -> f32 {
        if self.engine_delta_apply_ms <= 0.0 {
            0.0
        } else {
            (self.engine_delta_apply_ms / DEFAULT_FRAME_BUDGET_MS).min(1.0)
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PerformanceSample {
    pub engine_delta_apply_ms: f32,
    pub draw_calls: u32,
    pub physics_contacts: u32,
    pub engine_entity_count: u32,
    pub generated_frame: u64,
}

impl PerformanceSample {
    pub fn from_feedback(metrics: &PerformanceMetricsFeedback) -> Self {
        Self {
            engine_delta_apply_ms: metrics.engine_delta_apply_ms,
            draw_calls: metrics.draw_calls,
            physics_contacts: metrics.physics_contacts,
            engine_entity_count: metrics.engine_entity_count,
            generated_frame: metrics.generated_frame,
        }
    }

    pub fn sort_key(&self) -> (u64, u32, u32, u32) {
        (
            self.generated_frame,
            self.engine_entity_count,
            self.draw_calls,
            self.physics_contacts,
        )
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct PerformanceSummary {
    pub sample_count: usize,
    pub avg_tick_ms: f32,
    pub peak_tick_ms: f32,
    pub latest_tick_ms: f32,
    pub avg_draw_calls: f32,
    pub avg_physics_contacts: f32,
    pub latest_engine_entity_count: u32,
    pub over_budget_count: u64,
}

impl PerformanceSummary {
    pub fn for_guard(&self) -> BTreeMap<String, f32> {
        BTreeMap::from([
            ("avg_tick_ms".to_string(), self.avg_tick_ms),
            ("peak_tick_ms".to_string(), self.peak_tick_ms),
            ("latest_tick_ms".to_string(), self.latest_tick_ms),
            ("avg_draw_calls".to_string(), self.avg_draw_calls),
            (
                "avg_physics_contacts".to_string(),
                self.avg_physics_contacts,
            ),
            (
                "latest_engine_entity_count".to_string(),
                self.latest_engine_entity_count as f32,
            ),
        ])
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PerformanceFeedbackMetrics {
    pub reports_processed: u64,
    pub over_budget_count: u64,
    pub validation_failures: u64,
    pub poison_recoveries: u64,
}

pub struct PerformanceFeedbackHandler {
    latest: Mutex<LatestPerformanceMetrics>,
    samples: Mutex<VecDeque<PerformanceSample>>,
    history_limit: usize,
    metrics: Mutex<PerformanceFeedbackMetrics>,
}

impl PerformanceFeedbackHandler {
    pub fn new() -> Self {
        Self::with_history_limit(DEFAULT_HISTORY_LIMIT)
    }

    pub fn with_history_limit(history_limit: usize) -> Self {
        Self {
            latest: Mutex::new(LatestPerformanceMetrics::default()),
            samples: Mutex::new(VecDeque::new()),
            history_limit: history_limit.max(1),
            metrics: Mutex::new(PerformanceFeedbackMetrics::default()),
        }
    }

    pub fn latest_metrics(&self) -> LatestPerformanceMetrics {
        self.lock_latest().clone()
    }

    pub fn reports_processed(&self) -> u64 {
        self.metrics().reports_processed
    }

    pub fn over_budget_count(&self) -> u64 {
        self.metrics().over_budget_count
    }

    pub fn peak_delta_ms(&self) -> f32 {
        self.summary().peak_tick_ms
    }

    pub fn metrics(&self) -> PerformanceFeedbackMetrics {
        self.lock_metrics().clone()
    }

    pub fn samples_sorted(&self) -> Vec<PerformanceSample> {
        let mut samples: Vec<_> = self.lock_samples().iter().cloned().collect();
        samples.sort_by_key(PerformanceSample::sort_key);
        samples
    }

    pub fn summary(&self) -> PerformanceSummary {
        let samples = self.lock_samples();
        let sample_count = samples.len();
        if sample_count == 0 {
            return PerformanceSummary::default();
        }

        let mut total_ms = 0.0f32;
        let mut total_draw_calls = 0u64;
        let mut total_contacts = 0u64;
        let mut peak_tick_ms = 0.0f32;
        let mut latest = samples.front().expect("non-empty samples");
        for sample in samples.iter() {
            total_ms += sample.engine_delta_apply_ms;
            total_draw_calls += sample.draw_calls as u64;
            total_contacts += sample.physics_contacts as u64;
            if sample.engine_delta_apply_ms > peak_tick_ms {
                peak_tick_ms = sample.engine_delta_apply_ms;
            }
            if sample.generated_frame >= latest.generated_frame {
                latest = sample;
            }
        }

        PerformanceSummary {
            sample_count,
            avg_tick_ms: total_ms / sample_count as f32,
            peak_tick_ms,
            latest_tick_ms: latest.engine_delta_apply_ms,
            avg_draw_calls: total_draw_calls as f32 / sample_count as f32,
            avg_physics_contacts: total_contacts as f32 / sample_count as f32,
            latest_engine_entity_count: latest.engine_entity_count,
            over_budget_count: self.over_budget_count(),
        }
    }

    pub fn guard_metrics(&self) -> BTreeMap<String, f32> {
        self.summary().for_guard()
    }

    fn validate_sample(&self, metrics: &PerformanceMetricsFeedback) -> Result<(), XaceError> {
        if !metrics.engine_delta_apply_ms.is_finite() || metrics.engine_delta_apply_ms < 0.0 {
            return Err(self.validation_error(
                "handle",
                format!(
                    "engine_delta_apply_ms is invalid: {}",
                    metrics.engine_delta_apply_ms
                ),
            ));
        }
        Ok(())
    }

    fn push_sample(&self, sample: PerformanceSample) {
        let mut samples = self.lock_samples();
        samples.push_back(sample);
        while samples.len() > self.history_limit {
            samples.pop_front();
        }
    }

    fn update_latest(&self, metrics: &PerformanceMetricsFeedback) {
        let mut latest = self.lock_latest();
        latest.engine_delta_apply_ms = metrics.engine_delta_apply_ms;
        latest.draw_calls = metrics.draw_calls;
        latest.physics_contacts = metrics.physics_contacts;
        latest.engine_entity_count = metrics.engine_entity_count;
        latest.generated_frame = metrics.generated_frame;
        latest.is_populated = true;
    }

    fn validation_error(&self, operation: &'static str, message: impl Into<String>) -> XaceError {
        self.lock_metrics().validation_failures += 1;
        recoverable(operation, message)
    }

    fn lock_latest(&self) -> MutexGuard<'_, LatestPerformanceMetrics> {
        match self.latest.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_samples(&self) -> MutexGuard<'_, VecDeque<PerformanceSample>> {
        match self.samples.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                self.lock_metrics().poison_recoveries += 1;
                poisoned.into_inner()
            }
        }
    }

    fn lock_metrics(&self) -> MutexGuard<'_, PerformanceFeedbackMetrics> {
        match self.metrics.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
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

    fn can_handle(&self, feedback_type: FeedbackType) -> bool {
        feedback_type == FeedbackType::PerformanceMetrics
    }

    fn handle(&self, payload: &TypedFeedbackPayload) -> Result<(), XaceError> {
        let metrics = match payload {
            TypedFeedbackPayload::PerformanceMetrics(metrics) => metrics,
            other => {
                return Err(recoverable(
                    "handle",
                    format!("unexpected payload type {:?}", other.feedback_type()),
                ))
            }
        };

        self.validate_sample(metrics)?;
        if metrics.engine_delta_apply_ms > DEFAULT_FRAME_BUDGET_MS {
            self.lock_metrics().over_budget_count += 1;
            log::warn!(
                "PerformanceFeedbackHandler: engine delta {:.2}ms exceeds {:.2}ms budget at frame {}",
                metrics.engine_delta_apply_ms,
                DEFAULT_FRAME_BUDGET_MS,
                metrics.generated_frame
            );
        }

        self.update_latest(metrics);
        self.push_sample(PerformanceSample::from_feedback(metrics));
        self.lock_metrics().reports_processed += 1;
        Ok(())
    }
}

fn recoverable(operation: &'static str, message: impl Into<String>) -> XaceError {
    XaceError::RecoverableError {
        message: format!("PerformanceFeedbackHandler: {}", message.into()),
        context: ErrorContext::new("PerformanceFeedbackHandler", operation),
        max_retries: 0,
        retry_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::wire::feedback_payload::{
        AudioPositionUpdateFeedback, FeedbackType, PerformanceMetricsFeedback,
    };

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
        let handler = PerformanceFeedbackHandler::new();
        assert!(handler.can_handle(FeedbackType::PerformanceMetrics));
        assert!(!handler.can_handle(FeedbackType::PhysicsSettled));
    }

    #[test]
    fn valid_metrics_processed_and_stored() {
        let handler = PerformanceFeedbackHandler::new();
        handler.handle(&perf(8.5, 1200, 300)).unwrap();

        assert_eq!(handler.reports_processed(), 1);
        let latest = handler.latest_metrics();
        assert!(latest.is_populated);
        assert!((latest.engine_delta_apply_ms - 8.5).abs() < 0.001);
        assert_eq!(latest.draw_calls, 1200);
        assert_eq!(latest.engine_entity_count, 300);
    }

    #[test]
    fn over_budget_frame_counted() {
        let handler = PerformanceFeedbackHandler::new();
        handler.handle(&perf(20.0, 500, 100)).unwrap();
        assert_eq!(handler.over_budget_count(), 1);
    }

    #[test]
    fn summary_and_guard_metrics_are_reported() {
        let handler = PerformanceFeedbackHandler::new();
        handler.handle(&perf(5.0, 100, 50)).unwrap();
        handler.handle(&perf(15.0, 200, 100)).unwrap();

        let summary = handler.summary();
        assert_eq!(summary.sample_count, 2);
        assert!((summary.avg_tick_ms - 10.0).abs() < 0.001);
        assert_eq!(handler.guard_metrics().get("avg_tick_ms"), Some(&10.0));
    }

    #[test]
    fn history_limit_is_enforced() {
        let handler = PerformanceFeedbackHandler::with_history_limit(2);
        handler.handle(&perf(1.0, 10, 1)).unwrap();
        handler.handle(&perf(2.0, 20, 2)).unwrap();
        handler.handle(&perf(3.0, 30, 3)).unwrap();

        assert_eq!(handler.samples_sorted().len(), 2);
        assert_eq!(handler.summary().latest_tick_ms, 3.0);
    }

    #[test]
    fn negative_or_non_finite_delta_ms_returns_err() {
        let handler = PerformanceFeedbackHandler::new();
        assert!(handler.handle(&perf(-1.0, 100, 50)).is_err());
        assert!(handler.handle(&perf(f32::NAN, 100, 50)).is_err());
    }

    #[test]
    fn is_within_budget_correct() {
        let metrics = LatestPerformanceMetrics {
            engine_delta_apply_ms: 10.0,
            is_populated: true,
            ..Default::default()
        };
        assert!(metrics.is_within_budget());

        let metrics = LatestPerformanceMetrics {
            engine_delta_apply_ms: 20.0,
            is_populated: true,
            ..Default::default()
        };
        assert!(!metrics.is_within_budget());
    }

    #[test]
    fn latest_metrics_not_populated_initially() {
        let handler = PerformanceFeedbackHandler::new();
        assert!(!handler.latest_metrics().is_populated);
    }

    #[test]
    fn wrong_payload_type_returns_err() {
        let handler = PerformanceFeedbackHandler::new();
        let wrong = TypedFeedbackPayload::AudioPositionUpdate(AudioPositionUpdateFeedback {
            entity_id: 1,
            position_json: "{}".into(),
            generated_frame: 1,
        });
        assert!(handler.handle(&wrong).is_err());
    }
}
