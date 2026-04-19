//! # World Definition
//!
//! Defines the physical and environmental properties of a game world
//! within a specific game mode. Every GameMode has exactly one WorldDefinition.
//!
//! ## What This Defines
//! The WorldDefinition is the environment contract — it tells the runtime
//! and engine adapter what kind of physical space this mode takes place in.
//! Map type, gravity, physics profile, time system, and environment type
//! are all declared here.
//!
//! ## What This Does Not Define
//! Entity positions, actual terrain geometry, and asset layouts are
//! NOT defined here. Those live in actor definitions and the engine's
//! scene data. WorldDefinition defines the rules of the space,
//! not the content of the space.
//!
//! ## Engine Responsibility
//! The engine adapter reads WorldDefinition at mode load time and
//! configures its physics engine, lighting system, and time-of-day
//! system accordingly. XACE never calls physics or lighting APIs directly.

use serde::{Deserialize, Serialize};

// ── Map Type ──────────────────────────────────────────────────────────────────

/// The geometric topology of the game world.
///
/// Determines how the engine sets up its scene graph and
/// culling systems. Also constrains which movement systems
/// make sense — a 2D map should not use 3D flying movement.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum MapType {
    /// A fully 3D open environment.
    /// Characters move in all three axes.
    /// Most common for action, RPG, and shooter games.
    Open3D,

    /// A 2D side-scrolling environment.
    /// Characters move on X and Y axes only.
    /// Used for platformers, side-scrollers, fighting games.
    Sidescroller2D,

    /// A 2D top-down environment viewed from above.
    /// Characters move on X and Z axes only (Y is up, fixed).
    /// Used for top-down shooters, RPGs, strategy games.
    TopDown2D,

    /// A 3D environment with isometric camera perspective.
    /// Full 3D simulation but rendered from a fixed diagonal angle.
    /// Used for RTS, MOBA, and classic RPG games.
    Isometric3D,

    /// A confined indoor environment — corridors, rooms, dungeons.
    /// Typically triggers aggressive occlusion culling in the engine.
    Indoor3D,

    /// An infinite or procedurally generated world.
    /// Requires WorldStreaming components on chunk entities.
    /// Used for survival, sandbox, and open-world games.
    Infinite3D,
}

impl Default for MapType {
    fn default() -> Self {
        MapType::Open3D
    }
}

impl std::fmt::Display for MapType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MapType::Open3D => write!(f, "Open3D"),
            MapType::Sidescroller2D => write!(f, "Sidescroller2D"),
            MapType::TopDown2D => write!(f, "TopDown2D"),
            MapType::Isometric3D => write!(f, "Isometric3D"),
            MapType::Indoor3D => write!(f, "Indoor3D"),
            MapType::Infinite3D => write!(f, "Infinite3D"),
        }
    }
}

// ── Environment Type ──────────────────────────────────────────────────────────

/// The visual and atmospheric environment of the world.
///
/// Drives the engine's lighting, weather, and atmosphere systems.
/// The engine adapter maps each type to its environment presets.
/// XACE stores the declaration — the engine renders the result.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum EnvironmentType {
    /// Bright outdoor daylight. Standard sun lighting.
    Outdoor,
    /// Interior space. Artificial lighting, no sky.
    Indoor,
    /// Underground cave or dungeon. Dark, torch-lit.
    Underground,
    /// Underwater environment. Caustics, depth fog.
    Underwater,
    /// Space or zero-gravity vacuum. Starfield background.
    Space,
    /// Nighttime outdoor environment. Moon and star lighting.
    Night,
    /// Extreme weather — storm, blizzard, sandstorm.
    Extreme,
    /// Abstract or non-realistic environment (puzzle, dream).
    Abstract,
}

impl Default for EnvironmentType {
    fn default() -> Self {
        EnvironmentType::Outdoor
    }
}

impl std::fmt::Display for EnvironmentType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EnvironmentType::Outdoor => write!(f, "Outdoor"),
            EnvironmentType::Indoor => write!(f, "Indoor"),
            EnvironmentType::Underground => write!(f, "Underground"),
            EnvironmentType::Underwater => write!(f, "Underwater"),
            EnvironmentType::Space => write!(f, "Space"),
            EnvironmentType::Night => write!(f, "Night"),
            EnvironmentType::Extreme => write!(f, "Extreme"),
            EnvironmentType::Abstract => write!(f, "Abstract"),
        }
    }
}

