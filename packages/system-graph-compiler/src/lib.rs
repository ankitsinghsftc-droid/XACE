//! # XACE System Graph Compiler (SGC)
//!
//! Compiles SystemDefinition declarations from the CGS into a deterministic
//! ExecutionPlan that the runtime PhaseOrchestrator executes every tick.
//!
//! ## Pipeline Stages (in order)
//! 1. graph_construction    — SystemDefinitions → RawSystemGraph
//! 2. cycle_detection       — DFS cycle check (early abort)
//! 3. phase_segmentation    — RawSystemGraph → Vec<PhaseBucket>
//! 4. dependency_resolution — PhaseBuckets → OrderedGraph (Kahn's)
//! 5. conflict_analyzer     — OrderedGraph → ConflictReport
//! 6. scheduler             — OrderedGraph + Report → ExecutionPlan
//! 7. parallelization       — ExecutionPlan safety validation pass
//!
//! Entry point: sgc_pipeline::SgcPipeline::compile()
//! Determinism guarantee (D1, D9, D11): identical input → identical plan.

pub mod compilation_error;
pub mod graph_construction;
pub mod phase_segmentation;
pub mod dependency_resolution;
pub mod conflict_analyzer;
pub mod scheduler;
pub mod cycle_detection;
pub mod parallelization;
pub mod sgc_pipeline;

#[cfg(test)]
mod tests;