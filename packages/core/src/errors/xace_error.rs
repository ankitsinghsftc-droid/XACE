//! # XACE Error Types
//!
//! The complete error classification system for XACE. Every error that
//! can occur anywhere in the pipeline is one of these types. No anonymous
//! or untyped errors are allowed to cross module boundaries.
//!
//! ## Error Classification
//! XACE errors fall into six categories with distinct handling strategies:
//!
//! FatalError — determinism violation, schema mismatch, corrupted snapshot.
//! Runtime must halt immediately. No recovery possible.
//!
//! RecoverableError — network drop, asset resolution delay.
//! Runtime continues. Error logged and retry attempted.
//!
//! ValidationFailure — invalid schema path, type mismatch, dependency violation.
//! Mutation blocked. CGS unchanged. User notified.
//!
//! ClarificationRequired — ambiguous prompt, needs user input.
//! Pipeline paused. Question generated. Resumed on response.
//!
//! RetryableLLMFailure — invalid LLM output. Retry then clarify.
//! PIL retries up to max_retries. Escalates to ClarificationRequired.
//!
//! AssetUnresolved — UNRESOLVED ref blocks CGS commit (I12).
//! Schema commit blocked. Asset must be registered before retry.
//!
//! NetworkDesync — peer hash mismatch, trigger resync (Audit 5).
//! Network layer triggers SNAPSHOT recovery. Session may continue.
//!
//! SaveVersionMismatch — attempt migration, warn if failed (Audit 7).
//! Save system attempts CGS migration. Warns user if migration fails.

use serde::{Deserialize, Serialize};

// ── Error Severity ────────────────────────────────────────────────────────────

/// The severity level of an XACE error.
///
/// Determines how the runtime and pipeline respond to the error.
/// Higher severity = more disruptive response required.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum ErrorSeverity {
    /// Informational — something worth noting but not a problem.
    /// No action required. Logged for debugging.
    Info = 0,

    /// Warning — something unexpected but recoverable happened.
    /// Pipeline continues. User may be notified.
    Warning = 1,

    /// Error — an operation failed and must be retried or abandoned.
    /// Pipeline paused for this operation. Other operations continue.
    Error = 2,

    /// Critical — a subsystem is in a bad state.
    /// Subsystem may need restart. Session may be affected.
    Critical = 3,

    /// Fatal — the runtime cannot continue safely.
    /// Immediate halt required. State must be restored from snapshot.
    Fatal = 4,
}

impl std::fmt::Display for ErrorSeverity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ErrorSeverity::Info => write!(f, "INFO"),
            ErrorSeverity::Warning => write!(f, "WARNING"),
            ErrorSeverity::Error => write!(f, "ERROR"),
            ErrorSeverity::Critical => write!(f, "CRITICAL"),
            ErrorSeverity::Fatal => write!(f, "FATAL"),
        }
    }
}

// ── Error Context ─────────────────────────────────────────────────────────────

/// Contextual information attached to any XACE error.
///
/// Provides the information needed to diagnose, log, and display
/// errors appropriately across all pipeline stages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorContext {
    /// The module or subsystem where the error originated.
    /// Examples: "GDE", "PIL", "MutationGate", "SnapshotEngine"
    pub module: String,

    /// The operation that was being performed when the error occurred.
    /// Examples: "apply_mutation", "take_snapshot", "dispatch_event"
    pub operation: String,

    /// The simulation tick at which the error occurred.
    /// 0 if the error occurred outside the simulation loop.
    pub tick: u64,

    /// Additional key-value details for debugging.
    /// Examples: {"entity_id": "42", "component_type": "COMP_HEALTH_V1"}
    pub details: std::collections::BTreeMap<String, String>,
}

impl ErrorContext {
    pub fn new(module: impl Into<String>, operation: impl Into<String>) -> Self {
        Self {
            module: module.into(),
            operation: operation.into(),
            tick: 0,
            details: std::collections::BTreeMap::new(),
        }
    }

    pub fn with_tick(mut self, tick: u64) -> Self {
        self.tick = tick;
        self
    }

