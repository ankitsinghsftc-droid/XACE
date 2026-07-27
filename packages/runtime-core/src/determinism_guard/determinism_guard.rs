//! # Determinism Guard
//!
//! Implements the DeterminismGuard hook surface for XACE determinism rules
//! (D1-D15). RuntimeOrchestrator owns one guard for the ticking session and
//! PhaseOrchestrator calls the boundary/version/hash hooks during every tick.
//!
//! ## Six Runtime Hooks
//! 1. hook_tick_start     — validates schema/plan version match (D10, D15)
//! 2. hook_phase_start    — records phase entry, enforces boundary guard (D15)
//! 3. hook_system_execute — validates system is in the ExecutionPlan (D1, D15)
//! 4. hook_phase_end      — closes phase window, boundary completion (D15)
//! 5. hook_tick_end       — computes and records world_hash (D9, D11)
//! 6. hook_rng_access     — detects illegal non-deterministic RNG usage (D6)
//!
//! ## Guard Modes
//! STRICT — violation produces XaceError::FatalError, simulation halts.
//!          Use in all shipped games and staging environments.
//! DEV    — violation logged to stderr + violation_log. Simulation continues.
//!          Never use in production — violations may corrupt state silently.
//! SILENT — violation recorded in violation_log only. No output.
//!          Used in CI/testing where violations are expected and asserted.
//!
//! ## D10 Exception
//! Schema version mismatch (D10) is ALWAYS fatal regardless of guard mode.
//! No guard mode can suppress a version mismatch — it is too dangerous to
//! allow silent divergence from a mismatched execution plan.
//!
//! ## World Hash (D9)
//! hook_tick_end calls WorldHasher::compute(snapshot) for the live end-of-tick
//! snapshot and records the authoritative per-tick SHA-256 world hash.

use std::collections::{BTreeMap, BTreeSet};

use xace_core::errors::determinism_error::{DeterminismRule, DeterminismViolation, GuardMode};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::runtime::phase_enum::PhaseEnum;
use xace_core::runtime::world_snapshot::WorldSnapshot;

// ── CHANGE 1: Import the real WorldHasher ────────────────────────────────────
// Both files live in packages/runtime-core/src/determinism_guard/ as siblings.
// `super` goes up to the determinism_guard module; world_hasher is a
// sibling module declared in mod.rs as: pub mod world_hasher;

use super::world_hasher::WorldHasher;

// ── Guard State ───────────────────────────────────────────────────────────────

/// All mutable tracking state for the DeterminismGuard.
///
/// Separated from the guard struct to keep the public API surface clean
/// and allow the guard to pass `&mut state` internally without borrow conflicts.
#[derive(Debug, Default)]
struct GuardState {
    /// Current simulation tick. Set by hook_tick_start.
    current_tick: u64,

    /// Current execution phase. Set by hook_phase_start, cleared by hook_phase_end.
    current_phase: Option<PhaseEnum>,

    /// Schema version locked at guard construction (D10).
    /// Every hook_tick_start validates the live version matches this.
    locked_schema_version: String,

    /// ExecutionPlan version locked at guard construction (D10).
    locked_execution_plan_version: u32,

    /// System IDs registered from the ExecutionPlan.
    /// hook_system_execute validates all system_ids against this set (D1).
    /// BTreeSet for deterministic iteration if inspection is ever needed.
    registered_system_ids: BTreeSet<String>,

    /// Per-tick world hashes recorded during live simulation.
    /// BTreeMap<tick → hash> for stable ordering (D11).
    /// Used by validate_replay_hash() to detect divergence during replay (D14).
    tick_hash_log: BTreeMap<u64, String>,

    /// All violations recorded this session.
    /// Populated regardless of guard mode — mode controls output only.
    violation_log: Vec<DeterminismViolation>,

    /// True between hook_tick_start and hook_tick_end. Used by D15 enforcement.
    inside_tick: bool,

