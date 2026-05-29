//! # Errors Module
//! XACE error types — classification, context, and determinism violations.

pub mod determinism_error;
pub mod xace_error;

pub use determinism_error::{DeterminismRule, DeterminismViolation, GuardMode};
pub use xace_error::{ErrorContext, ErrorSeverity, XaceError};
