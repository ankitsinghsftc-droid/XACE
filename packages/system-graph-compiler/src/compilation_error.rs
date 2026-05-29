//! # SGC Compilation Errors
//!
//! All error types produced by the System Graph Compiler pipeline.
//! Each stage produces a specific error variant with full diagnostic payload.
//!
//! ## Error Variants
//! CycleError              — hard dependency cycle detected in system graph
//! PhaseViolation          — system declares invalid phase or cross-phase dependency
//! ConflictError           — unresolvable write-write conflict between systems
//! InvalidSystemDefinition — system definition missing required fields or invalid IDs
//! AmbiguousOrdering       — topological sort cannot determine stable order
//!
//! ## Error Philosophy
//! SGC errors are always fatal — a graph that cannot be compiled cannot be run.
//! Errors carry enough context to identify the exact systems and rules involved.
//! The pipeline reports the FIRST error it encounters. For complete error lists
//! the caller should run in diagnostic mode (future work, Phase 13).

use std::collections::BTreeSet;
use xace_core::runtime::phase_enum::PhaseEnum;

// ── Edge Type ─────────────────────────────────────────────────────────────────

/// The type of a directed edge in the system dependency graph.
///
/// Used by the graph construction layer and reported in cycle diagnostics.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum EdgeType {
    /// Explicitly declared in SystemDefinition.depends_on.
    ExplicitDependency,

    /// System B reads a component that System A writes.
    /// B must run after A to see A's mutations.
    ReadAfterWrite,

    /// Both System A and System B write the same component.
    /// Execution order is determined by lexicographic system_id tie-breaking.
    WriteAfterWrite,

    /// Systems in different phases must respect global phase order.
    /// Initialization → Input → Simulation → PostSimulation → Cleanup
    PhaseOrder,
}

impl EdgeType {
    pub fn as_str(&self) -> &'static str {
        match self {
            EdgeType::ExplicitDependency => "EXPLICIT_DEPENDENCY",
            EdgeType::ReadAfterWrite => "READ_AFTER_WRITE",
            EdgeType::WriteAfterWrite => "WRITE_AFTER_WRITE",
            EdgeType::PhaseOrder => "PHASE_ORDER",
        }
    }
}

impl std::fmt::Display for EdgeType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

// ── Cycle Error ───────────────────────────────────────────────────────────────

/// A hard dependency cycle that prevents compilation.
///
/// A hard cycle means system A depends (directly or transitively) on
/// system B, and system B depends on system A. This is unsolvable without
/// redesigning the system graph.
#[derive(Debug, Clone)]
pub struct CycleError {
    /// The ordered list of system IDs forming the cycle.
    /// Last element has an edge back to first element.
    /// Sorted starting from the lexicographically smallest system_id
    /// for deterministic error messages (D11).
    pub cycle_path: Vec<String>,

    /// The edge types that form the cycle (one per edge in the path).
    pub edge_types: Vec<EdgeType>,

    /// Human-readable explanation of why this cycle cannot be resolved.
    pub description: String,

    /// Suggested resolution strategies.
    pub suggestions: Vec<String>,
}

impl CycleError {
    pub fn new(cycle_path: Vec<String>, edge_types: Vec<EdgeType>) -> Self {
        let desc = format!(
            "Dependency cycle detected: {} → (back to start). \
             This cycle must be broken to compile the system graph.",
            cycle_path.join(" → ")
        );
        let suggestions = vec![
            "Split one of the systems in the cycle into read-only and write-only parts.".into(),
            "Introduce an intermediate component that decouples the cyclic dependency.".into(),
            "Move one system to an earlier phase to break the cross-system dependency.".into(),
        ];
        Self {
            cycle_path,
            edge_types,
            description: desc,
            suggestions,
        }
    }

    pub fn cycle_display(&self) -> String {
        format!("{} → {}", self.cycle_path.join(" → "), self.cycle_path[0])
    }
}

// ── Phase Violation ───────────────────────────────────────────────────────────

/// A system phase declaration error.
#[derive(Debug, Clone)]
pub enum PhaseViolationKind {
    /// System's phase field is None or invalid.
    SystemPhaseUndefined,
    /// System references a phase that doesn't exist in PhaseEnum.
    InvalidSystemPhase { given: String },
    /// System A declares it depends_on System B, but B is in a later phase.
    PhaseDependencyViolation {
        from_phase: PhaseEnum,
        to_phase: PhaseEnum,
    },
}

