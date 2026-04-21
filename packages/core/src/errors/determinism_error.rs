//! # Determinism Error
//!
//! Defines the DeterminismViolation error — raised by the DeterminismGuard
//! when any of the 15 determinism rules (D1-D15) is violated at runtime.
//!
//! ## Why Determinism Errors Are Special
//! A determinism violation is the most serious error in XACE.
//! It means the simulation has diverged from a reproducible path —
//! replays will fail, network peers will desync, and rollback will
//! produce incorrect results. The DeterminismGuard treats violations
//! as FatalErrors in STRICT mode.
//!
//! ## The 15 Determinism Rules (D1-D15)
//! D1  — System order = ExecutionPlan only. Never self-scheduled.
//! D2  — EntityID never reused. Destroyed IDs permanently archived.
//! D3  — Entity iteration always sorted by EntityID ASC.
//! D4  — Mutations only after phase completion via Mutation Gate.
//! D5  — Events sorted by (tick, phase, event_id) before dispatch.
//! D6  — DeterministicRNG only. No OS/language RNG.
//! D7  — Fixed timestep only. delta_time = 1/simulation_rate.
//! D8  — Consistent float precision. No frame-dependent accumulation.
//! D9  — world_hash computed after each tick. Replay hashes must match.
//! D10 — runtime.schema_version == execution_plan.schema_version always.
//! D11 — Stable key ordering in serialization. Fixed decimal precision.
//! D12 — External input applied at tick boundaries only.
//! D13 — Adapters never modify authoritative simulation state.
//! D14 — Replay = initial snapshot + deterministic input stream + identical schema.
//! D15 — DeterminismGuard hooks at every execution boundary.
//!
//! ## Guard Modes
//! STRICT — violation causes immediate runtime halt (production default)
//! DEV    — violation logged with full context, simulation continues
//! SILENT — violation recorded internally, no output (CI/testing use)

use serde::{Deserialize, Serialize};

// ── Determinism Rule ──────────────────────────────────────────────────────────

/// One of the 15 XACE determinism rules.
///
/// Each rule has a unique ID (D1-D15) and describes one aspect of
/// deterministic simulation. All 15 rules must hold simultaneously
/// for a simulation to be provably deterministic.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum DeterminismRule {
    /// D1 — System order defined only by ExecutionPlan.
    /// No system may schedule itself or reorder execution at runtime.
    D1SystemOrderFromPlanOnly,

    /// D2 — EntityID never reused after destruction.
    /// Destroyed entity IDs are permanently archived — never reassigned.
    D2EntityIdNeverReused,

    /// D3 — Entity iteration always in EntityID ascending order.
    /// No system may iterate entities in insertion order or random order.
    D3EntityIterationSorted,

    /// D4 — All mutations applied only after phase completion via Mutation Gate.
    /// No system may mutate component state directly during phase execution.
    D4MutationsViaGateOnly,

    /// D5 — Events dispatched in (tick ASC, phase ASC, event_id ASC) order.
    /// Emission order never affects dispatch order.
    D5EventsSortedBeforeDispatch,

    /// D6 — Only DeterministicRNG allowed. seed=hash(world_seed,system_id,tick).
    /// OS random(), thread_rng(), and language-native RNG are blocked.
    D6DeterministicRngOnly,

    /// D7 — Fixed timestep only. delta_time = 1.0 / simulation_rate.
    /// Frame rate and rendering performance must never affect simulation timing.
    D7FixedTimestepOnly,

    /// D8 — Consistent float precision across platforms.
    /// No frame-dependent float accumulation allowed.
    D8ConsistentFloatPrecision,

    /// D9 — world_hash computed and validated after each tick.
    /// Replay hashes must match original run hashes tick-for-tick.
    D9WorldHashPerTick,

    /// D10 — runtime.schema_version must equal execution_plan.schema_version.
    /// Version mismatch causes immediate halt — no partial execution.
    D10SchemaVersionMatch,

    /// D11 — Stable key ordering in all serialization.
    /// BTreeMap required everywhere. Fixed decimal precision for floats.
    D11StableSerializationOrder,

    /// D12 — External input applied only at tick boundaries.
    /// No input may be injected mid-tick or mid-phase.
    D12InputAtTickBoundariesOnly,

    /// D13 — Engine adapters may never modify authoritative simulation state.
    /// Adapters are read-only consumers of StateDelta — never writers.
    D13AdaptersReadOnly,

    /// D14 — Replay requires: initial snapshot + input stream + identical schema.
    /// Any deviation in these three inputs produces divergent replay output.
    D14ReplayRequiresThreeInputs,

    /// D15 — DeterminismGuard hooks active at every execution boundary.
    /// No execution boundary may bypass guard validation.
    D15GuardAtEveryBoundary,
}

