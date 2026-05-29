//! # Contracts Module
//! All XACE module boundary interfaces — the complete contract layer.

pub mod interfaces;

pub use interfaces::{
    EventId, IComponentTable, IDeterminismGuard, IEngineAdapter, IEntityStore, IEventBus,
    IMutationGate, ISaveEngine, ISnapshotEngine, ISystem, ISystemContext, SaveSlotInfo,
    VisibilityQuery,
};
