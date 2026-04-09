// xace-system-graph-compiler — Converts SystemDefinitions into deterministic ExecutionPlan
// 7 compiler stages. Build Phase 10.

pub mod graph_construction;
pub mod phase_segmentation;
pub mod dependency_resolution;
pub mod conflict_analyzer;
pub mod scheduler;
pub mod cycle_detection;
pub mod parallelization;
pub mod sgc_pipeline;
pub mod compilation_error;
