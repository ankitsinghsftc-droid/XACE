//! # Errors Module
//! XACE error types — classification, context, and determinism violations.

pub mod xace_error;
pub mod determinism_error;

pub use xace_error::{XaceError, ErrorContext, ErrorSeverity};
pub use determinism_error::{DeterminismViolation, DeterminismRule, GuardMode};