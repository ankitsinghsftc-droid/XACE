//! # COMP_GAMESTATE_V1
//!
//! The global game state carrier. Tracks the current phase of the game,
//! score, elapsed time, active game mode, and match state. Typically
//! attached to a single controller entity that represents the game
//! session itself.
//!
//! ## Why this is UCL Core
//! Every game has a state — a menu, a match, a round, a game over screen.
//! Every game tracks some form of progress or score. Every game has a
//! concept of "what mode are we in right now." These concepts are
//! universal across every genre without exception.
//!
//! ## Single Controller Pattern
//! COMP_GAMESTATE_V1 is typically attached to exactly one entity per
//! world — the game controller entity. Systems that need global game
//! state query this entity rather than storing state locally.
//! This keeps game state visible, snapshotable, and deterministic.
//!
//! ## Determinism
//! time_elapsed_ticks is always in ticks — never seconds or frames (D7).
//! Score and phase are written only via Mutation Gate (I2).
//! The controller entity is defined in the CGS, not created at runtime.

use serde::{Deserialize, Serialize};
use crate::entity_metadata::Tick;

/// Component type ID for COMP_GAMESTATE_V1. Frozen forever.
pub const COMP_GAMESTATE_V1_ID: u32 = 9;

// ── Game Phase ────────────────────────────────────────────────────────────────

/// The high-level phase of the game session.
///
/// Represents the macro state of the game — what "screen" or "stage"
/// the player is currently in. Systems check this to determine whether
/// they should run (e.g. combat systems skip during MainMenu phase).
///
/// Game-specific phases (wave 1, boss fight, cutscene) should be
/// represented in the active_mode_id and mode-specific state,
/// not by extending this enum. Keep this high-level.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum GamePhase {
    /// Game is initializing — loading assets, setting up world.
    /// Most gameplay systems are inactive during this phase.
    Initializing,

    /// Main menu or title screen is active.
    /// Input routes to UI systems only.
    MainMenu,

    /// Active gameplay is running.
    /// All gameplay systems are active.
    Playing,

    /// Game is temporarily suspended.
    /// Simulation tick still runs but gameplay systems are paused.
    Paused,

    /// A cutscene or scripted sequence is playing.
    /// Player input is suppressed. Camera system takes over.
    Cutscene,

    /// Game over state — match ended, player lost.
    /// Score is finalized. Restart or menu options presented.
    GameOver,

    /// Victory state — match ended, player won or objective complete.
    Victory,

    /// Transitioning between phases — loading screen, fade, etc.
    /// Duration tracked in transition_ticks_remaining if needed.
    Transitioning,

    /// A developer-defined phase not covered by the above.
    /// String payload carries the custom phase name.
    Custom(String),
}

impl Default for GamePhase {
    fn default() -> Self {
        GamePhase::Initializing
    }
}

impl std::fmt::Display for GamePhase {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            GamePhase::Initializing => write!(f, "Initializing"),
            GamePhase::MainMenu => write!(f, "MainMenu"),
            GamePhase::Playing => write!(f, "Playing"),
            GamePhase::Paused => write!(f, "Paused"),
            GamePhase::Cutscene => write!(f, "Cutscene"),
            GamePhase::GameOver => write!(f, "GameOver"),
            GamePhase::Victory => write!(f, "Victory"),
            GamePhase::Transitioning => write!(f, "Transitioning"),
            GamePhase::Custom(name) => write!(f, "Custom({})", name),
        }
    }
}

// ── Match State ───────────────────────────────────────────────────────────────

/// The state of the current match or round within the Playing phase.
///
/// Provides finer granularity than GamePhase for games with structured
/// match flow — countdown, active play, round end, etc.
/// Ignored when GamePhase is not Playing.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum MatchState {
    /// No match is currently active.
    Idle,

    /// Countdown before match starts (3, 2, 1, Go!)
    Countdown,

    /// Match is actively running — gameplay is live.
    Active,

    /// Brief pause between rounds or waves.
    RoundEnd,

    /// Match has concluded — winner determined.
    MatchEnd,

    /// Sudden death or overtime period.
    Overtime,
}

impl Default for MatchState {
    fn default() -> Self {
        MatchState::Idle
    }
}

