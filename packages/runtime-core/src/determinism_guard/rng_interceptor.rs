//! # RNG Interceptor
//!
//! Enforces determinism rule D6: only DeterministicRNG is permitted.
//! No system may use OS randomness, language-native random functions,
//! or any source of randomness not seeded by hash(world_seed, system_id, tick).
//!
//! ## The Problem This Solves
//! In Rust, nothing stops a system from calling `rand::random::<f32>()` or
//! `thread_rng().gen()` directly. Both produce nondeterministic values that
//! differ across machines, threads, and time. One such call silently breaks
//! replay, network determinism, and rollback — forever, with no error.
//!
//! ## How Interception Works
//! XACE uses a two-layer approach:
//!
//! **Layer 1 — Thread-local context window**
//! When the PhaseOrchestrator hands a system its SystemContext, it opens a
//! DeterministicWindow via RngInterceptor::open_window(). This marks the
//! current thread as "inside a deterministic execution context."
//! The window closes automatically when dropped (RAII).
//!
//! **Layer 2 — Explicit access through the interceptor**
//! Systems must request RNG through `RngInterceptor::request_rng(system_id, tick)`.
//! This validates the window is open and fires hook_rng_access(true) on the
//! DeterminismGuard, recording a legal deterministic RNG access.
//!
//! **Detection of illegal access**
//! Any code that detects OS/language RNG usage calls `report_illegal_rng()`.
//! This fires hook_rng_access(false) on the DeterminismGuard, producing a D6
//! violation with full system and tick context.
//!
//! ## What This Does NOT Do
//! This interceptor cannot magically prevent a system from calling `rand::random()`
//! without going through the interceptor — Rust provides no such hook. The
//! interceptor is a contract enforcement layer, not a sandbox. The static
//! analysis pass in `determinism_code_checker.rs` (Phase 13) handles detecting
//! direct rand usage in generated system code at compile time. This interceptor
//! handles the runtime side: validating every legal RNG access and providing a
//! reporting path for detected illegal ones.
//!
//! ## Deterministic RNG Seeding (D6)
//! seed = SHA-256(world_seed || system_id || tick)[0..8]
//! Same inputs → same seed → same output, always, on every machine.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use sha2::{Digest, Sha256};
use xace_core::errors::determinism_error::{DeterminismRule, DeterminismViolation, GuardMode};
use xace_core::errors::xace_error::{ErrorContext, XaceError};

// ── Thread-local Deterministic Window ────────────────────────────────────────

thread_local! {
    /// Tracks whether the current thread is inside an open deterministic
    /// execution window. Set by DeterministicWindow::open(), cleared on drop.
    static DETERMINISTIC_WINDOW: RefCell<Option<ActiveWindow>> = RefCell::new(None);
}

/// The context captured when a deterministic window is opened.
#[derive(Debug, Clone)]
struct ActiveWindow {
    system_id: String,
    tick: u64,
}

// ── Deterministic Window (RAII Guard) ─────────────────────────────────────────

/// A scoped RAII guard that marks the current thread as inside a valid
/// deterministic execution context.
///
/// Created by `RngInterceptor::open_window()`. Closed automatically on drop.
/// The PhaseOrchestrator opens one window per system execution and drops it
/// before the next system begins.
pub struct DeterministicWindow {
    _private: (),
}

impl DeterministicWindow {
    fn open(system_id: impl Into<String>, tick: u64) -> Self {
        DETERMINISTIC_WINDOW.with(|cell| {
            *cell.borrow_mut() = Some(ActiveWindow {
                system_id: system_id.into(),
                tick,
            });
        });
        DeterministicWindow { _private: () }
    }

    fn current() -> Option<ActiveWindow> {
        DETERMINISTIC_WINDOW.with(|cell| cell.borrow().clone())
    }
}

impl Drop for DeterministicWindow {
    fn drop(&mut self) {
        DETERMINISTIC_WINDOW.with(|cell| {
            *cell.borrow_mut() = None;
        });
    }
}

// ── RNG Access Record ─────────────────────────────────────────────────────────

/// A single recorded RNG access event — legal or illegal.
#[derive(Debug, Clone)]
pub struct RngAccessRecord {
    pub system_id: String,
    pub tick: u64,
    pub is_deterministic: bool,
    /// The seed issued for legal accesses. None for illegal accesses.
    pub seed: Option<u64>,
}