    /// True between hook_phase_start and hook_phase_end. Used by D15 enforcement.
    inside_phase: bool,
}

// ── Determinism Guard ─────────────────────────────────────────────────────────

/// Hook-based enforcer for XACE determinism rules.
///
/// RuntimeOrchestrator owns one guard for the live tick path and
/// PhaseOrchestrator calls the tick, phase, system, and hash hooks at their
/// correct boundaries every tick (D15).
///
/// ## Lifecycle
/// ```text
/// let mut guard = DeterminismGuard::new(GuardMode::Strict, "0.1.0", 1);
/// guard.register_systems(&["sys_movement", "sys_ai", "sys_health"]);
///
/// // Each tick:
/// guard.hook_tick_start(tick, &schema_version, plan_version)?;
/// for phase in PhaseEnum::ALL {
///     guard.hook_phase_start(tick, phase)?;
///     for system_id in &systems_in_phase {
///         guard.hook_system_execute(tick, phase, system_id)?;
///         // ... run system ...
///     }
///     guard.hook_phase_end(tick, phase)?;
/// }
/// let hash = guard.hook_tick_end(&snapshot)?;
/// ```
pub struct DeterminismGuard {
    /// Operating mode — controls how violations are reported.
    mode: GuardMode,

    /// All mutable guard tracking state.
    state: GuardState,
}

impl DeterminismGuard {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new DeterminismGuard with locked version contracts.
    ///
    /// `schema_version` and `execution_plan_version` are locked at construction.
    /// hook_tick_start validates the live runtime matches these on every tick (D10).
    /// Any version drift is always fatal — no guard mode can suppress D10.
    pub fn new(
        mode: GuardMode,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
    ) -> Self {
        Self {
            mode,
            state: GuardState {
                locked_schema_version: schema_version.into(),
                locked_execution_plan_version: execution_plan_version,
                ..Default::default()
            },
        }
    }

    /// Registers all system IDs from the ExecutionPlan.
    ///
    /// Must be called before the first tick. All system IDs passed to
    /// hook_system_execute must be present in this set or a D1 violation
    /// is raised. Call with the full flattened list from ExecutionPlan.
    pub fn register_systems(&mut self, system_ids: &[&str]) {
        for id in system_ids {
            self.state.registered_system_ids.insert(id.to_string());
        }
    }

    // ── Hook 1: Tick Start ────────────────────────────────────────────────────

    /// Hook 1 — Call at the very start of every tick, before any phase begins.
    ///
    /// Enforces:
    /// - D10: live schema_version must match locked version (always fatal)
    /// - D10: live execution_plan_version must match locked version (always fatal)
    /// - D15: establishes the tick window used by hooks 2–5
    ///
    /// Returns Err in all guard modes on D10 violation — schema mismatch
    /// is too dangerous to allow even in DEV or SILENT mode.
    /// Re-locks schema/plan contracts at a tick boundary after a validated
    /// runtime hot-swap while preserving the historical per-tick hash log.
    pub fn reconfigure_for_hot_swap(
        &mut self,
        schema_version: impl Into<String>,
        execution_plan_version: u32,
        system_ids: &[&str],
    ) {
        self.state.locked_schema_version = schema_version.into();
        self.state.locked_execution_plan_version = execution_plan_version;
        self.state.registered_system_ids.clear();
        self.register_systems(system_ids);
        self.state.current_phase = None;
        self.state.inside_tick = false;
        self.state.inside_phase = false;
    }

