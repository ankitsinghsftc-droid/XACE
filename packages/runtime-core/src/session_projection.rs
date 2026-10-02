//! Versioned, mechanic-independent full projection synchronization.
//! Tick means the NEXT authoritative simulation tick (state before that tick).
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use crate::engine_protocol::EntityState;
use crate::live_session::SessionAdmission;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectionStamp {
    pub schema: String,
    pub session_id: String,
    pub authority_incarnation: String,
    pub ruleset_epoch: u64,
    pub connection_generation: u64,
    pub baseline_id: String,
    pub sequence: u64,
    pub next_tick: u64,
    pub projection_digest: String,
}
#[derive(Debug, Deserialize)]
#[serde(tag = "msg_type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProjectionControl {
    BaselineAck { stamp_json: String },
    ResyncRequest { connection_generation: u64 },
}
impl ProjectionStamp {
    pub fn build(admission: &SessionAdmission, sequence: u64, next_tick: u64,
                 entities: &[EntityState]) -> anyhow::Result<(Self, String)> {
        // Hash the exact UTF-8 projection bytes, avoiding client float/JSON re-encoding.
        let projection = serde_json::to_string(entities)?;
        Ok((Self {
            schema: "xace.session_projection.v1".into(),
            session_id: admission.contract.epoch.session_id.to_string(),
            authority_incarnation: admission.contract.epoch.authority_incarnation.to_string(),
            ruleset_epoch: admission.contract.epoch.ruleset_epoch,
            connection_generation: admission.generation,
            baseline_id: uuid::Uuid::new_v4().to_string(),
            sequence, next_tick,
            projection_digest: format!("{:x}", Sha256::digest(projection.as_bytes())),
        }, projection))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ack_is_strictly_versioned_and_rejects_untyped_fields() {
        let raw = r#"{"msg_type":"baseline_ack","stamp":{}}"#;
        assert!(serde_json::from_str::<ProjectionControl>(raw).is_err());
        assert!(serde_json::from_str::<ProjectionControl>(
            r#"{"msg_type":"resync_request","connection_generation":1,"wall_run":true}"#).is_err());
    }
}