    pub fn with_detail(
        mut self,
        key: impl Into<String>,
        value: impl Into<String>,
    ) -> Self {
        self.details.insert(key.into(), value.into());
        self
    }
}

// ── XACE Error ────────────────────────────────────────────────────────────────

/// The unified error type for all XACE pipeline errors.
///
/// Every error that crosses a module boundary must be one of these
/// variants. No raw strings or anonymous error types allowed.
///
/// ## Handling Strategy per Variant
///
/// FatalError → halt runtime immediately, restore from last clean snapshot
/// RecoverableError → log, retry with backoff, continue if retry succeeds
/// ValidationFailure → block mutation, return to user with explanation
/// ClarificationRequired → pause pipeline, generate question, resume on answer
/// RetryableLLMFailure → retry PIL pipeline up to max_retries, then clarify
/// AssetUnresolved → block CGS commit, require asset registration
/// NetworkDesync → trigger SNAPSHOT recovery, resync engine adapter
/// SaveVersionMismatch → attempt migration, warn user if migration fails
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum XaceError {
    /// A determinism violation or unrecoverable runtime state corruption.
    ///
    /// The runtime MUST halt immediately on FatalError.
    /// The DeterminismGuard raises this on D-rule violations.
    /// The SnapshotEngine raises this on corrupted snapshot detection.
    ///
    /// Recovery: restore from last clean WorldSnapshot.
    /// If no clean snapshot exists: session must be restarted.
    FatalError {
        /// What went fatally wrong.
        message: String,
        /// Where it happened.
        context: ErrorContext,
        /// Whether a snapshot restore might recover the session.
        snapshot_recovery_possible: bool,
    },

    /// An operation failed but the runtime can continue.
    ///
    /// Examples: network connection dropped, asset file temporarily
    /// unavailable, engine adapter timed out on one tick.
    ///
    /// Recovery: log, retry with exponential backoff, continue.
    RecoverableError {
        /// What failed.
        message: String,
        /// Where it happened.
        context: ErrorContext,
        /// Maximum number of retries before escalating.
        max_retries: u32,
        /// Current retry attempt number.
        retry_count: u32,
    },

    /// A schema mutation or runtime operation failed validation.
    ///
    /// Examples: invalid DSL path, type mismatch on component field,
    /// invariant violation, duplicate entity ID, missing dependency.
    ///
    /// Recovery: block the operation, return error to user with
    /// explanation. CGS remains unchanged. No retry needed.
    ValidationFailure {
        /// What validation rule was violated.
        message: String,
        /// Where validation failed.
        context: ErrorContext,
        /// The specific validation rule or invariant that was violated.
        /// Examples: "I1", "D3", "type_mismatch", "missing_dependency"
        rule_violated: String,
        /// The fully qualified path to the field that failed validation.
        /// Empty if the error is not field-specific.
        failed_path: String,
    },

    /// A prompt was ambiguous and needs user clarification before proceeding.
    ///
    /// Examples: "make the enemy faster" when multiple enemy types exist,
    /// "remove the health system" when health is used by multiple systems.
    ///
    /// Recovery: generate a structured clarification question,
    /// pause the pipeline, resume when user responds.
    ClarificationRequired {
        /// Why clarification is needed.
        message: String,
        /// Where ambiguity was detected.
        context: ErrorContext,
        /// The specific ambiguity that needs resolution.
        /// Examples: "multiple_targets", "scope_unclear", "value_range"
        ambiguity_type: String,
        /// The original prompt that triggered this clarification.
        original_prompt: String,
    },

    /// The LLM produced invalid output that failed parsing or validation.
    ///
    /// Examples: hallucinated schema path, invalid JSON structure,
    /// operation type incompatible with target field type.
    ///
    /// Recovery: retry the PIL pipeline with enhanced context.
    /// After max_retries exhausted: escalate to ClarificationRequired.
    RetryableLLMFailure {
        /// What the LLM got wrong.
        message: String,
        /// Where failure occurred.
        context: ErrorContext,
        /// Which PIL pass failed (1-5).
        failed_pass: u8,
        /// Current retry attempt.
        retry_count: u32,
        /// Maximum retries before escalating to ClarificationRequired.
        max_retries: u32,
    },

    /// An UNRESOLVED asset reference blocks CGS commit (I12).
    ///
    /// Examples: component references an asset ID that was never
    /// registered in the Asset Registry.
    ///
    /// Recovery: register the asset reference before retrying commit.
    /// The Asset Registry must transition it from UNRESOLVED to PLACEHOLDER.
    AssetUnresolved {
        /// Which asset is unresolved.
        message: String,
        /// Where the unresolved reference was found.
        context: ErrorContext,
        /// The asset ID that is unresolved.
        asset_id: String,
        /// The fully qualified CGS path to the field containing this reference.
        field_path: String,
    },

    /// A network desync was detected between peers (Audit 5).
    ///
    /// Examples: world_hash mismatch between host and client at tick N,
    /// sequence gap in DELTA messages, peer reported wrong schema version.
    ///
    /// Recovery: send SNAPSHOT to desynced peer for full resynchronization.
    /// Session continues for synchronized peers during recovery.
    NetworkDesync {
        /// What desynced.
        message: String,
        /// Where desync was detected.
        context: ErrorContext,
        /// The peer ID of the desynced client.
        peer_id: String,
        /// The tick at which desync was detected.
        desync_tick: u64,
        /// The local world_hash at desync tick.
        local_hash: String,
        /// The remote world_hash reported by the peer.
        remote_hash: String,
    },

    /// A save file was created with an older CGS version (Audit 7).
    ///
    /// Examples: loading a save file from CGS version 0.1.0 when the
    /// current game schema is version 0.3.2.
    ///
    /// Recovery: attempt schema migration using SchemaDelta chain.
    /// If migration succeeds: load save with migrated data.
    /// If migration fails: warn user, offer to start fresh or use backup.
    SaveVersionMismatch {
        /// What version mismatch occurred.
        message: String,
        /// Where the mismatch was detected.
        context: ErrorContext,
        /// The CGS version the save was created on.
        save_schema_version: String,
        /// The current CGS version.
        current_schema_version: String,
        /// Whether a migration path exists from save version to current.
        migration_available: bool,
    },
}