impl DeterminismRule {
    /// Returns the canonical rule ID string (e.g. "D1", "D15").
    pub fn rule_id(&self) -> &'static str {
        match self {
            DeterminismRule::D1SystemOrderFromPlanOnly => "D1",
            DeterminismRule::D2EntityIdNeverReused => "D2",
            DeterminismRule::D3EntityIterationSorted => "D3",
            DeterminismRule::D4MutationsViaGateOnly => "D4",
            DeterminismRule::D5EventsSortedBeforeDispatch => "D5",
            DeterminismRule::D6DeterministicRngOnly => "D6",
            DeterminismRule::D7FixedTimestepOnly => "D7",
            DeterminismRule::D8ConsistentFloatPrecision => "D8",
            DeterminismRule::D9WorldHashPerTick => "D9",
            DeterminismRule::D10SchemaVersionMatch => "D10",
            DeterminismRule::D11StableSerializationOrder => "D11",
            DeterminismRule::D12InputAtTickBoundariesOnly => "D12",
            DeterminismRule::D13AdaptersReadOnly => "D13",
            DeterminismRule::D14ReplayRequiresThreeInputs => "D14",
            DeterminismRule::D15GuardAtEveryBoundary => "D15",
        }
    }

    /// Returns a plain-English description of this rule.
    pub fn description(&self) -> &'static str {
        match self {
            DeterminismRule::D1SystemOrderFromPlanOnly =>
                "System execution order must come from ExecutionPlan only",
            DeterminismRule::D2EntityIdNeverReused =>
                "EntityIDs must never be reused after destruction",
            DeterminismRule::D3EntityIterationSorted =>
                "Entities must always be iterated in EntityID ascending order",
            DeterminismRule::D4MutationsViaGateOnly =>
                "All mutations must go through the Mutation Gate after phase end",
            DeterminismRule::D5EventsSortedBeforeDispatch =>
                "Events must be sorted by (tick, phase, event_id) before dispatch",
            DeterminismRule::D6DeterministicRngOnly =>
                "Only DeterministicRNG allowed — no OS or language-native random",
            DeterminismRule::D7FixedTimestepOnly =>
                "Fixed timestep only — frame rate must not affect simulation",
            DeterminismRule::D8ConsistentFloatPrecision =>
                "Float precision must be consistent — no frame-dependent accumulation",
            DeterminismRule::D9WorldHashPerTick =>
                "world_hash must be computed and validated after every tick",
            DeterminismRule::D10SchemaVersionMatch =>
                "Runtime schema version must match execution plan schema version",
            DeterminismRule::D11StableSerializationOrder =>
                "All serialization must use stable key ordering and fixed precision",
            DeterminismRule::D12InputAtTickBoundariesOnly =>
                "External input must only be applied at tick boundaries",
            DeterminismRule::D13AdaptersReadOnly =>
                "Engine adapters must never modify authoritative simulation state",
            DeterminismRule::D14ReplayRequiresThreeInputs =>
                "Replay requires initial snapshot, input stream, and identical schema",
            DeterminismRule::D15GuardAtEveryBoundary =>
                "DeterminismGuard must be active at every execution boundary",
        }
    }

    /// Returns the severity impact of violating this rule.
    /// All determinism violations are fatal in STRICT mode.
    /// This rating reflects which violations are hardest to detect
    /// and most likely to cause silent corruption.
    pub fn impact_level(&self) -> u8 {
        match self {
            // Immediate and obvious violations
            DeterminismRule::D6DeterministicRngOnly => 5,
            DeterminismRule::D10SchemaVersionMatch => 5,
            DeterminismRule::D13AdaptersReadOnly => 5,
            // Subtle ordering violations
            DeterminismRule::D1SystemOrderFromPlanOnly => 4,
            DeterminismRule::D3EntityIterationSorted => 4,
            DeterminismRule::D4MutationsViaGateOnly => 4,
            DeterminismRule::D5EventsSortedBeforeDispatch => 4,
            // Timing and precision violations
            DeterminismRule::D7FixedTimestepOnly => 4,
            DeterminismRule::D8ConsistentFloatPrecision => 3,
            DeterminismRule::D11StableSerializationOrder => 3,
            // ID and hash violations
            DeterminismRule::D2EntityIdNeverReused => 5,
            DeterminismRule::D9WorldHashPerTick => 5,
            // Boundary violations
            DeterminismRule::D12InputAtTickBoundariesOnly => 4,
            DeterminismRule::D14ReplayRequiresThreeInputs => 4,
            DeterminismRule::D15GuardAtEveryBoundary => 3,
        }
    }

    /// Returns all 15 determinism rules in order.
    pub fn all() -> &'static [DeterminismRule] {
        &[
            DeterminismRule::D1SystemOrderFromPlanOnly,
            DeterminismRule::D2EntityIdNeverReused,
            DeterminismRule::D3EntityIterationSorted,
            DeterminismRule::D4MutationsViaGateOnly,
            DeterminismRule::D5EventsSortedBeforeDispatch,
            DeterminismRule::D6DeterministicRngOnly,
            DeterminismRule::D7FixedTimestepOnly,
            DeterminismRule::D8ConsistentFloatPrecision,
            DeterminismRule::D9WorldHashPerTick,
            DeterminismRule::D10SchemaVersionMatch,
            DeterminismRule::D11StableSerializationOrder,
            DeterminismRule::D12InputAtTickBoundariesOnly,
            DeterminismRule::D13AdaptersReadOnly,
            DeterminismRule::D14ReplayRequiresThreeInputs,
            DeterminismRule::D15GuardAtEveryBoundary,
        ]
    }
}