    pub fn hook_tick_start(
        &mut self,
        tick: u64,
        schema_version: &str,
        execution_plan_version: u32,
    ) -> Result<(), XaceError> {
        self.state.current_tick = tick;
        self.state.current_phase = None;
        self.state.inside_phase = false;

        // D10: schema version must match locked version exactly.
        // Always fatal — no mode can suppress this.
        if schema_version != self.state.locked_schema_version {
            let violation = DeterminismViolation::new(
                DeterminismRule::D10SchemaVersionMatch,
                "DeterminismGuard",
                tick,
                format!(
                    "Schema version mismatch at tick {}: locked='{}' but runtime='{}'",
                    tick, self.state.locked_schema_version, schema_version
                ),
                self.mode,
            );
            return Err(self.handle_violation_always_fatal(violation));
        }

        // D10: execution plan version must also match.
        if execution_plan_version != self.state.locked_execution_plan_version {
            let violation = DeterminismViolation::new(
                DeterminismRule::D10SchemaVersionMatch,
                "DeterminismGuard",
                tick,
                format!(
                    "ExecutionPlan version mismatch at tick {}: locked={} but runtime={}",
                    tick, self.state.locked_execution_plan_version, execution_plan_version
                ),
                self.mode,
            );
            return Err(self.handle_violation_always_fatal(violation));
        }

        self.state.inside_tick = true;
        Ok(())
    }

    // ── Hook 2: Phase Start ───────────────────────────────────────────────────

    /// Hook 2 — Call at the start of each phase, before any system runs.
    ///
    /// Enforces:
    /// - D15: hook_tick_start must have been called first this tick
    pub fn hook_phase_start(&mut self, tick: u64, phase: PhaseEnum) -> Result<(), XaceError> {
        // D15: must be inside an active tick window
        if !self.state.inside_tick {
            let violation = DeterminismViolation::new(
                DeterminismRule::D15GuardAtEveryBoundary,
                "DeterminismGuard",
                tick,
                format!(
                    "hook_phase_start({:?}) called at tick {} but hook_tick_start \
                     was not called — guard boundary violated (D15)",
                    phase, tick
                ),
                self.mode,
            );
            return self.handle_violation(violation);
        }

        self.state.current_phase = Some(phase);
        self.state.inside_phase = true;
        Ok(())
    }

    // ── Hook 3: System Execute ────────────────────────────────────────────────

    /// Hook 3 — Call immediately before running each system.
    ///
    /// Enforces:
    /// - D1: system_id must be registered in the ExecutionPlan
    /// - D15: must be called within an open phase window
    pub fn hook_system_execute(
        &mut self,
        tick: u64,
        phase: PhaseEnum,
        system_id: &str,
    ) -> Result<(), XaceError> {
        // D15: must be inside an active phase window
        if !self.state.inside_phase {
            let violation = DeterminismViolation::new(
                DeterminismRule::D15GuardAtEveryBoundary,
                system_id,
                tick,
                format!(
                    "System '{}' executed at tick {} without an open phase window — \
                     hook_phase_start must precede hook_system_execute (D15)",
                    system_id, tick
                ),
                self.mode,
            )
            .with_phase(phase.as_u8());
            return self.handle_violation(violation);
        }

        // D1: system must be registered in the ExecutionPlan
        if !self.state.registered_system_ids.contains(system_id) {
            let violation = DeterminismViolation::new(
                DeterminismRule::D1SystemOrderFromPlanOnly,
                system_id,
                tick,
                format!(
                    "System '{}' at tick {} phase {:?} is not registered in the \
                     ExecutionPlan — unregistered systems violate D1",
                    system_id, tick, phase
                ),
                self.mode,
            )
            .with_phase(phase.as_u8());
            return self.handle_violation(violation);
        }

        Ok(())
    }

    // ── Hook 4: Phase End ─────────────────────────────────────────────────────

    /// Hook 4 — Call after all systems in a phase complete and after the
    /// Mutation Gate and EventBus have been flushed for this phase.
    ///
    /// Enforces:
    /// - D15: closes the phase window opened by hook_phase_start
    pub fn hook_phase_end(&mut self, _tick: u64, _phase: PhaseEnum) -> Result<(), XaceError> {
        self.state.inside_phase = false;
        self.state.current_phase = None;
        Ok(())
    }