impl XaceError {
    /// Returns the severity level of this error.
    pub fn severity(&self) -> ErrorSeverity {
        match self {
            XaceError::FatalError { .. } => ErrorSeverity::Fatal,
            XaceError::NetworkDesync { .. } => ErrorSeverity::Critical,
            XaceError::RecoverableError { .. } => ErrorSeverity::Error,
            XaceError::ValidationFailure { .. } => ErrorSeverity::Error,
            XaceError::AssetUnresolved { .. } => ErrorSeverity::Error,
            XaceError::RetryableLLMFailure { .. } => ErrorSeverity::Warning,
            XaceError::ClarificationRequired { .. } => ErrorSeverity::Info,
            XaceError::SaveVersionMismatch { migration_available, .. } => {
                if *migration_available {
                    ErrorSeverity::Warning
                } else {
                    ErrorSeverity::Error
                }
            }
        }
    }

    /// Returns true if this error requires the runtime to halt immediately.
    pub fn is_fatal(&self) -> bool {
        matches!(self, XaceError::FatalError { .. })
    }

    /// Returns true if this error can be recovered from without user input.
    pub fn is_auto_recoverable(&self) -> bool {
        matches!(
            self,
            XaceError::RecoverableError { .. }
                | XaceError::RetryableLLMFailure { .. }
                | XaceError::NetworkDesync { .. }
        )
    }

    /// Returns true if this error requires user input to resolve.
    pub fn requires_user_input(&self) -> bool {
        matches!(
            self,
            XaceError::ClarificationRequired { .. }
                | XaceError::SaveVersionMismatch {
                    migration_available: false,
                    ..
                }
        )
    }

    /// Returns true if this error blocks a CGS mutation from proceeding.
    pub fn blocks_mutation(&self) -> bool {
        matches!(
            self,
            XaceError::ValidationFailure { .. }
                | XaceError::AssetUnresolved { .. }
                | XaceError::ClarificationRequired { .. }
        )
    }