impl std::fmt::Display for DeterminismRule {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.rule_id(), self.description())
    }
}

// ── Guard Mode ────────────────────────────────────────────────────────────────

/// The operating mode of the DeterminismGuard.
///
/// Controls how violations are handled at runtime.
/// Mode is set once at runtime initialization — never changed mid-session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum GuardMode {
    /// Production default. Any violation causes immediate runtime halt.
    /// The safest mode — no risk of silent corruption propagating.
    /// Use in all shipped games and staging environments.
    Strict,

    /// Development mode. Violations are logged with full context.
    /// Simulation continues after logging — allows investigation.
    /// Never use in production — violations may corrupt state silently.
    Dev,

    /// Silent recording mode. Violations recorded internally, no output.
    /// Used in CI/testing where violations are expected and asserted.
    /// The test suite uses this mode to verify violation detection works.
    Silent,
}

impl std::fmt::Display for GuardMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            GuardMode::Strict => write!(f, "STRICT"),
            GuardMode::Dev => write!(f, "DEV"),
            GuardMode::Silent => write!(f, "SILENT"),
        }
    }
}

// ── Determinism Violation ─────────────────────────────────────────────────────

/// A detected violation of one of the 15 XACE determinism rules.
///
/// Raised by the DeterminismGuard (Phase 6) when a rule violation
/// is detected. In STRICT mode, this is immediately wrapped in a
/// XaceError::FatalError and causes runtime halt.
///
/// In DEV mode, this is logged and returned for investigation.
/// In SILENT mode, this is recorded in the violation log only.
///
/// ## Full Context
/// The violation carries everything needed to diagnose the issue:
/// - Which rule was violated (rule_id)
/// - Which system caused it (system_context)
/// - At which tick it occurred (tick)
/// - What hash values were expected vs actual (for hash violations)
/// - A human-readable description of what went wrong
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeterminismViolation {
    /// Which determinism rule was violated.
    pub rule: DeterminismRule,

    /// The system ID of the system that caused the violation.
    /// Empty string if the violation is not system-specific.
    /// Examples: "sys_movement", "sys_ai_behavior"
    pub system_context: String,

    /// The simulation tick at which the violation was detected.
    pub tick: u64,

    /// The expected world_hash or value before the violation.
    /// Empty if not applicable to this rule type.
    pub expected_hash: String,

    /// The actual world_hash or value that caused the violation.
    /// Empty if not applicable to this rule type.
    pub actual_hash: String,

    /// Human-readable description of exactly what went wrong.
    /// Includes enough context to identify and fix the violation.
    pub description: String,

    /// The guard mode active when this violation was detected.
    /// Determines how the violation was handled.
    pub detected_in_mode: GuardMode,

    /// The execution phase during which the violation occurred.
    /// Stored as u8 matching PhaseEnum discriminant.
    /// 255 if the violation occurred outside phase execution.
    pub phase: u8,
}