    // ── Hook 5: Tick End ──────────────────────────────────────────────────────

    /// Hook 5 — Call after all five phases complete and after the Mutation Gate
    /// and EventBus are fully flushed. The snapshot passed in must reflect the
    /// complete final state of the tick.
    ///
    /// Enforces:
    /// - D9: computes world_hash from snapshot using WorldHasher::compute()
    /// - D11: hash uses BTreeMap iteration (type_id ASC, EntityID ASC)
    /// - D3:  entity store fed in EntityID ASC order (SnapshotEngine guarantee)
    ///
    /// If the snapshot already carries a non-empty world_hash, this hook validates
    /// the computed hash matches it — this is the replay desync detection path (D9).
    ///
    /// Returns the computed world_hash so the PhaseOrchestrator can store it
    /// in the committed WorldSnapshot.
    pub fn hook_tick_end(&mut self, snapshot: &WorldSnapshot) -> Result<String, XaceError> {
        let tick = snapshot.tick;
        self.state.inside_tick = false;

        // ── CHANGE 2: Use WorldHasher::compute() — real SHA-256, not placeholder ──
        //
        // WorldHasher feeds tick/version identity, cgs_hash, RNG/event/mutation
        // snapshot state, clean-boundary status, entity store, and component
        // tables in stable D11 order.
        let computed_hash = WorldHasher::compute(snapshot);

        // Validate against an existing hash if present (replay / resync path)
        if !snapshot.world_hash.is_empty() && snapshot.world_hash != computed_hash {
            let violation = DeterminismViolation::hash_mismatch(
                DeterminismRule::D9WorldHashPerTick,
                "DeterminismGuard",
                tick,
                &snapshot.world_hash,
                &computed_hash,
                self.mode,
            );
            // In STRICT mode this returns Err and the hash is not logged.
            // In DEV/SILENT mode the violation is recorded but we continue.
            self.handle_violation(violation)?;
        }

        // Record hash for this tick — used by validate_replay_hash() (D14)
        self.state.tick_hash_log.insert(tick, computed_hash.clone());
        Ok(computed_hash)
    }

    // ── Hook 6: RNG Access ────────────────────────────────────────────────────

    /// Hook 6 — Call from the RNG interceptor whenever random values are generated.
    ///
    /// Enforces:
    /// - D6: only DeterministicRNG is allowed — no OS or language-native RNG
    ///
    /// `is_deterministic` must be true when called from DeterministicRNG.
    /// The RngInterceptor calls this with `is_deterministic = false` before
    /// blocking any OS/language RNG call, triggering this violation.
    pub fn hook_rng_access(
        &mut self,
        tick: u64,
        system_id: &str,
        is_deterministic: bool,
    ) -> Result<(), XaceError> {
        if !is_deterministic {
            let violation = DeterminismViolation::new(
                DeterminismRule::D6DeterministicRngOnly,
                system_id,
                tick,
                format!(
                    "System '{}' attempted OS or language-native RNG at tick {} — \
                     only DeterministicRNG with seed=hash(world_seed, system_id, tick) \
                     is permitted (D6)",
                    system_id, tick
                ),
                self.mode,
            );
            return self.handle_violation(violation);
        }
        Ok(())
    }

    // ── Replay Hash Validation ────────────────────────────────────────────────

    /// Validates a replay tick hash against the hash recorded during the original run.
    ///
    /// Called by ReplayValidator (replay_validator.rs) in REPLAY mode.
    /// If the hashes differ the replay has diverged — D14 violation.
    /// If no recorded hash exists for this tick it is treated as first-run
    /// and the hash is recorded (normal path during initial capture).
    pub fn validate_replay_hash(&mut self, tick: u64, replay_hash: &str) -> Result<(), XaceError> {
        match self.state.tick_hash_log.get(&tick) {
            Some(expected) if expected != replay_hash => {
                let expected_owned = expected.clone();
                let violation = DeterminismViolation::hash_mismatch(
                    DeterminismRule::D14ReplayRequiresThreeInputs,
                    "ReplayValidator",
                    tick,
                    expected_owned,
                    replay_hash,
                    self.mode,
                );
                self.handle_violation(violation)
            }
            None => {
                // First run — record the hash for future replay comparison
                self.state
                    .tick_hash_log
                    .insert(tick, replay_hash.to_string());
                Ok(())
            }
            _ => Ok(()), // Hash matches — determinism confirmed
        }
    }