// ── Physics Profile ───────────────────────────────────────────────────────────

/// The physics simulation profile for this world.
///
/// Controls how the engine configures its physics engine at mode load.
/// Higher fidelity profiles are more accurate but more CPU-expensive.
/// The engine adapter maps these to its physics quality settings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PhysicsProfile {
    /// No physics simulation. Entities move only by system logic.
    /// Fastest. Used for pure logic games, card games, visual novels.
    None,

    /// Simplified physics. Basic collision, no rigid body dynamics.
    /// Used for platformers and games needing collision but not physics.
    Simple,

    /// Standard physics simulation. Rigidbodies, joints, forces.
    /// Used for most action, adventure, and shooter games.
    Standard,

    /// High-fidelity physics. Accurate constraints, soft bodies.
    /// Used for physics puzzles, destruction simulations, vehicles.
    HighFidelity,

    /// Zero-gravity physics profile. No gravity, inertia preserved.
    /// Used for space games and zero-g environments.
    ZeroGravity,
}

impl Default for PhysicsProfile {
    fn default() -> Self {
        PhysicsProfile::Standard
    }
}

// ── Time System ───────────────────────────────────────────────────────────────

/// How the in-game time and day/night cycle operates.
///
/// Controls the engine's time-of-day system and sky/lighting transitions.
/// XACE tracks time in ticks (D7) — the TimeSystem converts ticks to
/// in-game hours for the engine adapter's day/night rendering.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum TimeSystem {
    /// No in-game time. Environment is static.
    /// Most common — most games don't need dynamic day/night.
    Static,

    /// Dynamic day/night cycle driven by simulation ticks.
    /// `day_length_ticks` in WorldDefinition controls cycle speed.
    Dynamic,

    /// Time is controlled by game events, not simulation ticks.
    /// Story beats or triggers advance time rather than passage.
    EventDriven,

    /// Frozen at a specific time of day. No cycle.
    /// Environment lighting is fixed at the declared time.
    Frozen,
}

impl Default for TimeSystem {
    fn default() -> Self {
        TimeSystem::Static
    }
}

// ── World Size ────────────────────────────────────────────────────────────────

/// The declared size bounds of the game world in world units.
///
/// Used by the engine adapter to configure far clip planes,
/// streaming budgets, and minimap scaling.
/// Not a hard constraint — entities can exist outside these bounds,
/// but the engine may cull them from rendering.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorldSize {
    /// Width of the world in world units (X axis).
    pub width: f32,
    /// Height of the world in world units (Y axis).
    /// For 2D games this is the vertical extent of the playfield.
    pub height: f32,
    /// Depth of the world in world units (Z axis).
    /// For 2D games this is typically set to 0.
    pub depth: f32,
}

impl WorldSize {
    /// A small arena — suitable for tight combat or puzzle maps.
    pub const SMALL: WorldSize = WorldSize {
        width: 100.0,
        height: 50.0,
        depth: 100.0,
    };

    /// A medium map — suitable for most action and adventure games.
    pub const MEDIUM: WorldSize = WorldSize {
        width: 500.0,
        height: 200.0,
        depth: 500.0,
    };

    /// A large open world — suitable for exploration and sandbox games.
    pub const LARGE: WorldSize = WorldSize {
        width: 2000.0,
        height: 500.0,
        depth: 2000.0,
    };

    /// Infinite world — used with Infinite3D map type and WorldStreaming.
    pub const INFINITE: WorldSize = WorldSize {
        width: f32::MAX,
        height: f32::MAX,
        depth: f32::MAX,
    };

    pub fn new(width: f32, height: f32, depth: f32) -> Self {
        Self { width, height, depth }
    }

    /// Returns true if this is a 2D world (depth is zero or near-zero).
    pub fn is_2d(&self) -> bool {
        self.depth < 1.0
    }
}

impl Default for WorldSize {
    fn default() -> Self {
        WorldSize::MEDIUM
    }
}

// ── Gravity ───────────────────────────────────────────────────────────────────

