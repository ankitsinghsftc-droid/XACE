pub mod authority_resolver;
pub mod authority_transfer;
pub mod cheat_guard;

pub use authority_resolver::{
    AuthorityRecord, AuthorityResolver, AuthorityScope, AuthoritySnapshot, AuthoritySource,
};
pub use authority_transfer::{
    AuthorityTransfer, AuthorityTransferDecision, AuthorityTransferReason, AuthorityTransferState,
};
pub use cheat_guard::{
    ActionLimit, CheatGuard, CheatGuardConfig, CheatGuardStats, CheatViolation, CheatViolationKind,
    TransformDeltaReport, TransformSample,
};
