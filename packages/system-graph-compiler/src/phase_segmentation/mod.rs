//! Phase Segmentation — SGC Stage 3.
//! Partitions the RawSystemGraph into per-phase PhaseBuckets.
//! Cross-phase and PhaseOrder edges are filtered out here.

pub mod phase_segmentation_layer;
pub mod phase_validator;