    /// Returns the error message regardless of variant.
    pub fn message(&self) -> &str {
        match self {
            XaceError::FatalError { message, .. } => message,
            XaceError::RecoverableError { message, .. } => message,
            XaceError::ValidationFailure { message, .. } => message,
            XaceError::ClarificationRequired { message, .. } => message,
            XaceError::RetryableLLMFailure { message, .. } => message,
            XaceError::AssetUnresolved { message, .. } => message,
            XaceError::NetworkDesync { message, .. } => message,
            XaceError::SaveVersionMismatch { message, .. } => message,
        }
    }

    /// Returns the error context regardless of variant.
    pub fn context(&self) -> &ErrorContext {
        match self {
            XaceError::FatalError { context, .. } => context,
            XaceError::RecoverableError { context, .. } => context,
            XaceError::ValidationFailure { context, .. } => context,
            XaceError::ClarificationRequired { context, .. } => context,
            XaceError::RetryableLLMFailure { context, .. } => context,
            XaceError::AssetUnresolved { context, .. } => context,
            XaceError::NetworkDesync { context, .. } => context,
            XaceError::SaveVersionMismatch { context, .. } => context,
        }
    }

    /// Returns a plain-English user-facing message for this error.
    /// Zero technical vocabulary — safe for display to any user mode.
    pub fn user_message(&self) -> String {
        match self {
            XaceError::FatalError { .. } =>
                "Something went seriously wrong. Your game is being restored \
                 to the last safe point.".into(),
            XaceError::RecoverableError { message, .. } =>
                format!("Something went wrong but we're fixing it: {}", message),
            XaceError::ValidationFailure { message, .. } =>
                format!("That change couldn't be applied: {}", message),
            XaceError::ClarificationRequired { message, .. } =>
                format!("I need a bit more information: {}", message),
            XaceError::RetryableLLMFailure { .. } =>
                "I'm having trouble understanding that. Let me try again.".into(),
            XaceError::AssetUnresolved { asset_id, .. } =>
                format!(
                    "A visual asset ('{}') is missing from the project. \
                     Please link it before saving.",
                    asset_id
                ),
            XaceError::NetworkDesync { peer_id, .. } =>
                format!(
                    "Player '{}' got out of sync. Reconnecting them now.",
                    peer_id
                ),
            XaceError::SaveVersionMismatch { migration_available, .. } => {
                if *migration_available {
                    "This save file is from an older version. \
                     Updating it now.".into()
                } else {
                    "This save file is too old to load. \
                     Please start a new game.".into()
                }
            }
        }
    }
}

