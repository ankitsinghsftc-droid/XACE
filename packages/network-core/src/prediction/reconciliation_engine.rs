use serde::{Deserialize, Serialize};

use super::Vec3;
use crate::{EntityId, NetworkError, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ReconciliationMode {
    None,
    Snap,
    Interpolate,
    Smooth,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ReconciliationConfig {
    pub snap_threshold: f32,
    pub correction_epsilon: f32,
    pub max_interpolation_ticks: u16,
    pub smooth_correction_ticks: u16,
}

impl Default for ReconciliationConfig {
    fn default() -> Self {
        Self {
            snap_threshold: 0.5,
            correction_epsilon: 0.0001,
            max_interpolation_ticks: 4,
            smooth_correction_ticks: 8,
        }
    }
}

impl ReconciliationConfig {
    pub fn validate(self) -> Result<(), NetworkError> {
        if !self.snap_threshold.is_finite()
            || self.snap_threshold < 0.0
            || !self.correction_epsilon.is_finite()
            || self.correction_epsilon < 0.0
        {
            return Err(NetworkError::InvalidOperation(
                "reconciliation thresholds must be finite and non-negative".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReconciliationPlan {
    pub entity_id: EntityId,
    pub tick: Tick,
    pub mode: ReconciliationMode,
    pub error_distance: f32,
    pub needs_correction: bool,
    pub correction: Vec3,
    pub predicted: Vec3,
    pub authoritative: Vec3,
    pub blend_ticks: u16,
}

impl ReconciliationPlan {
    pub fn corrected_position_at_step(&self, step: u16) -> Vec3 {
        if !self.needs_correction {
            return self.predicted;
        }
        match self.mode {
            ReconciliationMode::None => self.predicted,
            ReconciliationMode::Snap => self.authoritative,
            ReconciliationMode::Interpolate | ReconciliationMode::Smooth => {
                let denominator = self.blend_ticks.max(1) as f32;
                let alpha = (f32::from(step.min(self.blend_ticks)) / denominator).clamp(0.0, 1.0);
                Vec3::new(
                    self.predicted.x + self.correction.x * alpha,
                    self.predicted.y + self.correction.y * alpha,
                    self.predicted.z + self.correction.z * alpha,
                )
            }
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ReconciliationEngine {
    config: ReconciliationConfig,
}

impl ReconciliationEngine {
    pub fn new(snap_threshold: f32) -> Self {
        Self::with_config(ReconciliationConfig {
            snap_threshold,
            ..ReconciliationConfig::default()
        })
        .expect("reconciliation configuration must be valid")
    }

    pub fn with_config(config: ReconciliationConfig) -> Result<Self, NetworkError> {
        config.validate()?;
        Ok(Self { config })
    }

    pub fn plan(
        &self,
        entity_id: EntityId,
        tick: Tick,
        predicted: (f32, f32, f32),
        authoritative: (f32, f32, f32),
        preferred_mode: ReconciliationMode,
    ) -> ReconciliationPlan {
        self.plan_vec3(
            entity_id,
            tick,
            Vec3::from_tuple(predicted),
            Vec3::from_tuple(authoritative),
            preferred_mode,
        )
        .unwrap_or_else(|_| ReconciliationPlan {
            entity_id,
            tick,
            mode: ReconciliationMode::None,
            error_distance: 0.0,
            needs_correction: false,
            correction: Vec3::ZERO,
            predicted: Vec3::from_tuple(predicted),
            authoritative: Vec3::from_tuple(authoritative),
            blend_ticks: 0,
        })
    }

    pub fn plan_vec3(
        &self,
        entity_id: EntityId,
        tick: Tick,
        predicted: Vec3,
        authoritative: Vec3,
        preferred_mode: ReconciliationMode,
    ) -> Result<ReconciliationPlan, NetworkError> {
        if entity_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "entity_id 0 is reserved".to_string(),
            ));
        }
        if !predicted.is_finite() || !authoritative.is_finite() {
            return Err(NetworkError::InvalidOperation(
                "reconciliation positions must be finite".to_string(),
            ));
        }

        let correction = Vec3::new(
            authoritative.x - predicted.x,
            authoritative.y - predicted.y,
            authoritative.z - predicted.z,
        );
        let error_distance = correction.magnitude();
        let needs_correction = error_distance > self.config.correction_epsilon;
        let mode = if !needs_correction {
            ReconciliationMode::None
        } else if error_distance >= self.config.snap_threshold {
            ReconciliationMode::Snap
        } else {
            preferred_mode
        };
        let blend_ticks = match mode {
            ReconciliationMode::None | ReconciliationMode::Snap => 0,
            ReconciliationMode::Interpolate => self.config.max_interpolation_ticks.max(1),
            ReconciliationMode::Smooth => self.config.smooth_correction_ticks.max(1),
        };

        Ok(ReconciliationPlan {
            entity_id,
            tick,
            mode,
            error_distance,
            needs_correction,
            correction,
            predicted,
            authoritative,
            blend_ticks,
        })
    }

    pub fn config(&self) -> ReconciliationConfig {
        self.config
    }
}