#[derive(Debug, Clone)]
pub struct PhaseViolation {
    pub system_id: String,
    pub kind: PhaseViolationKind,
    pub description: String,
}

impl PhaseViolation {
    pub fn undefined_phase(system_id: impl Into<String>) -> Self {
        let id = system_id.into();
        Self {
            description: format!(
                "System '{}' has no phase declared. \
                 Every system must be assigned to a phase in its SystemDefinition.",
                id
            ),
            system_id: id,
            kind: PhaseViolationKind::SystemPhaseUndefined,
        }
    }

    pub fn invalid_phase(system_id: impl Into<String>, given: impl Into<String>) -> Self {
        let id = system_id.into();
        let ph = given.into();
        Self {
            description: format!(
                "System '{}' declares phase '{}' which does not exist in PhaseEnum. \
                 Valid phases: Initialization, Input, Simulation, PostSimulation, Cleanup.",
                id, ph
            ),
            kind: PhaseViolationKind::InvalidSystemPhase { given: ph },
            system_id: id,
        }
    }

    pub fn cross_phase_dependency(
        system_id: impl Into<String>,
        from_phase: PhaseEnum,
        to_phase: PhaseEnum,
    ) -> Self {
        let id = system_id.into();
        Self {
            description: format!(
                "System '{}' (phase {:?}) declares depends_on a system in phase {:?}. \
                 Dependencies must point to earlier or same phases only.",
                id, from_phase, to_phase
            ),
            kind: PhaseViolationKind::PhaseDependencyViolation {
                from_phase,
                to_phase,
            },
            system_id: id,
        }
    }
}

// ── Conflict Error ────────────────────────────────────────────────────────────

/// An unresolvable conflict between two systems.
///
/// In practice, all write-write conflicts are resolvable via tie-breaking
/// (lexicographic system_id). This error is reserved for pathological cases
/// where the conflict cannot be automatically resolved.
#[derive(Debug, Clone)]
pub struct ConflictError {
    pub system_a: String,
    pub system_b: String,
    pub conflicting_component_type_ids: BTreeSet<u32>,
    pub description: String,
}

impl ConflictError {
    pub fn write_write(
        system_a: impl Into<String>,
        system_b: impl Into<String>,
        type_ids: BTreeSet<u32>,
    ) -> Self {
        let a = system_a.into();
        let b = system_b.into();
        Self {
            description: format!(
                "Systems '{}' and '{}' both write component type IDs {:?}. \
                 The SGC will serialize them (lexicographic order: '{}' before '{}').",
                a,
                b,
                type_ids,
                // Fixed:
                a.as_str().min(b.as_str()),
                a.as_str().max(b.as_str())
            ),
            system_a: a,
            system_b: b,
            conflicting_component_type_ids: type_ids,
        }
    }
}

// ── Invalid System Definition ─────────────────────────────────────────────────

/// A system definition is missing required fields or contains invalid values.
#[derive(Debug, Clone)]
pub struct InvalidSystemDefinition {
    pub system_id: String,
    pub field: String,
    pub reason: String,
}

impl InvalidSystemDefinition {
    pub fn missing_id() -> Self {
        Self {
            system_id: String::new(),
            field: "system_id".into(),
            reason: "System definition has an empty system_id. \
                        Every system must have a non-empty, unique system_id."
                .into(),
        }
    }

    pub fn unknown_dependency(system_id: impl Into<String>, dep_id: impl Into<String>) -> Self {
        let dep = dep_id.into();
        Self {
            system_id: system_id.into(),
            field: "depends_on".into(),
            reason: format!(
                "System declares depends_on '{}' but no system with that ID \
                 is registered in the schema.",
                dep
            ),
        }
    }
}

// ── Compilation Error ─────────────────────────────────────────────────────────

