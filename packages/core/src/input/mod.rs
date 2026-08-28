//! Canonical semantic input contracts shared by creator tools and adapters.

pub mod semantic_input_registry;

pub use semantic_input_registry::{
    get_semantic_input, is_registered_semantic_input, SemanticInputDefinition, SemanticInputKind,
    BUILTIN_SEMANTIC_INPUTS,
};