impl std::fmt::Display for MatchState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MatchState::Idle => write!(f, "Idle"),
            MatchState::Countdown => write!(f, "Countdown"),
            MatchState::Active => write!(f, "Active"),
            MatchState::RoundEnd => write!(f, "RoundEnd"),
            MatchState::MatchEnd => write!(f, "MatchEnd"),
            MatchState::Overtime => write!(f, "Overtime"),
        }
    }
}

// ── Component ─────────────────────────────────────────────────────────────────

/// COMP_GAMESTATE_V1 — Global game session state.
///
/// UCL Core component. Attached to the game controller entity defined
/// in the CGS. Systems query this component to understand the current
/// macro state of the game and whether they should be active.
///
/// ## Score
/// Score is a signed 64-bit integer to support:
/// - Large scores (arcade games, idle games)
/// - Negative scores (penalties, debt in management games)
/// - Zero-sum scoring (one player's gain is another's loss)
///
/// ## Active Mode
/// `active_mode_id` maps to a GameMode defined in the CGS.
/// Mode switching is a schema mutation — it goes through PIL → GDE
/// → Schema Factory → Runtime, not a direct runtime write.
///
/// ## Time
/// `time_elapsed_ticks` counts ticks since GamePhase became Playing.
/// Resets on match restart. Never counts ticks during Paused phase.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GameStateComponent {
    /// Current high-level phase of the game session.
    pub current_phase: GamePhase,

    /// Current score for this game session.
    /// Signed to support penalties and negative scoring.
    pub score: i64,

    /// Ticks elapsed since the current match/session began.
    /// Only incremented when current_phase is Playing and
    /// match_state is Active. Paused and menu time is excluded.
    pub time_elapsed_ticks: Tick,

    /// The ID of the currently active game mode defined in the CGS.
    /// Empty string means no mode is active (initializing or menu).
    pub active_mode_id: String,

    /// Fine-grained match state within the Playing phase.
    pub match_state: MatchState,
}

impl GameStateComponent {
    /// Creates a fresh game state in the Initializing phase.
    /// Used when a new world session begins.
    pub fn new() -> Self {
        Self {
            current_phase: GamePhase::Initializing,
            score: 0,
            time_elapsed_ticks: 0,
            active_mode_id: String::new(),
            match_state: MatchState::Idle,
        }
    }

    /// Creates a game state ready for active gameplay with a specific mode.
    pub fn playing(active_mode_id: impl Into<String>) -> Self {
        Self {
            current_phase: GamePhase::Playing,
            score: 0,
            time_elapsed_ticks: 0,
            active_mode_id: active_mode_id.into(),
            match_state: MatchState::Active,
        }
    }

    /// Returns true if gameplay systems should be running.
    /// Only true when phase is Playing and match is Active.
    pub fn is_gameplay_active(&self) -> bool {
        self.current_phase == GamePhase::Playing
            && self.match_state == MatchState::Active
    }

    /// Returns true if the game is in any terminal state.
    pub fn is_terminal(&self) -> bool {
        matches!(
            self.current_phase,
            GamePhase::GameOver | GamePhase::Victory
        )
    }

    /// Returns true if player input should be accepted.
    /// Input is blocked during cutscenes, transitions, and terminal states.
    pub fn accepts_input(&self) -> bool {
        matches!(
            self.current_phase,
            GamePhase::Playing | GamePhase::MainMenu | GamePhase::Paused
        )
    }

    /// Adds delta to the score. Delta can be negative for penalties.
    /// Returns the new score value.
    pub fn add_score(&mut self, delta: i64) -> i64 {
        self.score = self.score.saturating_add(delta);
        self.score
    }

    /// Increments time_elapsed_ticks by one.
    /// Called by the GameStateSystem only when is_gameplay_active() is true.
    pub fn tick_time(&mut self) {
        if self.is_gameplay_active() {
            self.time_elapsed_ticks = self.time_elapsed_ticks.saturating_add(1);
        }
    }

    /// Returns elapsed time in seconds given a simulation rate.
    /// `simulation_rate` is ticks per second (e.g. 60.0 for 60Hz).
    pub fn elapsed_seconds(&self, simulation_rate: f32) -> f32 {
        if simulation_rate <= 0.0 {
            return 0.0;
        }
        self.time_elapsed_ticks as f32 / simulation_rate
    }

