//! Thread-safe deterministic feedback buffer.
//!
//! Engine feedback may arrive on a transport thread, but the runtime may only
//! process it at tick boundaries. This buffer is the handoff point.

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};

use xace_core::entity_id::EntityID;
use xace_core::entity_metadata::Tick;
use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackPayload, FeedbackType};

use crate::feedback_message::FeedbackMessageExt;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct FeedbackBufferMetrics {
    pub total_appended: u64,
    pub total_drains: u64,
    pub total_drained: u64,
    pub empty_drain_ticks: u64,
    pub peak_pending: usize,
    pub clear_count: u64,
    pub dropped_over_capacity: u64,
    pub poison_recoveries: u64,
    pub per_type_pending: BTreeMap<u8, usize>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FeedbackBufferConfig {
    pub max_pending_messages: usize,
    pub drop_oldest_on_overflow: bool,
}

impl Default for FeedbackBufferConfig {
    fn default() -> Self {
        Self {
            max_pending_messages: 16 * 1024,
            drop_oldest_on_overflow: false,
        }
    }
}

struct BufferInner {
    messages: Vec<FeedbackMessage>,
    metrics: FeedbackBufferMetrics,
}

#[derive(Clone)]
pub struct FeedbackBuffer {
    inner: Arc<Mutex<BufferInner>>,
    config: FeedbackBufferConfig,
}

impl FeedbackBuffer {
    pub fn new() -> Self {
        Self::with_config(FeedbackBufferConfig::default())
    }

    pub fn with_config(config: FeedbackBufferConfig) -> Self {
        Self {
            inner: Arc::new(Mutex::new(BufferInner {
                messages: Vec::with_capacity(64),
                metrics: FeedbackBufferMetrics::default(),
            })),
            config,
        }
    }

    pub fn append(&self, message: FeedbackMessage) -> Result<(), FeedbackBufferOverflow> {
        self.append_batch(vec![message])
    }

    pub fn append_batch(
        &self,
        messages: Vec<FeedbackMessage>,
    ) -> Result<(), FeedbackBufferOverflow> {
        if messages.is_empty() {
            return Ok(());
        }

        let mut inner = self.lock();
        let incoming = messages.len();
        let pending = inner.messages.len();
        let max = self.config.max_pending_messages;

        if pending + incoming > max {
            let overflow = pending + incoming - max;
            if self.config.drop_oldest_on_overflow {
                let drop_count = overflow.min(inner.messages.len());
                inner.messages.drain(0..drop_count);
                inner.metrics.dropped_over_capacity += drop_count as u64;
            } else {
                inner.metrics.dropped_over_capacity += incoming as u64;
                return Err(FeedbackBufferOverflow {
                    pending,
                    incoming,
                    capacity: max,
                });
            }
        }

        for message in messages {
            *inner
                .metrics
                .per_type_pending
                .entry(message.feedback_type.as_u8())
                .or_insert(0) += 1;
            inner.messages.push(message);
        }
        inner.metrics.total_appended += incoming as u64;
        inner.metrics.peak_pending = inner.metrics.peak_pending.max(inner.messages.len());
        Ok(())
    }

    pub fn append_payload(&self, payload: FeedbackPayload) -> Result<(), FeedbackBufferOverflow> {
        self.append_batch(payload.messages)
    }

    /// Legacy infallible append used by older call sites. Overflow drops the
    /// entire incoming batch when configured as fail-closed.
    pub fn append_lossy(&self, message: FeedbackMessage) {
        let _ = self.append(message);
    }

    pub fn drain_sorted(&self) -> Vec<FeedbackMessage> {
        self.drain_matching(|_| true)
    }

    pub fn drain_payload_sorted(&self, tick: Tick) -> FeedbackPayload {
        let mut payload = FeedbackPayload::empty(tick);
        for message in self.drain_sorted() {
            payload.add_message(message);
        }
        payload.sort_in_place();
        payload
    }

    pub fn drain_type_sorted(&self, feedback_type: FeedbackType) -> Vec<FeedbackMessage> {
        self.drain_matching(|message| message.feedback_type == feedback_type)
    }

    pub fn drain_sorted_for_entity_range(
        &self,
        min_entity_id: EntityID,
        max_entity_id: EntityID,
    ) -> Vec<FeedbackMessage> {
        self.drain_matching(|message| message.entity_in_range(min_entity_id, max_entity_id))
    }

    pub fn pending_count(&self) -> usize {
        self.lock().messages.len()
    }

    pub fn is_empty(&self) -> bool {
        self.pending_count() == 0
    }

    pub fn clear(&self) {
        let mut inner = self.lock();
        inner.messages.clear();
        inner.metrics.per_type_pending.clear();
        inner.metrics.clear_count += 1;
    }

    pub fn metrics(&self) -> FeedbackBufferMetrics {
        self.lock().metrics.clone()
    }

    fn drain_matching(&self, keep: impl Fn(&FeedbackMessage) -> bool) -> Vec<FeedbackMessage> {
        let mut inner = self.lock();
        inner.metrics.total_drains += 1;

        if inner.messages.is_empty() {
            inner.metrics.empty_drain_ticks += 1;
            return Vec::new();
        }

        let mut drained = Vec::new();
        let mut retained = Vec::new();
        for message in std::mem::take(&mut inner.messages) {
            if keep(&message) {
                drained.push(message);
            } else {
                retained.push(message);
            }
        }
        retained.sort_by_key(FeedbackMessageExt::sort_key);
        drained.sort_by_key(FeedbackMessageExt::sort_key);
        inner.messages = retained;
        inner.metrics.total_drained += drained.len() as u64;
        inner.metrics.per_type_pending = count_by_type(&inner.messages);
        if drained.is_empty() {
            inner.metrics.empty_drain_ticks += 1;
        }
        drained
    }

    fn lock(&self) -> MutexGuard<'_, BufferInner> {
        match self.inner.lock() {
            Ok(guard) => guard,
            Err(poisoned) => {
                let mut guard = poisoned.into_inner();
                guard.metrics.poison_recoveries += 1;
                guard
            }
        }
    }
}