    // ── Inspection API ────────────────────────────────────────────────────────

    /// Returns all violations recorded this session, in detection order.
    pub fn violations(&self) -> &[DeterminismViolation] {
        &self.state.violation_log
    }

    /// Returns the total number of violations recorded this session.
    pub fn violation_count(&self) -> usize {
        self.state.violation_log.len()
    }

    /// Returns true if any violations have been recorded.
    pub fn has_violations(&self) -> bool {
        !self.state.violation_log.is_empty()
    }

    /// Returns all violations for a specific D-rule.
    pub fn violations_for_rule(&self, rule: DeterminismRule) -> Vec<&DeterminismViolation> {
        self.state
            .violation_log
            .iter()
            .filter(|v| v.rule == rule)
            .collect()
    }

    /// Returns the world hash recorded at a specific tick, if any.
    pub fn hash_at_tick(&self, tick: u64) -> Option<&str> {
        self.state.tick_hash_log.get(&tick).map(|s| s.as_str())
    }

    /// Returns all recorded tick hashes in ascending tick order.
    pub fn hash_log(&self) -> Vec<(u64, String)> {
        self.state
            .tick_hash_log
            .iter()
            .map(|(tick, hash)| (*tick, hash.clone()))
            .collect()
    }

    /// Returns the latest recorded tick hash, if any.
    pub fn latest_hash(&self) -> Option<(u64, &str)> {
        self.state
            .tick_hash_log
            .iter()
            .next_back()
            .map(|(tick, hash)| (*tick, hash.as_str()))
    }

    /// Returns the current guard mode.
    pub fn mode(&self) -> GuardMode {
        self.mode
    }

    // ── Internal Violation Handling ───────────────────────────────────────────

    /// Handles a violation according to the current guard mode.
    ///
    /// Always records the violation in violation_log.
    /// Mode controls output and whether Err is returned:
    /// - STRICT: log to stderr, return Err(FatalError) — simulation halts
    /// - DEV:    log to stderr, return Ok(()) — simulation continues
    /// - SILENT: no output,    return Ok(()) — CI/test silent recording
    fn handle_violation(&mut self, violation: DeterminismViolation) -> Result<(), XaceError> {
        self.state.violation_log.push(violation.clone());
        match self.mode {
            GuardMode::Strict => {
                eprintln!(
                    "[XACE][STRICT][{}] {}",
                    violation.rule.rule_id(),
                    violation.summary()
                );
                Err(Self::make_fatal_error(&violation))
            }
            GuardMode::Dev => {
                eprintln!(
                    "[XACE][DEV][{}] {}",
                    violation.rule.rule_id(),
                    violation.summary()
                );
                Ok(()) // Log and continue in DEV mode
            }
            GuardMode::Silent => {
                Ok(()) // Record only — no output in SILENT mode
            }
        }
    }

    /// Handles a violation that is ALWAYS fatal regardless of guard mode.
    ///
    /// Used exclusively for D10 (schema version mismatch). Version mismatch
    /// can never be silently ignored — it will corrupt replay and network sync.
    /// Returns XaceError directly (not Result) because callers always wrap it in Err.
    fn handle_violation_always_fatal(&mut self, violation: DeterminismViolation) -> XaceError {
        self.state.violation_log.push(violation.clone());
        eprintln!(
            "[XACE][FATAL][{}] {}",
            violation.rule.rule_id(),
            violation.summary()
        );
        Self::make_fatal_error(&violation)
    }

