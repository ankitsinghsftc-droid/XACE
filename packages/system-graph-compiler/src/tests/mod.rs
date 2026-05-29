//! SGC integration test suite.
//! Each file covers one compiler stage using the zombie chase
//! graph (Phase 9) as the canonical test fixture.
//! All tests verify determinism (D11): same input → same output.

mod test_conflict_analyzer;
mod test_cycle_detection;
mod test_dependency_resolution;
mod test_graph_construction;
mod test_phase_segmentation;
