//! # Assets Module
//! Typed asset references for the XACE asset pipeline.
//! Per Audit 2 — never raw strings, always typed AssetReference structs.

pub mod asset_reference;
pub mod asset_status;
pub mod asset_type;
pub mod semantic_binding;

pub use asset_reference::AssetReference;
pub use asset_status::AssetStatus;
pub use asset_type::AssetType;
pub use semantic_binding::{
    BindingEntitySelector, PlaybackCommandRequest, RuntimeFallbackBinding, SemanticAssetBinding,
    SemanticBindingError, SemanticBindingTable, SemanticPlaybackKind, PARAM_BINDING_STATUS,
    PARAM_FALLBACK_ASSET_ID, PARAM_FALLBACK_ASSET_STATUS, PARAM_FALLBACK_ASSET_TYPE,
    PARAM_FALLBACK_DETERMINISTIC, PARAM_FALLBACK_KIND, PARAM_FALLBACK_LABEL, PARAM_FALLBACK_SCHEMA,
    PARAM_FALLBACK_SEED, PARAM_FALLBACK_VISIBLE, PARAM_RUNTIME_FALLBACK,
    RUNTIME_FALLBACK_CATALOG_SCHEMA,
};