/// Gravity vector for this world's physics simulation.
///
/// Expressed as acceleration in world units per second squared.
/// Standard Earth gravity is approximately (0, -9.81, 0).
/// The engine adapter applies this to all rigidbody entities
/// that do not have gravity disabled in COMP_RIGIDBODY_V1.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Gravity {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Gravity {
    /// Standard Earth-like gravity pulling downward on Y axis.
    pub const EARTH: Gravity = Gravity { x: 0.0, y: -9.81, z: 0.0 };

    /// No gravity — used for space and zero-g environments.
    pub const ZERO: Gravity = Gravity { x: 0.0, y: 0.0, z: 0.0 };

    /// Low gravity — moon-like, good for floaty platformers.
    pub const LOW: Gravity = Gravity { x: 0.0, y: -2.5, z: 0.0 };

    /// High gravity — heavy, oppressive, good for horror or weight.
    pub const HIGH: Gravity = Gravity { x: 0.0, y: -20.0, z: 0.0 };

    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    /// Returns true if gravity is effectively zero in all axes.
    pub fn is_zero(&self) -> bool {
        self.x.abs() < 1e-6 && self.y.abs() < 1e-6 && self.z.abs() < 1e-6
    }

    /// Returns the magnitude of the gravity vector.
    pub fn magnitude(&self) -> f32 {
        (self.x * self.x + self.y * self.y + self.z * self.z).sqrt()
    }
}

impl Default for Gravity {
    fn default() -> Self {
        Gravity::EARTH
    }
}

// ── World Definition ──────────────────────────────────────────────────────────

/// The physical and environmental configuration of a game mode's world.
///
/// Every GameMode contains exactly one WorldDefinition. It is the
/// environment contract between the CGS and the engine adapter.
/// The engine reads this at mode load time and configures its
/// scene, physics, lighting, and time systems accordingly.
///
/// ## Relationship to WorldStreaming
/// For Infinite3D worlds, entities with COMP_WORLDSTREAMING_V1
/// manage chunk loading. WorldDefinition declares the streaming intent —
/// the WorldStreaming system implements it tick by tick.
///
/// ## Determinism
/// WorldDefinition is immutable during a session — it is a schema
/// declaration, not runtime state. Changes to world properties
/// require a schema mutation through the full PIL → GDE pipeline.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorldDefinition {
    /// Geometric topology of the world.
    pub map_type: MapType,

    /// Visual and atmospheric environment.
    pub environment_type: EnvironmentType,

    /// Declared size bounds of the world in world units.
    pub size: WorldSize,

    /// Physics simulation fidelity for this world.
    pub physics_profile: PhysicsProfile,

    /// How in-game time progresses in this world.
    pub time_system: TimeSystem,

    /// Length of one full day/night cycle in simulation ticks.
    /// Only meaningful when time_system is Dynamic.
    /// At 60Hz: 72000 ticks = 20 real minutes per in-game day.
    pub day_length_ticks: u64,

    /// Gravity vector applied to all physics-enabled entities.
    pub gravity: Gravity,
}

impl WorldDefinition {
    /// Creates a standard 3D outdoor world with Earth gravity.
    /// The most common starting point for action and adventure games.
    pub fn standard_3d() -> Self {
        Self {
            map_type: MapType::Open3D,
            environment_type: EnvironmentType::Outdoor,
            size: WorldSize::MEDIUM,
            physics_profile: PhysicsProfile::Standard,
            time_system: TimeSystem::Static,
            day_length_ticks: 0,
            gravity: Gravity::EARTH,
        }
    }

    /// Creates a 2D sidescroller world with standard gravity.
    pub fn sidescroller_2d() -> Self {
        Self {
            map_type: MapType::Sidescroller2D,
            environment_type: EnvironmentType::Outdoor,
            size: WorldSize::new(1000.0, 200.0, 0.0),
            physics_profile: PhysicsProfile::Simple,
            time_system: TimeSystem::Static,
            day_length_ticks: 0,
            gravity: Gravity::EARTH,
        }
    }

    /// Creates a top-down 2D world with no gravity.
    pub fn top_down_2d() -> Self {
        Self {
            map_type: MapType::TopDown2D,
            environment_type: EnvironmentType::Outdoor,
            size: WorldSize::new(500.0, 0.0, 500.0),
            physics_profile: PhysicsProfile::Simple,
            time_system: TimeSystem::Static,
            day_length_ticks: 0,
            gravity: Gravity::ZERO,
        }
    }