impl DeterminismViolation {
    /// Creates a new determinism violation record.
    pub fn new(
        rule: DeterminismRule,
        system_context: impl Into<String>,
        tick: u64,
        description: impl Into<String>,
        detected_in_mode: GuardMode,
    ) -> Self {
        Self {
            rule,
            system_context: system_context.into(),
            tick,
            expected_hash: String::new(),
            actual_hash: String::new(),
            description: description.into(),
            detected_in_mode,
            phase: 255,
        }
    }

    /// Creates a hash mismatch violation — used for D9 violations.
    pub fn hash_mismatch(
        rule: DeterminismRule,
        system_context: impl Into<String>,
        tick: u64,
        expected_hash: impl Into<String>,
        actual_hash: impl Into<String>,
        detected_in_mode: GuardMode,
    ) -> Self {
        let expected = expected_hash.into();
        let actual = actual_hash.into();
        Self {
            rule,
            system_context: system_context.into(),
            tick,
            description: format!(
                "Hash mismatch at tick {}: expected '{}' but got '{}'",
                tick, expected, actual
            ),
            expected_hash: expected,
            actual_hash: actual,
            detected_in_mode,
            phase: 255,
        }
    }

    /// Builder — sets the phase during which the violation occurred.
    pub fn with_phase(mut self, phase: u8) -> Self {
        self.phase = phase;
        self
    }

    /// Builder — sets the expected hash for hash violations.
    pub fn with_expected_hash(mut self, hash: impl Into<String>) -> Self {
        self.expected_hash = hash.into();
        self
    }

    /// Builder — sets the actual hash for hash violations.
    pub fn with_actual_hash(mut self, hash: impl Into<String>) -> Self {
        self.actual_hash = hash.into();
        self
    }

    /// Returns true if this is a hash mismatch violation.
    pub fn is_hash_mismatch(&self) -> bool {
        !self.expected_hash.is_empty() && !self.actual_hash.is_empty()
    }

    /// Returns true if this violation was detected in STRICT mode.
    /// STRICT violations always cause runtime halt.
    pub fn is_strict(&self) -> bool {
        matches!(self.detected_in_mode, GuardMode::Strict)
    }

    /// Returns a one-line summary of this violation for logging.
    pub fn summary(&self) -> String {
        format!(
            "[{}][{}] tick={} system='{}' — {}",
            self.detected_in_mode,
            self.rule.rule_id(),
            self.tick,
            self.system_context,
            self.description,
        )
    }

    /// Returns the impact level of the violated rule.
    /// Higher = more dangerous violation.
    pub fn impact_level(&self) -> u8 {
        self.rule.impact_level()
    }
}

