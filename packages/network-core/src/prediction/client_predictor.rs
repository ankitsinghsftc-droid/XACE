use serde::{Deserialize, Serialize};

use crate::{EntityId, NetworkError, Tick};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub const ZERO: Self = Self {
        x: 0.0,
        y: 0.0,
        z: 0.0,
    };

    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    pub fn from_tuple(value: (f32, f32, f32)) -> Self {
        Self::new(value.0, value.1, value.2)
    }

    pub fn to_tuple(self) -> (f32, f32, f32) {
        (self.x, self.y, self.z)
    }

    pub fn add_scaled(self, velocity: Self, dt: f32) -> Self {
        Self {
            x: self.x + velocity.x * dt,
            y: self.y + velocity.y * dt,
            z: self.z + velocity.z * dt,
        }
    }

    pub fn magnitude(self) -> f32 {
        self.magnitude_sq().sqrt()
    }

    pub fn magnitude_sq(self) -> f32 {
        self.x
            .mul_add(self.x, self.y.mul_add(self.y, self.z * self.z))
    }

    pub fn clamp_magnitude(self, max_magnitude: f32) -> Self {
        if max_magnitude <= 0.0 {
            return Self::ZERO;
        }
        let magnitude = self.magnitude();
        if magnitude <= max_magnitude || magnitude <= f32::EPSILON {
            return self;
        }
        let scale = max_magnitude / magnitude;
        Self {
            x: self.x * scale,
            y: self.y * scale,
            z: self.z * scale,
        }
    }

    pub fn is_finite(self) -> bool {
        self.x.is_finite() && self.y.is_finite() && self.z.is_finite()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PredictionConfig {
    pub tick_rate_hz: u32,
    pub max_velocity_units_per_second: f32,
    pub max_acceleration_units_per_second_sq: f32,
    pub max_prediction_ticks: u16,
}

impl Default for PredictionConfig {
    fn default() -> Self {
        Self {
            tick_rate_hz: 60,
            max_velocity_units_per_second: 120.0,
            max_acceleration_units_per_second_sq: 240.0,
            max_prediction_ticks: 12,
        }
    }
}

impl PredictionConfig {
    pub fn validate(self) -> Result<(), NetworkError> {
        if self.tick_rate_hz == 0 {
            return Err(NetworkError::InvalidOperation(
                "prediction tick_rate_hz must be greater than zero".to_string(),
            ));
        }
        if !self.max_velocity_units_per_second.is_finite()
            || self.max_velocity_units_per_second < 0.0
            || !self.max_acceleration_units_per_second_sq.is_finite()
            || self.max_acceleration_units_per_second_sq < 0.0
        {
            return Err(NetworkError::InvalidOperation(
                "prediction velocity/acceleration limits must be finite and non-negative"
                    .to_string(),
            ));
        }
        Ok(())
    }

    pub fn tick_dt(self) -> f32 {
        1.0 / self.tick_rate_hz as f32
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PredictionInput {
    pub entity_id: EntityId,
    pub base_tick: Tick,
    pub target_tick: Tick,
    pub position: Vec3,
    pub velocity: Vec3,
    pub acceleration: Vec3,
}

impl PredictionInput {
    pub fn validate(self, config: PredictionConfig) -> Result<(), NetworkError> {
        if self.entity_id == 0 {
            return Err(NetworkError::InvalidOperation(
                "entity_id 0 is reserved".to_string(),
            ));
        }
        if self.target_tick < self.base_tick {
            return Err(NetworkError::InvalidOperation(format!(
                "prediction target tick {} is before base tick {}",
                self.target_tick, self.base_tick
            )));
        }
        let prediction_ticks = self.target_tick.saturating_sub(self.base_tick);
        if prediction_ticks > u64::from(config.max_prediction_ticks) {
            return Err(NetworkError::InvalidOperation(format!(
                "prediction horizon {} exceeds limit {}",
                prediction_ticks, config.max_prediction_ticks
            )));
        }
        if !self.position.is_finite()
            || !self.velocity.is_finite()
            || !self.acceleration.is_finite()
        {
            return Err(NetworkError::InvalidOperation(
                "prediction input contains non-finite vectors".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ClientPrediction {
    pub entity_id: EntityId,
    pub tick: Tick,
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl ClientPrediction {
    pub fn position(self) -> Vec3 {
        Vec3::new(self.x, self.y, self.z)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PredictedState {
    pub entity_id: EntityId,
    pub base_tick: Tick,
    pub predicted_tick: Tick,
    pub position: Vec3,
    pub velocity: Vec3,
    pub prediction_ticks: u16,
}

impl PredictedState {
    pub fn as_client_prediction(self) -> ClientPrediction {
        ClientPrediction {
            entity_id: self.entity_id,
            tick: self.predicted_tick,
            x: self.position.x,
            y: self.position.y,
            z: self.position.z,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct ClientPredictor {
    config: PredictionConfig,
    tick_dt: f32,
}

impl ClientPredictor {
    pub fn new(tick_rate_hz: u32) -> Self {
        Self::with_config(PredictionConfig {
            tick_rate_hz: tick_rate_hz.max(1),
            ..PredictionConfig::default()
        })
        .expect("default prediction configuration must be valid")
    }

    pub fn with_config(config: PredictionConfig) -> Result<Self, NetworkError> {
        config.validate()?;
        Ok(Self {
            tick_dt: config.tick_dt(),
            config,
        })
    }

    pub fn predict_linear(
        &self,
        entity_id: EntityId,
        tick: Tick,
        position: (f32, f32, f32),
        velocity: (f32, f32, f32),
    ) -> ClientPrediction {
        let input = PredictionInput {
            entity_id,
            base_tick: tick.saturating_sub(1),
            target_tick: tick,
            position: Vec3::from_tuple(position),
            velocity: Vec3::from_tuple(velocity),
            acceleration: Vec3::ZERO,
        };
        self.predict(input)
            .map(PredictedState::as_client_prediction)
            .unwrap_or(ClientPrediction {
                entity_id,
                tick,
                x: position.0,
                y: position.1,
                z: position.2,
            })
    }

    pub fn predict(&self, input: PredictionInput) -> Result<PredictedState, NetworkError> {
        input.validate(self.config)?;
        let prediction_ticks = input.target_tick.saturating_sub(input.base_tick) as u16;
        let dt = self.tick_dt * f32::from(prediction_ticks);
        let clamped_acceleration = input
            .acceleration
            .clamp_magnitude(self.config.max_acceleration_units_per_second_sq);
        let velocity = input
            .velocity
            .add_scaled(clamped_acceleration, dt)
            .clamp_magnitude(self.config.max_velocity_units_per_second);
        let average_velocity = Vec3::new(
            (input.velocity.x + velocity.x) * 0.5,
            (input.velocity.y + velocity.y) * 0.5,
            (input.velocity.z + velocity.z) * 0.5,
        );
        let position = input.position.add_scaled(average_velocity, dt);
        Ok(PredictedState {
            entity_id: input.entity_id,
            base_tick: input.base_tick,
            predicted_tick: input.target_tick,
            position,
            velocity,
            prediction_ticks,
        })
    }

    pub fn config(&self) -> PredictionConfig {
        self.config
    }

    pub fn tick_dt(&self) -> f32 {
        self.tick_dt
    }
}