    /// Constructs a XaceError::FatalError from a DeterminismViolation.
    fn make_fatal_error(violation: &DeterminismViolation) -> XaceError {
        XaceError::FatalError {
            message: violation.summary(),
            context: ErrorContext::new("DeterminismGuard", violation.rule.rule_id())
                .with_tick(violation.tick),
            snapshot_recovery_possible: true,
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use xace_core::runtime::world_snapshot::WorldSnapshot;

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// STRICT guard — violations return Err immediately.
    fn strict_guard() -> DeterminismGuard {
        let mut g = DeterminismGuard::new(GuardMode::Strict, "0.1.0", 1);
        g.register_systems(&["sys_movement", "sys_ai", "sys_health"]);
        g
    }

    /// SILENT guard — violations recorded but Ok() returned. Used for
    /// multi-violation tests where we don't want early Err to stop the sequence.
    fn silent_guard() -> DeterminismGuard {
        let mut g = DeterminismGuard::new(GuardMode::Silent, "0.1.0", 1);
        g.register_systems(&["sys_movement", "sys_ai", "sys_health"]);
        g
    }

    /// Snapshot with empty world_hash so hook_tick_end computes fresh.
    fn empty_snapshot(tick: u64) -> WorldSnapshot {
        let mut s = WorldSnapshot::empty("0.1.0", 1, 42);
        s.tick = tick;
        s // world_hash is empty — hook_tick_end will compute and record it
    }

    // ── Hook 1: Tick Start ────────────────────────────────────────────────────

    #[test]
    fn tick_start_passes_matching_versions() {
        let mut g = strict_guard();
        assert!(g.hook_tick_start(1, "0.1.0", 1).is_ok());
    }

    #[test]
    fn tick_start_fails_schema_mismatch_in_strict() {
        let mut g = strict_guard();
        let result = g.hook_tick_start(1, "0.2.0", 1);
        assert!(result.is_err());
        assert_eq!(g.violation_count(), 1);
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D10SchemaVersionMatch
        );
    }

    #[test]
    fn tick_start_fails_schema_mismatch_even_in_silent() {
        // D10 is always fatal — SILENT mode cannot suppress it
        let mut g = silent_guard();
        let result = g.hook_tick_start(1, "0.9.9", 1);
        assert!(result.is_err(), "D10 must be fatal in all modes");
        assert_eq!(g.violation_count(), 1);
    }

    #[test]
    fn tick_start_fails_plan_version_mismatch() {
        let mut g = strict_guard();
        let result = g.hook_tick_start(1, "0.1.0", 99);
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D10SchemaVersionMatch
        );
    }

    // ── Hook 2: Phase Start ───────────────────────────────────────────────────

