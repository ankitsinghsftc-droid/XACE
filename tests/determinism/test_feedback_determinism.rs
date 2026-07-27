use xace_core::wire::feedback_payload::{FeedbackMessage, FeedbackType};
use xace_engine_feedback::feedback_buffer::FeedbackBuffer;
use xace_engine_feedback::feedback_log::FeedbackLog;
use xace_engine_feedback::feedback_replay_loader::FeedbackReplayLoader;

fn messages(order: &[u64]) -> Vec<FeedbackMessage> {
    order
        .iter()
        .copied()
        .map(|entity_id| {
            FeedbackMessage::new(
                FeedbackType::PhysicsSettled,
                entity_id,
                100 + (entity_id % 2),
                format!(
                    "{{\"entity_id\":{},\"x\":{},\"z\":{}}}",
                    entity_id,
                    entity_id * 3,
                    entity_id * 5
                ),
            )
        })
        .collect()
}

fn build_log(order: &[u64]) -> FeedbackLog {
    let buffer = FeedbackBuffer::new();
    for message in messages(order) {
        buffer.append(message).unwrap();
    }

    let mut log = FeedbackLog::new("schema.feedback.test", 3);
    log.record_tick_checked(12, buffer.drain_sorted()).unwrap();
    log.record_tick_checked(13, Vec::new()).unwrap();
    log.validate_integrity().unwrap();
    log
}

#[test]
fn feedback_log_serialization_is_stable_after_sorted_drain() {
    let a = serde_json::to_string(&build_log(&[4, 2, 3, 1])).unwrap();
    let b = serde_json::to_string(&build_log(&[1, 3, 2, 4])).unwrap();
    assert_eq!(a, b);
}

#[test]
fn feedback_replay_injects_the_same_tick_sequence() {
    let log = build_log(&[4, 2, 3, 1]);
    let expected = log.messages_at(12).to_vec();
    let replay_buffer = FeedbackBuffer::new();
    let mut loader = FeedbackReplayLoader::new(replay_buffer.clone(), "schema.feedback.test", 3);

    loader.begin_replay(log).unwrap();
    assert_eq!(loader.inject_for_tick(12).unwrap(), expected.len());
    assert_eq!(replay_buffer.drain_sorted(), expected);
    assert_eq!(loader.inject_for_tick(13).unwrap(), 0);

    let report = loader.finish_replay();
    assert!(report.is_complete());
    assert_eq!(report.total_messages_injected, expected.len() as u64);
}