impl std::fmt::Display for XaceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "[{}] {}: {}",
            self.severity(),
            self.context().module,
            self.message()
        )
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn test_context() -> ErrorContext {
        ErrorContext::new("TestModule", "test_operation")
            .with_tick(42)
            .with_detail("key", "value")
    }

    fn fatal_error() -> XaceError {
        XaceError::FatalError {
            message: "Determinism violation detected".into(),
            context: test_context(),
            snapshot_recovery_possible: true,
        }
    }

    fn validation_error() -> XaceError {
        XaceError::ValidationFailure {
            message: "Type mismatch on field".into(),
            context: test_context(),
            rule_violated: "type_mismatch".into(),
            failed_path: "modes.mode_arena.actors.actor_player.stats.speed".into(),
        }
    }

    fn clarification_error() -> XaceError {
        XaceError::ClarificationRequired {
            message: "Multiple enemy types found".into(),
            context: test_context(),
            ambiguity_type: "multiple_targets".into(),
            original_prompt: "make the enemy faster".into(),
        }
    }

    #[test]
    fn fatal_error_is_fatal() {
        assert!(fatal_error().is_fatal());
        assert_eq!(fatal_error().severity(), ErrorSeverity::Fatal);
    }

    #[test]
    fn validation_error_is_not_fatal() {
        assert!(!validation_error().is_fatal());
    }

    #[test]
    fn validation_error_blocks_mutation() {
        assert!(validation_error().blocks_mutation());
    }

    #[test]
    fn clarification_required_blocks_mutation() {
        assert!(clarification_error().blocks_mutation());
    }

    #[test]
    fn fatal_error_does_not_block_mutation() {
        assert!(!fatal_error().blocks_mutation());
    }

    #[test]
    fn clarification_requires_user_input() {
        assert!(clarification_error().requires_user_input());
    }

    #[test]
    fn fatal_does_not_require_user_input() {
        assert!(!fatal_error().requires_user_input());
    }

    #[test]
    fn recoverable_error_is_auto_recoverable() {
        let err = XaceError::RecoverableError {
            message: "Network timeout".into(),
            context: test_context(),
            max_retries: 3,
            retry_count: 0,
        };
        assert!(err.is_auto_recoverable());
    }

    #[test]
    fn network_desync_is_critical() {
        let err = XaceError::NetworkDesync {
            message: "Hash mismatch".into(),
            context: test_context(),
            peer_id: "peer_001".into(),
            desync_tick: 1000,
            local_hash: "abc123".into(),
            remote_hash: "def456".into(),
        };
        assert_eq!(err.severity(), ErrorSeverity::Critical);
        assert!(err.is_auto_recoverable());
    }

    #[test]
    fn asset_unresolved_blocks_mutation() {
        let err = XaceError::AssetUnresolved {
            message: "Asset not registered".into(),
            context: test_context(),
            asset_id: "character_knight_mesh_v1".into(),
            field_path: "modes.mode_arena.actors.actor_player.components.render".into(),
        };
        assert!(err.blocks_mutation());
    }

    #[test]
    fn save_version_mismatch_with_migration_is_warning() {
        let err = XaceError::SaveVersionMismatch {
            message: "Version mismatch".into(),
            context: test_context(),
            save_schema_version: "0.1.0".into(),
            current_schema_version: "0.3.0".into(),
            migration_available: true,
        };
        assert_eq!(err.severity(), ErrorSeverity::Warning);
    }

    #[test]
    fn save_version_mismatch_without_migration_is_error() {
        let err = XaceError::SaveVersionMismatch {
            message: "Version mismatch".into(),
            context: test_context(),
            save_schema_version: "0.1.0".into(),
            current_schema_version: "0.3.0".into(),
            migration_available: false,
        };
        assert_eq!(err.severity(), ErrorSeverity::Error);
        assert!(err.requires_user_input());
    }

    #[test]
    fn message_accessible_from_all_variants() {
        assert!(!fatal_error().message().is_empty());
        assert!(!validation_error().message().is_empty());
        assert!(!clarification_error().message().is_empty());
    }

    #[test]
    fn context_accessible_from_all_variants() {
        assert_eq!(fatal_error().context().module, "TestModule");
        assert_eq!(fatal_error().context().tick, 42);
    }

    #[test]
    fn context_details_stored() {
        let ctx = test_context();
        assert_eq!(ctx.details.get("key"), Some(&"value".to_string()));
    }

    #[test]
    fn user_message_not_empty_for_all_variants() {
        assert!(!fatal_error().user_message().is_empty());
        assert!(!validation_error().user_message().is_empty());
        assert!(!clarification_error().user_message().is_empty());
    }

    #[test]
    fn display_includes_severity_and_module() {
        let display = fatal_error().to_string();
        assert!(display.contains("FATAL"));
        assert!(display.contains("TestModule"));
    }

    #[test]
    fn error_severity_ordering() {
        assert!(ErrorSeverity::Info < ErrorSeverity::Warning);
        assert!(ErrorSeverity::Warning < ErrorSeverity::Error);
        assert!(ErrorSeverity::Error < ErrorSeverity::Critical);
        assert!(ErrorSeverity::Critical < ErrorSeverity::Fatal);
    }

    #[test]
    fn retryable_llm_failure_is_warning() {
        let err = XaceError::RetryableLLMFailure {
            message: "Invalid JSON from LLM".into(),
            context: test_context(),
            failed_pass: 2,
            retry_count: 1,
            max_retries: 3,
        };
        assert_eq!(err.severity(), ErrorSeverity::Warning);
        assert!(err.is_auto_recoverable());
    }
}