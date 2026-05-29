//! # Schema Module
//! Canonical Game Schema types — the single source of truth for all game definitions.

pub mod actor_definition;
pub mod canonical_game_schema;
pub mod game_mode;
pub mod rule_definition;
pub mod system_definition;
pub mod world_definition;

pub use actor_definition::ActorDefinition;
pub use canonical_game_schema::{CanonicalGameSchema, CgsMetadata, CgsVersion};
pub use game_mode::GameMode;
pub use rule_definition::RuleDefinition;
pub use system_definition::SystemDefinition;
pub use world_definition::WorldDefinition;