// ── Interceptor Metrics ───────────────────────────────────────────────────────

/// Runtime metrics accumulated by the interceptor across a session.
#[derive(Debug, Clone, Default)]
pub struct InterceptorMetrics {
    pub legal_access_count: u64,
    pub illegal_access_count: u64,
    pub violations_raised: u64,
    pub windowless_access_count: u64,
}

// ── Inner State (Mutex-protected) ─────────────────────────────────────────────

struct InterceptorInner {
    /// All RNG access records this session, keyed by (tick, system_id).
    /// BTreeMap guarantees deterministic iteration for audit (D11).
    access_log: BTreeMap<(u64, String), RngAccessRecord>,
    metrics: InterceptorMetrics,
    violations: Vec<DeterminismViolation>,
}

// ── RNG Interceptor ───────────────────────────────────────────────────────────

/// Runtime enforcement of determinism rule D6.
///
/// Central authority for all RNG access in the XACE runtime.
/// Held by the PhaseOrchestrator and passed into SystemContext.
///
/// ## Thread Safety
/// Access log, metrics, and violations are protected by a Mutex.
/// Window state lives in thread-local storage — no cross-thread locking needed.
pub struct RngInterceptor {
    world_seed: u64,
    mode: GuardMode,
    inner: Arc<Mutex<InterceptorInner>>,
}

impl RngInterceptor {
    // ── Construction ──────────────────────────────────────────────────────────

    /// Creates a new RngInterceptor with the given world seed and guard mode.
    pub fn new(world_seed: u64, mode: GuardMode) -> Self {
        Self {
            world_seed,
            mode,
            inner: Arc::new(Mutex::new(InterceptorInner {
                access_log: BTreeMap::new(),
                metrics: InterceptorMetrics::default(),
                violations: Vec::new(),
            })),
        }
    }

    // ── Window Management ─────────────────────────────────────────────────────

    /// Opens a deterministic execution window for the given system and tick.
    ///
    /// Called by PhaseOrchestrator immediately before running each system.
    /// Drop the returned window before the next system begins.
    pub fn open_window(&self, system_id: impl Into<String>, tick: u64) -> DeterministicWindow {
        DeterministicWindow::open(system_id, tick)
    }

    // ── Legal RNG Access ──────────────────────────────────────────────────────

    /// Requests a deterministic RNG seed for the current system and tick.
    ///
    /// Must be called from within an open DeterministicWindow whose system_id
    /// and tick match the arguments. Returns the seed on success.
    ///
    /// On windowless access or window mismatch: D6 violation, mode-controlled.
    pub fn request_rng(&self, system_id: &str, tick: u64) -> Result<u64, XaceError> {
        match DeterministicWindow::current() {
            Some(window) if window.system_id == system_id && window.tick == tick => {
                // Window matches — legal access path
                let seed = Self::derive_seed(self.world_seed, system_id, tick);
                let record = RngAccessRecord {
                    system_id: system_id.to_string(),
                    tick,
                    is_deterministic: true,
                    seed: Some(seed),
                };
                let mut inner = self.inner.lock().unwrap();
                inner.access_log.insert((tick, system_id.to_string()), record);
                inner.metrics.legal_access_count += 1;
                Ok(seed)
            }

            Some(window) => {
                // Window is open but for the wrong system or tick
                Err(self.raise_d6_violation(
                    system_id,
                    tick,
                    format!(
                        "System '{}' at tick {} requested RNG under window owned by \
                         '{}' at tick {} — window context mismatch (D6)",
                        system_id, tick, window.system_id, window.tick
                    ),
                ))
            }

            None => {
                // No window open at all
                {
                    let mut inner = self.inner.lock().unwrap();
                    inner.metrics.windowless_access_count += 1;
                }
                Err(self.raise_d6_violation(
                    system_id,
                    tick,
                    format!(
                        "System '{}' at tick {} requested RNG outside a deterministic \
                         window — PhaseOrchestrator must open a window before running \
                         any system (D6, D15)",
                        system_id, tick
                    ),
                ))
            }
        }
    }

    // ── Illegal RNG Reporting ─────────────────────────────────────────────────

