//! # Runtime Module
//! Core runtime types — phases, execution plans, snapshots, and state deltas.

pub mod phase_enum;
pub mod execution_group;
pub mod execution_plan;
pub mod state_delta;
pub mod world_snapshot;

pub use phase_enum::PhaseEnum;
pub use execution_group::ExecutionGroup;
pub use execution_plan::ExecutionPlan;
pub use state_delta::StateDelta;
pub use world_snapshot::WorldSnapshot;