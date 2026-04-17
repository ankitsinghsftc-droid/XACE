//! # Assets Module
//! Typed asset references for the XACE asset pipeline.
//! Per Audit 2 — never raw strings, always typed AssetReference structs.

pub mod asset_reference;
pub mod asset_status;
pub mod asset_type;

pub use asset_reference::AssetReference;
pub use asset_status::AssetStatus;
pub use asset_type::AssetType;