    /// Reports a detected illegal (OS or language-native) RNG access.
    ///
    /// Call from any instrumentation that detects non-deterministic rand usage.
    /// Produces a D6 violation and handles it per the current guard mode:
    /// - STRICT: returns Err(FatalError) — simulation halts
    /// - DEV:    logs, records violation, returns Ok(())
    /// - SILENT: records violation silently, returns Ok(())
    pub fn report_illegal_rng(&self, system_id: &str, tick: u64) -> Result<(), XaceError> {
        {
            let mut inner = self.inner.lock().unwrap();
            inner.access_log.insert(
                (tick, system_id.to_string()),
                RngAccessRecord {
                    system_id: system_id.to_string(),
                    tick,
                    is_deterministic: false,
                    seed: None,
                },
            );
            inner.metrics.illegal_access_count += 1;
        }

        let err = self.raise_d6_violation(
            system_id,
            tick,
            format!(
                "System '{}' at tick {} used OS or language-native RNG — \
                 rand::random(), thread_rng(), SmallRng::from_entropy() and any \
                 entropy-sourced RNG are forbidden. Use DeterministicRng via \
                 RngInterceptor::request_rng() only (D6)",
                system_id, tick
            ),
        );

        match self.mode {
            GuardMode::Strict => Err(err),
            GuardMode::Dev | GuardMode::Silent => Ok(()),
        }
    }

    // ── Seed Derivation ───────────────────────────────────────────────────────

    /// Derives the deterministic seed for a system at a specific tick.
    ///
    /// seed = SHA-256(world_seed_be || len(system_id)_be || system_id_bytes || tick_be)[0..8]
    ///
    /// Length-prefixing system_id prevents adjacent-field collisions.
    /// Same (world_seed, system_id, tick) → same u64, always, on any machine. (D6)
    pub fn derive_seed(world_seed: u64, system_id: &str, tick: u64) -> u64 {
        let mut hasher = Sha256::new();
        hasher.update(world_seed.to_be_bytes());
        hasher.update((system_id.len() as u64).to_be_bytes());
        hasher.update(system_id.as_bytes());
        hasher.update(tick.to_be_bytes());
        let digest = hasher.finalize();
        u64::from_be_bytes(digest[..8].try_into().unwrap())
    }

    // ── Inspection API ────────────────────────────────────────────────────────

    /// Returns a copy of accumulated interceptor metrics.
    pub fn metrics(&self) -> InterceptorMetrics {
        self.inner.lock().unwrap().metrics.clone()
    }

    /// Returns all D6 violations recorded this session.
    pub fn violations(&self) -> Vec<DeterminismViolation> {
        self.inner.lock().unwrap().violations.clone()
    }

    /// Returns the total number of D6 violations produced.
    pub fn violation_count(&self) -> usize {
        self.inner.lock().unwrap().violations.len()
    }

    /// Returns true if any violations have been recorded.
    pub fn has_violations(&self) -> bool {
        self.violation_count() > 0
    }

    /// Returns all RNG access records for a specific system, in tick order.
    pub fn accesses_for_system(&self, system_id: &str) -> Vec<RngAccessRecord> {
        self.inner
            .lock()
            .unwrap()
            .access_log
            .iter()
            .filter(|((_, sid), _)| sid == system_id)
            .map(|(_, r)| r.clone())
            .collect()
    }

    /// Returns the seed that was issued for a (system_id, tick) pair.
    /// Returns None if no legal access was recorded for that pair.
    pub fn seed_for(&self, system_id: &str, tick: u64) -> Option<u64> {
        self.inner
            .lock()
            .unwrap()
            .access_log
            .get(&(tick, system_id.to_string()))
            .and_then(|r| r.seed)
    }

    /// Returns the world seed this interceptor was created with.
    pub fn world_seed(&self) -> u64 {
        self.world_seed
    }