/// The top-level error type returned by the SGC pipeline.
///
/// All variants carry full diagnostic context. The pipeline halts at the
/// first error — fix it and recompile.
#[derive(Debug, Clone)]
pub enum CompilationError {
    Cycle(CycleError),
    Phase(PhaseViolation),
    Conflict(ConflictError),
    InvalidDefinition(InvalidSystemDefinition),
    /// Internal SGC error — should never happen in production.
    InternalError(String),
}

impl CompilationError {
    pub fn description(&self) -> &str {
        match self {
            CompilationError::Cycle(e) => &e.description,
            CompilationError::Phase(e) => &e.description,
            CompilationError::Conflict(e) => &e.description,
            CompilationError::InvalidDefinition(e) => &e.reason,
            CompilationError::InternalError(s) => s,
        }
    }

    pub fn stage(&self) -> &'static str {
        match self {
            CompilationError::Cycle(_) => "CycleDetection",
            CompilationError::Phase(_) => "PhaseSegmentation",
            CompilationError::Conflict(_) => "ConflictAnalyzer",
            CompilationError::InvalidDefinition(_) => "GraphConstruction",
            CompilationError::InternalError(_) => "Internal",
        }
    }

    pub fn is_cycle(&self) -> bool {
        matches!(self, CompilationError::Cycle(_))
    }
    pub fn is_phase(&self) -> bool {
        matches!(self, CompilationError::Phase(_))
    }
    pub fn is_conflict(&self) -> bool {
        matches!(self, CompilationError::Conflict(_))
    }
}

impl std::fmt::Display for CompilationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "[SGC:{}] {}", self.stage(), self.description())
    }
}

impl std::error::Error for CompilationError {}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cycle_error_display() {
        let e = CycleError::new(
            vec!["sys_a".into(), "sys_b".into(), "sys_c".into()],
            vec![
                EdgeType::ExplicitDependency,
                EdgeType::ReadAfterWrite,
                EdgeType::WriteAfterWrite,
            ],
        );
        assert!(e.cycle_display().contains("sys_a"));
        assert!(e.cycle_display().ends_with("sys_a"));
        assert!(!e.suggestions.is_empty());
    }

    #[test]
    fn phase_violation_undefined() {
        let e = PhaseViolation::undefined_phase("sys_x");
        assert!(e.description.contains("sys_x"));
        assert!(matches!(e.kind, PhaseViolationKind::SystemPhaseUndefined));
    }

    #[test]
    fn phase_violation_cross_phase() {
        let e = PhaseViolation::cross_phase_dependency(
            "sys_late",
            PhaseEnum::Simulation,
            PhaseEnum::PostSimulation,
        );
        assert!(e.description.contains("sys_late"));
        assert!(matches!(
            e.kind,
            PhaseViolationKind::PhaseDependencyViolation { .. }
        ));
    }

    #[test]
    fn conflict_error_write_write() {
        let type_ids: BTreeSet<u32> = [1, 5].into();
        let e = ConflictError::write_write("sys_b", "sys_a", type_ids);
        // Lexicographic: sys_a before sys_b
        assert!(e.description.contains("sys_a"));
        assert!(e.description.contains("sys_b"));
    }

    #[test]
    fn compilation_error_stages() {
        let cycle = CompilationError::Cycle(CycleError::new(vec!["x".into()], vec![]));
        assert_eq!(cycle.stage(), "CycleDetection");
        assert!(cycle.is_cycle());

        let phase = CompilationError::Phase(PhaseViolation::undefined_phase("s"));
        assert_eq!(phase.stage(), "PhaseSegmentation");
        assert!(phase.is_phase());
    }

    #[test]
    fn edge_type_display() {
        assert_eq!(EdgeType::ReadAfterWrite.to_string(), "READ_AFTER_WRITE");
        assert_eq!(EdgeType::WriteAfterWrite.to_string(), "WRITE_AFTER_WRITE");
        assert_eq!(
            EdgeType::ExplicitDependency.to_string(),
            "EXPLICIT_DEPENDENCY"
        );
        assert_eq!(EdgeType::PhaseOrder.to_string(), "PHASE_ORDER");
    }

    #[test]
    fn invalid_definition_unknown_dep() {
        let e = InvalidSystemDefinition::unknown_dependency("sys_a", "sys_ghost");
        assert!(e.reason.contains("sys_ghost"));
        assert_eq!(e.field, "depends_on");
    }
}
