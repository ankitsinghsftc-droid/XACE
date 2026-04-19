//! # Schema Module
//! Canonical Game Schema types — the single source of truth for all game definitions.

pub mod canonical_game_schema;
pub mod game_mode;
pub mod world_definition;
pub mod actor_definition;
pub mod system_definition;
pub mod rule_definition;

pub use canonical_game_schema::{CanonicalGameSchema, CgsMetadata, CgsVersion};
pub use game_mode::GameMode;
pub use world_definition::WorldDefinition;
pub use actor_definition::ActorDefinition;
pub use system_definition::SystemDefinition;
pub use rule_definition::RuleDefinition;