    /// Resets all accumulated state — access log, metrics, violations.
    /// Used between sessions or in test teardown.
    pub fn reset(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.access_log.clear();
        inner.metrics = InterceptorMetrics::default();
        inner.violations.clear();
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /// Records a D6 violation and returns the corresponding XaceError.
    fn raise_d6_violation(&self, system_id: &str, tick: u64, description: String) -> XaceError {
        let violation = DeterminismViolation::new(
            DeterminismRule::D6DeterministicRngOnly,
            system_id,
            tick,
            &description,
            self.mode,
        );
        {
            let mut inner = self.inner.lock().unwrap();
            inner.violations.push(violation);
            inner.metrics.violations_raised += 1;
        }
        if matches!(self.mode, GuardMode::Dev | GuardMode::Strict) {
            eprintln!(
                "[XACE][{}][D6] Illegal RNG: system='{}' tick={}",
                self.mode, system_id, tick
            );
        }
        XaceError::FatalError {
            message: description,
            context: ErrorContext::new("RngInterceptor", "D6_violation")
                .with_tick(tick)
                .with_detail("system_id", system_id),
            snapshot_recovery_possible: false,
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn strict(seed: u64) -> RngInterceptor {
        RngInterceptor::new(seed, GuardMode::Strict)
    }

    fn silent(seed: u64) -> RngInterceptor {
        RngInterceptor::new(seed, GuardMode::Silent)
    }

    // ── Seed Derivation ───────────────────────────────────────────────────────

    #[test]
    fn same_inputs_produce_same_seed() {
        let a = RngInterceptor::derive_seed(42, "sys_movement", 100);
        let b = RngInterceptor::derive_seed(42, "sys_movement", 100);
        assert_eq!(a, b, "Same inputs must always produce same seed (D6)");
    }

    #[test]
    fn different_system_ids_produce_different_seeds() {
        let a = RngInterceptor::derive_seed(42, "sys_movement", 100);
        let b = RngInterceptor::derive_seed(42, "sys_ai", 100);
        assert_ne!(a, b);
    }

    #[test]
    fn different_ticks_produce_different_seeds() {
        let a = RngInterceptor::derive_seed(42, "sys_movement", 1);
        let b = RngInterceptor::derive_seed(42, "sys_movement", 2);
        assert_ne!(a, b);
    }

    #[test]
    fn different_world_seeds_produce_different_seeds() {
        let a = RngInterceptor::derive_seed(1, "sys_ai", 10);
        let b = RngInterceptor::derive_seed(2, "sys_ai", 10);
        assert_ne!(a, b);
    }

    #[test]
    fn length_prefix_prevents_field_collision() {
        // "sys_ab" and "sys_a" must not collide at same tick/world_seed
        let a = RngInterceptor::derive_seed(0, "sys_ab", 0);
        let b = RngInterceptor::derive_seed(0, "sys_a", 0);
        assert_ne!(a, b);
    }

    // ── Window Management ─────────────────────────────────────────────────────

    #[test]
    fn window_open_sets_thread_local() {
        let _win = DeterministicWindow::open("sys_test", 1);
        let ctx = DeterministicWindow::current();
        assert!(ctx.is_some());
        assert_eq!(ctx.unwrap().system_id, "sys_test");
    }

    #[test]
    fn window_drop_clears_thread_local() {
        {
            let _win = DeterministicWindow::open("sys_test", 1);
            assert!(DeterministicWindow::current().is_some());
        }
        assert!(DeterministicWindow::current().is_none());
    }

    #[test]
    fn no_window_by_default() {
        assert!(DeterministicWindow::current().is_none());
    }

    // ── Legal RNG Access ──────────────────────────────────────────────────────

    #[test]
    fn request_rng_succeeds_with_correct_window() {
        let i = strict(99);
        let _win = i.open_window("sys_movement", 5);
        assert!(i.request_rng("sys_movement", 5).is_ok());
    }

    #[test]
    fn request_rng_returns_derive_seed_output() {
        let i = strict(42);
        let _win = i.open_window("sys_ai", 10);
        let seed = i.request_rng("sys_ai", 10).unwrap();
        assert_eq!(seed, RngInterceptor::derive_seed(42, "sys_ai", 10));
    }

    #[test]
    fn request_rng_fails_without_window() {
        let i = strict(42);
        let result = i.request_rng("sys_movement", 1);
        assert!(result.is_err());
        assert_eq!(i.violation_count(), 1);
        assert_eq!(i.metrics().windowless_access_count, 1);
    }

    #[test]
    fn request_rng_fails_on_system_id_mismatch() {
        let i = strict(42);
        let _win = i.open_window("sys_movement", 5);
        assert!(i.request_rng("sys_ai", 5).is_err());
        assert_eq!(i.violation_count(), 1);
    }

    #[test]
    fn request_rng_fails_on_tick_mismatch() {
        let i = strict(42);
        let _win = i.open_window("sys_movement", 5);
        assert!(i.request_rng("sys_movement", 9).is_err());
        assert_eq!(i.violation_count(), 1);
    }

    #[test]
    fn legal_access_increments_metric() {
        let i = strict(1);
        let _win = i.open_window("sys_health", 1);
        i.request_rng("sys_health", 1).unwrap();
        assert_eq!(i.metrics().legal_access_count, 1);
        assert_eq!(i.metrics().violations_raised, 0);
    }

    #[test]
    fn seed_for_returns_issued_seed() {
        let i = strict(7);
        let _win = i.open_window("sys_ai", 3);
        let issued = i.request_rng("sys_ai", 3).unwrap();
        assert_eq!(i.seed_for("sys_ai", 3), Some(issued));
    }

    #[test]
    fn seed_for_returns_none_for_unaccessed_pair() {
        let i = strict(7);
        assert_eq!(i.seed_for("sys_movement", 999), None);
    }

    // ── Illegal RNG Reporting ─────────────────────────────────────────────────

    #[test]
    fn report_illegal_rng_returns_err_in_strict() {
        let i = strict(0);
        assert!(i.report_illegal_rng("sys_bad", 1).is_err());
    }

    #[test]
    fn report_illegal_rng_returns_ok_in_silent() {
        let i = silent(0);
        assert!(i.report_illegal_rng("sys_bad", 1).is_ok());
    }

    #[test]
    fn report_illegal_rng_records_violation() {
        let i = silent(0);
        i.report_illegal_rng("sys_bad", 5).ok();
        assert_eq!(i.violation_count(), 1);
        assert!(i.has_violations());
    }

    #[test]
    fn multiple_illegal_reports_accumulate() {
        let i = silent(0);
        i.report_illegal_rng("sys_a", 1).ok();
        i.report_illegal_rng("sys_b", 2).ok();
        i.report_illegal_rng("sys_c", 3).ok();
        assert_eq!(i.metrics().illegal_access_count, 3);
        assert_eq!(i.violation_count(), 3);
    }

    #[test]
    fn violation_carries_correct_rule_system_and_tick() {
        let i = silent(0);
        i.report_illegal_rng("sys_combat", 42).ok();
        let v = i.violations();
        assert_eq!(v[0].rule, DeterminismRule::D6DeterministicRngOnly);
        assert_eq!(v[0].system_context, "sys_combat");
        assert_eq!(v[0].tick, 42);
    }

    // ── Access Log ────────────────────────────────────────────────────────────

    #[test]
    fn accesses_for_system_returns_correct_records() {
        let i = strict(1);

        {
            let _w = i.open_window("sys_movement", 1);
            i.request_rng("sys_movement", 1).unwrap();
        }
        {
            let _w = i.open_window("sys_movement", 2);
            i.request_rng("sys_movement", 2).unwrap();
        }

        let records = i.accesses_for_system("sys_movement");
        assert_eq!(records.len(), 2);
        assert!(records.iter().all(|r| r.is_deterministic));
    }

    #[test]
    fn accesses_for_unknown_system_is_empty() {
        let i = strict(1);
        assert!(i.accesses_for_system("sys_ghost").is_empty());
    }

    // ── Reset ─────────────────────────────────────────────────────────────────

    #[test]
    fn reset_clears_all_state() {
        let i = silent(0);
        i.report_illegal_rng("sys_a", 1).ok();
        {
            let _w = i.open_window("sys_b", 2);
            i.request_rng("sys_b", 2).unwrap();
        }
        i.reset();
        assert_eq!(i.violation_count(), 0);
        assert!(!i.has_violations());
        let m = i.metrics();
        assert_eq!(m.legal_access_count, 0);
        assert_eq!(m.illegal_access_count, 0);
        assert_eq!(m.violations_raised, 0);
        assert_eq!(m.windowless_access_count, 0);
        assert!(i.accesses_for_system("sys_a").is_empty());
    }

    // ── World Seed & Metrics Defaults ─────────────────────────────────────────

    #[test]
    fn world_seed_accessor_correct() {
        assert_eq!(strict(123456).world_seed(), 123456);
    }

    #[test]
    fn metrics_all_zero_on_new_interceptor() {
        let m = strict(0).metrics();
        assert_eq!(m.legal_access_count, 0);
        assert_eq!(m.illegal_access_count, 0);
        assert_eq!(m.violations_raised, 0);
        assert_eq!(m.windowless_access_count, 0);
    }
}