    /// Returns true if a specific game mode is active.
    pub fn is_mode_active(&self, mode_id: &str) -> bool {
        self.active_mode_id == mode_id
    }
}

impl Default for GameStateComponent {
    fn default() -> Self {
        Self::new()
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_state_is_initializing() {
        let gs = GameStateComponent::new();
        assert_eq!(gs.current_phase, GamePhase::Initializing);
        assert_eq!(gs.score, 0);
        assert_eq!(gs.time_elapsed_ticks, 0);
    }

    #[test]
    fn playing_state_is_active() {
        let gs = GameStateComponent::playing("mode_arena");
        assert!(gs.is_gameplay_active());
        assert_eq!(gs.active_mode_id, "mode_arena");
    }

    #[test]
    fn initializing_is_not_gameplay_active() {
        let gs = GameStateComponent::new();
        assert!(!gs.is_gameplay_active());
    }

    #[test]
    fn paused_is_not_gameplay_active() {
        let mut gs = GameStateComponent::playing("mode_survival");
        gs.current_phase = GamePhase::Paused;
        assert!(!gs.is_gameplay_active());
    }

    #[test]
    fn gameover_is_terminal() {
        let mut gs = GameStateComponent::new();
        gs.current_phase = GamePhase::GameOver;
        assert!(gs.is_terminal());
    }

    #[test]
    fn victory_is_terminal() {
        let mut gs = GameStateComponent::new();
        gs.current_phase = GamePhase::Victory;
        assert!(gs.is_terminal());
    }

    #[test]
    fn playing_is_not_terminal() {
        let gs = GameStateComponent::playing("mode_arena");
        assert!(!gs.is_terminal());
    }

    #[test]
    fn add_score_positive() {
        let mut gs = GameStateComponent::playing("mode_arena");
        let new_score = gs.add_score(100);
        assert_eq!(new_score, 100);
        assert_eq!(gs.score, 100);
    }

    #[test]
    fn add_score_negative_penalty() {
        let mut gs = GameStateComponent::playing("mode_arena");
        gs.add_score(50);
        gs.add_score(-20);
        assert_eq!(gs.score, 30);
    }

    #[test]
    fn score_does_not_overflow() {
        let mut gs = GameStateComponent::playing("mode_arena");
        gs.score = i64::MAX;
        gs.add_score(1);
        assert_eq!(gs.score, i64::MAX);
    }

    #[test]
    fn tick_time_only_when_active() {
        let mut gs = GameStateComponent::playing("mode_arena");
        gs.tick_time();
        gs.tick_time();
        assert_eq!(gs.time_elapsed_ticks, 2);
    }

    #[test]
    fn tick_time_does_not_advance_when_paused() {
        let mut gs = GameStateComponent::playing("mode_arena");
        gs.current_phase = GamePhase::Paused;
        gs.tick_time();
        assert_eq!(gs.time_elapsed_ticks, 0);
    }

    #[test]
    fn elapsed_seconds_correct() {
        let mut gs = GameStateComponent::playing("mode_arena");
        for _ in 0..60 { gs.tick_time(); }
        let secs = gs.elapsed_seconds(60.0);
        assert!((secs - 1.0).abs() < 1e-5);
    }

    #[test]
    fn accepts_input_during_playing() {
        let gs = GameStateComponent::playing("mode_arena");
        assert!(gs.accepts_input());
    }

    #[test]
    fn no_input_during_cutscene() {
        let mut gs = GameStateComponent::playing("mode_arena");
        gs.current_phase = GamePhase::Cutscene;
        assert!(!gs.accepts_input());
    }

    #[test]
    fn mode_detection() {
        let gs = GameStateComponent::playing("mode_survival");
        assert!(gs.is_mode_active("mode_survival"));
        assert!(!gs.is_mode_active("mode_arena"));
    }

    #[test]
    fn custom_phase_display() {
        let phase = GamePhase::Custom("BossFight".into());
        assert_eq!(phase.to_string(), "Custom(BossFight)");
    }
}