    /// Creates a space world with zero gravity.
    pub fn space() -> Self {
        Self {
            map_type: MapType::Open3D,
            environment_type: EnvironmentType::Space,
            size: WorldSize::LARGE,
            physics_profile: PhysicsProfile::ZeroGravity,
            time_system: TimeSystem::Static,
            day_length_ticks: 0,
            gravity: Gravity::ZERO,
        }
    }

    /// Returns true if this world uses 2D movement constraints.
    pub fn is_2d(&self) -> bool {
        matches!(
            self.map_type,
            MapType::Sidescroller2D | MapType::TopDown2D
        )
    }

    /// Returns true if this world has active physics simulation.
    pub fn has_physics(&self) -> bool {
        !matches!(self.physics_profile, PhysicsProfile::None)
    }

    /// Returns true if this world has a dynamic day/night cycle.
    pub fn has_dynamic_time(&self) -> bool {
        matches!(self.time_system, TimeSystem::Dynamic)
            && self.day_length_ticks > 0
    }

    /// Returns true if this world requires WorldStreaming.
    /// Infinite worlds require streaming — all others load fully.
    pub fn requires_streaming(&self) -> bool {
        matches!(self.map_type, MapType::Infinite3D)
    }
}

impl Default for WorldDefinition {
    fn default() -> Self {
        Self::standard_3d()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn standard_3d_has_earth_gravity() {
        let w = WorldDefinition::standard_3d();
        assert!(!w.gravity.is_zero());
        assert!((w.gravity.y - (-9.81)).abs() < 1e-5);
    }

    #[test]
    fn space_world_has_zero_gravity() {
        let w = WorldDefinition::space();
        assert!(w.gravity.is_zero());
        assert!(matches!(w.physics_profile, PhysicsProfile::ZeroGravity));
    }

    #[test]
    fn top_down_is_2d() {
        let w = WorldDefinition::top_down_2d();
        assert!(w.is_2d());
    }

    #[test]
    fn standard_3d_is_not_2d() {
        let w = WorldDefinition::standard_3d();
        assert!(!w.is_2d());
    }

    #[test]
    fn no_physics_profile_has_no_physics() {
        let mut w = WorldDefinition::standard_3d();
        w.physics_profile = PhysicsProfile::None;
        assert!(!w.has_physics());
    }

    #[test]
    fn standard_has_physics() {
        let w = WorldDefinition::standard_3d();
        assert!(w.has_physics());
    }

    #[test]
    fn static_time_has_no_dynamic_time() {
        let w = WorldDefinition::standard_3d();
        assert!(!w.has_dynamic_time());
    }

    #[test]
    fn dynamic_time_with_day_length_detected() {
        let mut w = WorldDefinition::standard_3d();
        w.time_system = TimeSystem::Dynamic;
        w.day_length_ticks = 72000;
        assert!(w.has_dynamic_time());
    }

    #[test]
    fn infinite_world_requires_streaming() {
        let mut w = WorldDefinition::standard_3d();
        w.map_type = MapType::Infinite3D;
        assert!(w.requires_streaming());
    }

    #[test]
    fn standard_world_does_not_require_streaming() {
        let w = WorldDefinition::standard_3d();
        assert!(!w.requires_streaming());
    }

    #[test]
    fn gravity_magnitude_earth() {
        let g = Gravity::EARTH;
        assert!((g.magnitude() - 9.81).abs() < 1e-3);
    }

    #[test]
    fn gravity_zero_is_zero() {
        assert!(Gravity::ZERO.is_zero());
    }

    #[test]
    fn world_size_2d_detection() {
        let size = WorldSize::new(500.0, 200.0, 0.0);
        assert!(size.is_2d());
    }

    #[test]
    fn world_size_3d_not_2d() {
        let size = WorldSize::MEDIUM;
        assert!(!size.is_2d());
    }

    #[test]
    fn sidescroller_uses_simple_physics() {
        let w = WorldDefinition::sidescroller_2d();
        assert!(matches!(w.physics_profile, PhysicsProfile::Simple));
    }

    #[test]
    fn map_type_display() {
        assert_eq!(MapType::Open3D.to_string(), "Open3D");
        assert_eq!(MapType::Sidescroller2D.to_string(), "Sidescroller2D");
    }
}