impl std::fmt::Display for DeterminismViolation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.summary())
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn d6_violation() -> DeterminismViolation {
        DeterminismViolation::new(
            DeterminismRule::D6DeterministicRngOnly,
            "sys_ai_behavior",
            100,
            "System called rand::random() — OS RNG is forbidden (D6)",
            GuardMode::Strict,
        )
    }

    fn d9_violation() -> DeterminismViolation {
        DeterminismViolation::hash_mismatch(
            DeterminismRule::D9WorldHashPerTick,
            "DeterminismGuard",
            1000,
            "expected_hash_abc",
            "actual_hash_xyz",
            GuardMode::Dev,
        )
    }

    #[test]
    fn all_returns_fifteen_rules() {
        assert_eq!(DeterminismRule::all().len(), 15);
    }

    #[test]
    fn all_rules_have_unique_ids() {
        let mut ids = std::collections::HashSet::new();
        for rule in DeterminismRule::all() {
            assert!(ids.insert(rule.rule_id()), "Duplicate rule ID: {}", rule.rule_id());
        }
    }

    #[test]
    fn all_rules_have_descriptions() {
        for rule in DeterminismRule::all() {
            assert!(!rule.description().is_empty(), "Empty description for {}", rule.rule_id());
        }
    }

    #[test]
    fn all_rules_have_nonzero_impact() {
        for rule in DeterminismRule::all() {
            assert!(rule.impact_level() > 0, "Zero impact for {}", rule.rule_id());
        }
    }

    #[test]
    fn rule_ids_match_expected_format() {
        let ids: Vec<&str> = DeterminismRule::all()
            .iter()
            .map(|r| r.rule_id())
            .collect();
        assert_eq!(ids[0], "D1");
        assert_eq!(ids[14], "D15");
    }

    #[test]
    fn d6_violation_created_correctly() {
        let v = d6_violation();
        assert_eq!(v.rule, DeterminismRule::D6DeterministicRngOnly);
        assert_eq!(v.tick, 100);
        assert_eq!(v.system_context, "sys_ai_behavior");
        assert!(v.is_strict());
        assert!(!v.is_hash_mismatch());
    }

    #[test]
    fn d9_hash_mismatch_created_correctly() {
        let v = d9_violation();
        assert!(v.is_hash_mismatch());
        assert_eq!(v.expected_hash, "expected_hash_abc");
        assert_eq!(v.actual_hash, "actual_hash_xyz");
        assert!(!v.is_strict());
    }

    #[test]
    fn violation_summary_contains_key_info() {
        let v = d6_violation();
        let summary = v.summary();
        assert!(summary.contains("D6"));
        assert!(summary.contains("STRICT"));
        assert!(summary.contains("sys_ai_behavior"));
        assert!(summary.contains("100"));
    }

    #[test]
    fn with_phase_sets_phase() {
        let v = d6_violation().with_phase(2);
        assert_eq!(v.phase, 2);
    }

    #[test]
    fn default_phase_is_sentinel() {
        let v = d6_violation();
        assert_eq!(v.phase, 255);
    }

    #[test]
    fn impact_level_delegates_to_rule() {
        let v = d6_violation();
        assert_eq!(v.impact_level(), DeterminismRule::D6DeterministicRngOnly.impact_level());
    }

    #[test]
    fn guard_mode_display() {
        assert_eq!(GuardMode::Strict.to_string(), "STRICT");
        assert_eq!(GuardMode::Dev.to_string(), "DEV");
        assert_eq!(GuardMode::Silent.to_string(), "SILENT");
    }

    #[test]
    fn rule_display_includes_id_and_description() {
        let rule = DeterminismRule::D1SystemOrderFromPlanOnly;
        let display = rule.to_string();
        assert!(display.contains("D1"));
        assert!(display.contains("ExecutionPlan"));
    }

    #[test]
    fn violation_display_matches_summary() {
        let v = d6_violation();
        assert_eq!(v.to_string(), v.summary());
    }

    #[test]
    fn hash_mismatch_description_auto_generated() {
        let v = d9_violation();
        assert!(v.description.contains("1000"));
        assert!(v.description.contains("expected_hash_abc"));
        assert!(v.description.contains("actual_hash_xyz"));
    }

    #[test]
    fn silent_mode_violation_not_strict() {
        let v = DeterminismViolation::new(
            DeterminismRule::D3EntityIterationSorted,
            "sys_test",
            0,
            "Test violation",
            GuardMode::Silent,
        );
        assert!(!v.is_strict());
    }

    #[test]
    fn d2_has_maximum_impact() {
        assert_eq!(DeterminismRule::D2EntityIdNeverReused.impact_level(), 5);
    }

    #[test]
    fn d9_has_maximum_impact() {
        assert_eq!(DeterminismRule::D9WorldHashPerTick.impact_level(), 5);
    }
}