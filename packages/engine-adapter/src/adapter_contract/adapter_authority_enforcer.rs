//! Authority firewall for inbound engine-adapter messages.
//!
//! Engine adapters may send input, feedback, and lifecycle control. They may
//! not send authoritative state mutations such as deltas, snapshots, or events.

use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::wire::message_type::MessageType;
use xace_core::wire::wire_message::WireMessage;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuthorityClassification {
    Permitted,
    AttemptedMutation {
        message_type: MessageType,
        reason: &'static str,
    },
    Unexpected {
        message_type: MessageType,
        reason: &'static str,
    },
}

impl AuthorityClassification {
    pub fn is_permitted(&self) -> bool {
        matches!(self, Self::Permitted)
    }

    pub fn is_violation(&self) -> bool {
        matches!(self, Self::AttemptedMutation { .. })
    }

    pub fn should_drop(&self) -> bool {
        !self.is_permitted()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EnforcerMode {
    Strict,
    Dev,
}

impl std::fmt::Display for EnforcerMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Strict => f.write_str("STRICT"),
            Self::Dev => f.write_str("DEV"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuthorityPolicy {
    pub mode: EnforcerMode,
    pub expected_world_id: Option<String>,
    pub expected_schema_version: Option<String>,
    pub expected_execution_plan_version: Option<u32>,
    pub allow_post_handshake_control: bool,
}

impl AuthorityPolicy {
    pub fn strict() -> Self {
        Self {
            mode: EnforcerMode::Strict,
            expected_world_id: None,
            expected_schema_version: None,
            expected_execution_plan_version: None,
            allow_post_handshake_control: true,
        }
    }

    pub fn dev() -> Self {
        Self {
            mode: EnforcerMode::Dev,
            ..Self::strict()
        }
    }

    pub fn with_expected_session(
        mut self,
        world_id: impl Into<String>,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) -> Self {
        self.expected_world_id = Some(world_id.into());
        self.expected_schema_version = Some(schema_version.into());
        self.expected_execution_plan_version = Some(execution_plan_version);
        self
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EnforcerMetrics {
    pub messages_checked: u64,
    pub permitted_count: u64,
    pub violation_count: u64,
    pub unexpected_count: u64,
    pub version_reject_count: u64,
}

pub struct AdapterAuthorityEnforcer {
    policy: AuthorityPolicy,
    metrics: EnforcerMetrics,
    handshake_complete: bool,
}

impl AdapterAuthorityEnforcer {
    pub fn new(mode: EnforcerMode) -> Self {
        Self::with_policy(match mode {
            EnforcerMode::Strict => AuthorityPolicy::strict(),
            EnforcerMode::Dev => AuthorityPolicy::dev(),
        })
    }

    pub fn with_policy(policy: AuthorityPolicy) -> Self {
        Self {
            policy,
            metrics: EnforcerMetrics::default(),
            handshake_complete: false,
        }
    }

    pub fn strict() -> Self {
        Self::new(EnforcerMode::Strict)
    }

    pub fn dev() -> Self {
        Self::new(EnforcerMode::Dev)
    }

    pub fn mark_handshake_complete(&mut self) {
        self.handshake_complete = true;
    }

    pub fn is_handshake_complete(&self) -> bool {
        self.handshake_complete
    }

    pub fn check(&mut self, msg: &WireMessage) -> Result<AuthorityClassification, XaceError> {
        self.metrics.messages_checked += 1;

        if let Err(detail) = self.check_session(msg) {
            self.metrics.version_reject_count += 1;
            return self.handle_violation(
                msg,
                AuthorityClassification::AttemptedMutation {
                    message_type: msg.message_type,
                    reason: "message targets a different world/schema/plan session",
                },
                detail,
            );
        }

        let classification = self.classify(msg);
        match &classification {
            AuthorityClassification::Permitted => {
                self.metrics.permitted_count += 1;
                Ok(classification)
            }
            AuthorityClassification::Unexpected { .. } => {
                self.metrics.unexpected_count += 1;
                Ok(classification)
            }
            AuthorityClassification::AttemptedMutation { reason, .. } => {
                self.metrics.violation_count += 1;
                self.handle_violation(msg, classification.clone(), (*reason).to_string())
            }
        }
    }

    pub fn filter_permitted(
        &mut self,
        messages: Vec<WireMessage>,
    ) -> Result<Vec<WireMessage>, XaceError> {
        let mut permitted = Vec::with_capacity(messages.len());
        for msg in messages {
            if self.check(&msg)?.is_permitted() {
                permitted.push(msg);
            }
        }
        Ok(permitted)
    }

    pub fn metrics(&self) -> &EnforcerMetrics {
        &self.metrics
    }

    pub fn policy(&self) -> &AuthorityPolicy {
        &self.policy
    }

    pub fn mode(&self) -> EnforcerMode {
        self.policy.mode
    }

    pub fn has_violations(&self) -> bool {
        self.metrics.violation_count > 0 || self.metrics.version_reject_count > 0
    }

    fn classify(&self, msg: &WireMessage) -> AuthorityClassification {
        match msg.message_type {
            MessageType::Input | MessageType::Feedback => AuthorityClassification::Permitted,
            MessageType::Control => {
                if !self.handshake_complete || self.policy.allow_post_handshake_control {
                    AuthorityClassification::Permitted
                } else {
                    AuthorityClassification::Unexpected {
                        message_type: MessageType::Control,
                        reason: "post-handshake control messages are disabled by policy",
                    }
                }
            }
            MessageType::Delta => AuthorityClassification::AttemptedMutation {
                message_type: MessageType::Delta,
                reason: "DELTA is runtime-to-engine only",
            },
            MessageType::Snapshot => AuthorityClassification::AttemptedMutation {
                message_type: MessageType::Snapshot,
                reason: "SNAPSHOT is runtime-to-engine only",
            },
            MessageType::Event => AuthorityClassification::AttemptedMutation {
                message_type: MessageType::Event,
                reason: "EVENT originates in the runtime event bus only",
            },
        }
    }

    fn check_session(&self, msg: &WireMessage) -> Result<(), String> {
        if let Some(expected) = &self.policy.expected_world_id {
            if &msg.world_id != expected {
                return Err(format!(
                    "world_id mismatch: expected '{}', got '{}'",
                    expected, msg.world_id
                ));
            }
        }
        if let Some(expected) = &self.policy.expected_schema_version {
            if &msg.schema_version != expected {
                return Err(format!(
                    "schema_version mismatch: expected '{}', got '{}'",
                    expected, msg.schema_version
                ));
            }
        }
        if let Some(expected) = self.policy.expected_execution_plan_version {
            if msg.execution_plan_version != expected {
                return Err(format!(
                    "execution_plan_version mismatch: expected {}, got {}",
                    expected, msg.execution_plan_version
                ));
            }
        }
        Ok(())
    }

    fn handle_violation(
        &self,
        msg: &WireMessage,
        classification: AuthorityClassification,
        detail: String,
    ) -> Result<AuthorityClassification, XaceError> {
        match self.policy.mode {
            EnforcerMode::Dev => Ok(classification),
            EnforcerMode::Strict => Err(XaceError::FatalError {
                message: format!(
                    "engine adapter authority violation: {} (type={} world={} tick={} seq={})",
                    detail, msg.message_type, msg.world_id, msg.tick, msg.sequence_id
                ),
                context: ErrorContext::new("AdapterAuthorityEnforcer", "check")
                    .with_tick(msg.tick)
                    .with_detail("message_type", msg.message_type.to_string())
                    .with_detail("sequence_id", msg.sequence_id.to_string())
                    .with_detail("world_id", msg.world_id.clone()),
                snapshot_recovery_possible: false,
            }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg(message_type: MessageType) -> WireMessage {
        WireMessage::new("default", "0.1.0", 1, 1, 1, message_type, "{}")
    }

    #[test]
    fn input_feedback_and_control_are_permitted() {
        let mut enforcer = AdapterAuthorityEnforcer::strict();
        assert!(enforcer
            .check(&msg(MessageType::Input))
            .unwrap()
            .is_permitted());
        assert!(enforcer
            .check(&msg(MessageType::Feedback))
            .unwrap()
            .is_permitted());
        assert!(enforcer
            .check(&msg(MessageType::Control))
            .unwrap()
            .is_permitted());
    }

    #[test]
    fn inbound_delta_is_fatal_in_strict_mode() {
        let mut enforcer = AdapterAuthorityEnforcer::strict();
        assert!(enforcer.check(&msg(MessageType::Delta)).is_err());
        assert!(enforcer.has_violations());
    }

    #[test]
    fn inbound_snapshot_is_dropped_in_dev_mode() {
        let mut enforcer = AdapterAuthorityEnforcer::dev();
        let classification = enforcer.check(&msg(MessageType::Snapshot)).unwrap();
        assert!(classification.is_violation());
        assert!(classification.should_drop());
    }

    #[test]
    fn session_mismatch_is_rejected() {
        let policy = AuthorityPolicy::strict().with_expected_session("world_a", "0.1.0", 1);
        let mut enforcer = AdapterAuthorityEnforcer::with_policy(policy);
        let bad = WireMessage::input("world_b", "0.1.0", 1, 1, 1, "{}");
        assert!(enforcer.check(&bad).is_err());
        assert_eq!(enforcer.metrics().version_reject_count, 1);
    }
}
