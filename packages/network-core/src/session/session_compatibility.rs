use serde::{Deserialize, Serialize};

use crate::{NetworkError, PeerId};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionCompatibilityProfile {
    pub peer_id: PeerId,
    pub schema_version: String,
    pub sgc_plan_hash: String,
    pub adapter_version: String,
    pub asset_manifest_hash: String,
    pub package_set_hash: String,
    pub provider_free_metadata_hash: String,
    pub template_id: String,
}

impl SessionCompatibilityProfile {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        peer_id: PeerId,
        schema_version: impl Into<String>,
        sgc_plan_hash: impl Into<String>,
        adapter_version: impl Into<String>,
        asset_manifest_hash: impl Into<String>,
        package_set_hash: impl Into<String>,
        provider_free_metadata_hash: impl Into<String>,
        template_id: impl Into<String>,
    ) -> Self {
        Self {
            peer_id,
            schema_version: schema_version.into(),
            sgc_plan_hash: sgc_plan_hash.into(),
            adapter_version: adapter_version.into(),
            asset_manifest_hash: asset_manifest_hash.into(),
            package_set_hash: package_set_hash.into(),
            provider_free_metadata_hash: provider_free_metadata_hash.into(),
            template_id: template_id.into(),
        }
    }

    pub fn for_peer(&self, peer_id: PeerId) -> Self {
        Self {
            peer_id,
            ..self.clone()
        }
    }

    pub fn validate(&self) -> Result<(), NetworkError> {
        if self.peer_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "compatibility peer_id 0 is reserved".to_string(),
            ));
        }
        for (field, value) in [
            ("schema_version", self.schema_version.as_str()),
            ("sgc_plan_hash", self.sgc_plan_hash.as_str()),
            ("adapter_version", self.adapter_version.as_str()),
            ("asset_manifest_hash", self.asset_manifest_hash.as_str()),
            ("package_set_hash", self.package_set_hash.as_str()),
            (
                "provider_free_metadata_hash",
                self.provider_free_metadata_hash.as_str(),
            ),
            ("template_id", self.template_id.as_str()),
        ] {
            if value.trim().is_empty() {
                return Err(NetworkError::InvalidOperation(format!(
                    "session compatibility field {field} must be non-empty"
                )));
            }
        }
        Ok(())
    }

    pub fn compare_peer(&self, peer: &Self) -> Result<SessionCompatibilityReport, NetworkError> {
        self.validate()?;
        peer.validate()?;
        let mut mismatches = Vec::new();
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::Schema,
            &self.schema_version,
            &peer.schema_version,
        );
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::SgcPlan,
            &self.sgc_plan_hash,
            &peer.sgc_plan_hash,
        );
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::AdapterVersion,
            &self.adapter_version,
            &peer.adapter_version,
        );
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::Assets,
            &self.asset_manifest_hash,
            &peer.asset_manifest_hash,
        );
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::Packages,
            &self.package_set_hash,
            &peer.package_set_hash,
        );
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::ProviderFreeMetadata,
            &self.provider_free_metadata_hash,
            &peer.provider_free_metadata_hash,
        );
        push_mismatch(
            &mut mismatches,
            peer.peer_id,
            SessionCompatibilityMismatchKind::Template,
            &self.template_id,
            &peer.template_id,
        );
        Ok(SessionCompatibilityReport {
            peer_id: peer.peer_id,
            compatible: mismatches.is_empty(),
            mismatches,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum SessionCompatibilityMismatchKind {
    Schema,
    SgcPlan,
    AdapterVersion,
    Assets,
    Packages,
    ProviderFreeMetadata,
    Template,
    MissingProfile,
}

impl SessionCompatibilityMismatchKind {
    pub const fn stable_id(self) -> &'static str {
        match self {
            Self::Schema => "schema",
            Self::SgcPlan => "sgc_plan",
            Self::AdapterVersion => "adapter_version",
            Self::Assets => "assets",
            Self::Packages => "packages",
            Self::ProviderFreeMetadata => "provider_free_metadata",
            Self::Template => "template",
            Self::MissingProfile => "missing_profile",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionCompatibilityMismatch {
    pub peer_id: PeerId,
    pub kind: SessionCompatibilityMismatchKind,
    pub expected: String,
    pub actual: String,
    pub blocking: bool,
    pub message: String,
}

impl SessionCompatibilityMismatch {
    pub fn blocking(
        peer_id: PeerId,
        kind: SessionCompatibilityMismatchKind,
        expected: impl Into<String>,
        actual: impl Into<String>,
    ) -> Self {
        let expected = expected.into();
        let actual = actual.into();
        Self {
            peer_id,
            kind,
            expected: expected.clone(),
            actual: actual.clone(),
            blocking: true,
            message: format!(
                "session compatibility mismatch kind={} peer={} expected={} actual={}",
                kind.stable_id(),
                peer_id,
                expected,
                actual
            ),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SessionCompatibilityReport {
    pub peer_id: PeerId,
    pub compatible: bool,
    pub mismatches: Vec<SessionCompatibilityMismatch>,
}

impl SessionCompatibilityReport {
    pub fn compatible(peer_id: PeerId) -> Self {
        Self {
            peer_id,
            compatible: true,
            mismatches: Vec::new(),
        }
    }

    pub fn missing_profile(peer_id: PeerId) -> Self {
        Self {
            peer_id,
            compatible: false,
            mismatches: vec![SessionCompatibilityMismatch::blocking(
                peer_id,
                SessionCompatibilityMismatchKind::MissingProfile,
                "profile supplied before session start",
                "missing",
            )],
        }
    }

    pub fn has_blocking_mismatch(&self) -> bool {
        self.mismatches.iter().any(|mismatch| mismatch.blocking)
    }
}

fn push_mismatch(
    mismatches: &mut Vec<SessionCompatibilityMismatch>,
    peer_id: PeerId,
    kind: SessionCompatibilityMismatchKind,
    expected: &str,
    actual: &str,
) {
    if expected != actual {
        mismatches.push(SessionCompatibilityMismatch::blocking(
            peer_id, kind, expected, actual,
        ));
    }
}