    #[test]
    fn phase_start_requires_tick_start_first() {
        let mut g = strict_guard();
        // Deliberately skip hook_tick_start
        let result = g.hook_phase_start(1, PhaseEnum::Simulation);
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D15GuardAtEveryBoundary
        );
    }

    #[test]
    fn phase_start_succeeds_after_tick_start() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        assert!(g.hook_phase_start(1, PhaseEnum::Simulation).is_ok());
    }

    // ── Hook 3: System Execute ────────────────────────────────────────────────

    #[test]
    fn system_execute_rejects_unregistered_system() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        g.hook_phase_start(1, PhaseEnum::Simulation).unwrap();
        let result = g.hook_system_execute(1, PhaseEnum::Simulation, "sys_unknown");
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D1SystemOrderFromPlanOnly
        );
    }

    #[test]
    fn system_execute_accepts_registered_system() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        g.hook_phase_start(1, PhaseEnum::Simulation).unwrap();
        assert!(g
            .hook_system_execute(1, PhaseEnum::Simulation, "sys_movement")
            .is_ok());
    }

    #[test]
    fn system_execute_rejects_without_open_phase() {
        let mut g = strict_guard();
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        // No hook_phase_start — phase window is closed
        let result = g.hook_system_execute(1, PhaseEnum::Simulation, "sys_movement");
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D15GuardAtEveryBoundary
        );
    }

    // ── Hook 5: Tick End ──────────────────────────────────────────────────────

    #[test]
    fn tick_end_computes_and_records_hash() {
        let mut g = strict_guard();
        let snap = empty_snapshot(1);
        let result = g.hook_tick_end(&snap);
        assert!(result.is_ok());
        assert!(g.hash_at_tick(1).is_some());
        // ── CHANGE 3: hash is now a real 64-char SHA-256 hex string ──
        let hash = g.hash_at_tick(1).unwrap();
        assert_eq!(
            hash.len(),
            64,
            "WorldHasher must produce a 64-char SHA-256 hex"
        );
        assert!(!hash.is_empty());
    }

    #[test]
    fn tick_end_accepts_empty_world_hash_in_snapshot() {
        // Normal path: snapshot arrives with empty hash, guard computes it
        let mut g = strict_guard();
        let snap = empty_snapshot(5);
        assert!(snap.world_hash.is_empty());
        assert!(g.hook_tick_end(&snap).is_ok());
    }

    #[test]
    fn tick_end_rejects_mismatched_existing_hash() {
        let mut g = strict_guard();
        let mut snap = empty_snapshot(1);
        snap.world_hash = "deliberately_wrong_hash_xyz".into();
        let result = g.hook_tick_end(&snap);
        assert!(result.is_err());
        assert_eq!(g.violations()[0].rule, DeterminismRule::D9WorldHashPerTick);
    }

    // ── CHANGE 4: This test previously called compute_world_hash_placeholder()
    // directly. Now it uses WorldHasher::compute() — the same function that
    // hook_tick_end uses. Logic is identical: compute expected, set it, validate.
    #[test]
    fn tick_end_accepts_correct_precomputed_hash() {
        let mut g = strict_guard();
        let mut snap = empty_snapshot(2);
        // Ask WorldHasher what the hash for this snapshot will be,
        // then set it — hook_tick_end must accept it without violation.
        let expected = WorldHasher::compute(&snap);
        snap.world_hash = expected;
        assert!(g.hook_tick_end(&snap).is_ok());
        assert_eq!(g.violation_count(), 0);
    }

    // ── New test: hash is real SHA-256, not the old placeholder format ────────
    #[test]
    fn tick_end_hash_is_sha256_format_not_placeholder() {
        let mut g = strict_guard();
        let snap = empty_snapshot(1);
        let hash = g.hook_tick_end(&snap).unwrap();
        // Old placeholder started with "placeholder:" — real hash must not
        assert!(
            !hash.starts_with("placeholder:"),
            "hash must be real SHA-256, not the old placeholder string"
        );
        // Real SHA-256 is exactly 64 lowercase hex chars
        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    // ── Hook 6: RNG Access ────────────────────────────────────────────────────

    #[test]
    fn rng_access_allows_deterministic_calls() {
        let mut g = strict_guard();
        assert!(g.hook_rng_access(1, "sys_movement", true).is_ok());
    }

    #[test]
    fn rng_access_rejects_nondeterministic() {
        let mut g = strict_guard();
        let result = g.hook_rng_access(1, "sys_ai", false);
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D6DeterministicRngOnly
        );
        assert_eq!(g.violations()[0].system_context, "sys_ai");
        assert_eq!(g.violations()[0].tick, 1);
    }

    // ── Replay Validation ─────────────────────────────────────────────────────

    #[test]
    fn replay_hash_records_on_first_run() {
        let mut g = strict_guard();
        let hash = "a".repeat(64);
        assert!(g.validate_replay_hash(10, &hash).is_ok());
        assert_eq!(g.hash_at_tick(10), Some(hash.as_str()));
    }

    #[test]
    fn replay_hash_passes_on_identical_hash() {
        let mut g = strict_guard();
        let hash = "a".repeat(64);
        g.validate_replay_hash(10, &hash).unwrap();
        assert!(g.validate_replay_hash(10, &hash).is_ok());
        assert_eq!(g.violation_count(), 0);
    }

    #[test]
    fn replay_hash_fails_on_divergence() {
        let mut g = strict_guard();
        g.validate_replay_hash(10, "original_hash").unwrap();
        let result = g.validate_replay_hash(10, "diverged_hash");
        assert!(result.is_err());
        assert_eq!(
            g.violations()[0].rule,
            DeterminismRule::D14ReplayRequiresThreeInputs
        );
        assert!(g.violations()[0].is_hash_mismatch());
    }

    // ── Guard Modes ───────────────────────────────────────────────────────────

    #[test]
    fn silent_mode_records_violations_returns_ok() {
        let mut g = silent_guard();
        // D6 violation in SILENT mode — should record but return Ok
        let result = g.hook_rng_access(1, "sys_bad", false);
        assert!(result.is_ok(), "SILENT mode must return Ok and continue");
        assert_eq!(g.violation_count(), 1);
        assert!(g.has_violations());
    }

    #[test]
    fn silent_mode_accumulates_multiple_violations() {
        let mut g = silent_guard();
        g.hook_rng_access(1, "sys_a", false).ok();
        g.hook_rng_access(2, "sys_b", false).ok();
        g.hook_rng_access(3, "sys_c", false).ok();
        assert_eq!(g.violation_count(), 3);
    }

    #[test]
    fn mode_accessor_returns_correct_mode() {
        assert_eq!(strict_guard().mode(), GuardMode::Strict);
        assert_eq!(silent_guard().mode(), GuardMode::Silent);
        let g = DeterminismGuard::new(GuardMode::Dev, "0.1.0", 1);
        assert_eq!(g.mode(), GuardMode::Dev);
    }

    // ── Inspection API ────────────────────────────────────────────────────────

    #[test]
    fn violations_for_rule_filters_correctly() {
        let mut g = silent_guard();
        g.hook_rng_access(1, "sys_a", false).ok(); // D6
        g.hook_rng_access(2, "sys_b", false).ok(); // D6
        g.validate_replay_hash(5, "hash_1").unwrap();
        g.validate_replay_hash(5, "hash_2").ok(); // D14
        assert_eq!(
            g.violations_for_rule(DeterminismRule::D6DeterministicRngOnly)
                .len(),
            2
        );
        assert_eq!(
            g.violations_for_rule(DeterminismRule::D14ReplayRequiresThreeInputs)
                .len(),
            1
        );
        assert_eq!(
            g.violations_for_rule(DeterminismRule::D3EntityIterationSorted)
                .len(),
            0
        );
    }

    #[test]
    fn hash_at_tick_returns_none_for_unknown_tick() {
        let g = strict_guard();
        assert_eq!(g.hash_at_tick(999), None);
    }

    #[test]
    fn register_systems_allows_those_systems_to_execute() {
        let mut g = DeterminismGuard::new(GuardMode::Strict, "0.1.0", 1);
        g.register_systems(&["sys_x", "sys_y"]);
        g.hook_tick_start(1, "0.1.0", 1).unwrap();
        g.hook_phase_start(1, PhaseEnum::Simulation).unwrap();
        assert!(g
            .hook_system_execute(1, PhaseEnum::Simulation, "sys_x")
            .is_ok());
        assert!(g
            .hook_system_execute(1, PhaseEnum::Simulation, "sys_y")
            .is_ok());
    }

    #[test]
    fn violation_tick_and_system_context_are_correct() {
        let mut g = strict_guard();
        g.hook_rng_access(42, "sys_combat", false).ok();
        let v = &g.violations()[0];
        assert_eq!(v.tick, 42);
        assert_eq!(v.system_context, "sys_combat");
    }
}