impl Default for FeedbackBuffer {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FeedbackBufferOverflow {
    pub pending: usize,
    pub incoming: usize,
    pub capacity: usize,
}

impl std::fmt::Display for FeedbackBufferOverflow {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "feedback buffer overflow: pending={} incoming={} capacity={}",
            self.pending, self.incoming, self.capacity
        )
    }
}

impl std::error::Error for FeedbackBufferOverflow {}

fn count_by_type(messages: &[FeedbackMessage]) -> BTreeMap<u8, usize> {
    let mut counts = BTreeMap::new();
    for message in messages {
        *counts.entry(message.feedback_type.as_u8()).or_insert(0) += 1;
    }
    counts
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg(feedback_type: FeedbackType, entity_id: u64, frame: u64) -> FeedbackMessage {
        FeedbackMessage::new(feedback_type, entity_id, frame, "{}")
    }

    #[test]
    fn drains_in_deterministic_order() {
        let buffer = FeedbackBuffer::new();
        buffer
            .append(msg(FeedbackType::PhysicsSettled, 5, 10))
            .unwrap();
        buffer
            .append(msg(FeedbackType::AnimationStateUpdate, 1, 8))
            .unwrap();
        buffer
            .append(msg(FeedbackType::AudioComplete, 3, 10))
            .unwrap();

        let drained = buffer.drain_sorted();
        assert_eq!(drained[0].generated_frame, 8);
        assert_eq!(drained[1].entity_id, 3);
        assert_eq!(drained[2].entity_id, 5);
    }

    #[test]
    fn partial_drain_retains_other_types() {
        let buffer = FeedbackBuffer::new();
        buffer
            .append(msg(FeedbackType::PhysicsSettled, 1, 1))
            .unwrap();
        buffer
            .append(msg(FeedbackType::AudioComplete, 2, 2))
            .unwrap();

        let physics = buffer.drain_type_sorted(FeedbackType::PhysicsSettled);
        assert_eq!(physics.len(), 1);
        assert_eq!(buffer.pending_count(), 1);
        assert_eq!(
            buffer.drain_sorted()[0].feedback_type,
            FeedbackType::AudioComplete
        );
    }

    #[test]
    fn overflow_can_fail_closed() {
        let buffer = FeedbackBuffer::with_config(FeedbackBufferConfig {
            max_pending_messages: 1,
            drop_oldest_on_overflow: false,
        });
        buffer.append(msg(FeedbackType::EngineError, 1, 1)).unwrap();
        assert!(buffer.append(msg(FeedbackType::EngineError, 2, 2)).is_err());
    }

    #[test]
    fn overflow_can_drop_oldest() {
        let buffer = FeedbackBuffer::with_config(FeedbackBufferConfig {
            max_pending_messages: 1,
            drop_oldest_on_overflow: true,
        });
        buffer.append(msg(FeedbackType::EngineError, 1, 1)).unwrap();
        buffer.append(msg(FeedbackType::EngineError, 2, 2)).unwrap();
        let drained = buffer.drain_sorted();
        assert_eq!(drained.len(), 1);
        assert_eq!(drained[0].entity_id, 2);
        assert_eq!(buffer.metrics().dropped_over_capacity, 1);
    }
}
