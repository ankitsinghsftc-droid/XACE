//! # Contracts Module
//! All XACE module boundary interfaces — the complete contract layer.

pub mod interfaces;

pub use interfaces::{
    ISystem,
    ISystemContext,
    IMutationGate,
    IEntityStore,
    IComponentTable,
    ISnapshotEngine,
    IEventBus,
    IDeterminismGuard,
    IEngineAdapter,
    ISaveEngine,
    VisibilityQuery,
    SaveSlotInfo,
    EventId,
};