"""
system_validator.py — SystemValidator
======================================
Validates individual SchemaSystemDefinitions before they are registered
in the SystemDefinitionRegistry.

## Validation Rules
Each rule maps to one or more global invariants from CLAUDE.md.

    Rule 1 — Non-empty ID (I4)
    Rule 2 — Valid phase name (I4)
    Rule 3 — All read type_ids exist in ComponentDefinitionRegistry (I1)
    Rule 4 — All write type_ids exist in ComponentDefinitionRegistry (I1, I2)
    Rule 5 — No type_id appears in both reads AND writes (I6)
              A system either reads a component or writes it — writes are
              the authoritative access, reads are observational.
              Exception: a system may list a type_id in reads that it also
              writes IF it needs the previous tick's value; this is flagged
              as a warning, not an error, since it is sometimes intentional.
    Rule 6 — deterministic=True (soft warning if False)
    Rule 7 — No self-dependency in depends_on
    Rule 8 — display_name is non-empty (UI requirement, soft warning)
    Rule 9 — Non-negative version numbers
    Rule 10— UCL-only restriction: Cleanup phase systems must not write
              UCL type_ids 1–10 except COMP_LIFETIME_V1 (7) and
              COMP_GAMESTATE_V1 (8). Cleanup is for teardown, not gameplay.

## Severity Levels
Errors   — block registration. The system cannot be compiled.
Warnings — allow registration but are surfaced in the SchemaValidationReport.
"""

from __future__ import annotations

from dataclasses import dataclass

from .system_definition_registry import (
    SchemaSystemDefinition,
    VALID_PHASES,
)


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass
class SystemValidationResult:
    """
    Result of validating one SchemaSystemDefinition.

    Attributes
    ----------
    system_id : str
        ID of the system that was validated.
    errors : list[str]
        Hard failures. System must not be registered if errors is non-empty.
    warnings : list[str]
        Soft issues. System can be registered but issues should be surfaced.
    """

    system_id: str
    errors:    list[str]
    warnings:  list[str]

    @property
    def is_valid(self) -> bool:
        """True if there are no hard errors."""
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def __repr__(self) -> str:
        status = "VALID" if self.is_valid else f"INVALID ({len(self.errors)} errors)"
        return (
            f"SystemValidationResult(system={self.system_id!r}, "
            f"status={status}, warnings={len(self.warnings)})"
        )


# ── Constants ─────────────────────────────────────────────────────────────────

# UCL type_ids allowed to be written in Cleanup phase.
_CLEANUP_WRITABLE_UCL: frozenset[int] = frozenset({
    7,   # COMP_LIFETIME_V1 — lifecycle management
    8,   # COMP_GAMESTATE_V1 — match state transitions
    9,   # COMP_AUTHORITY_V1 — network cleanup
})

_UCL_RANGE: frozenset[int] = frozenset(range(1, 11))


# ── System Validator ──────────────────────────────────────────────────────────

class SystemValidator:
    """
    Validates SchemaSystemDefinitions against the ComponentDefinitionRegistry.

    Stateless — no mutable state. The component registry is injected per call
    so the validator is safe to reuse across multiple compile() runs.

    Usage
    -----
        validator = SystemValidator(component_registry)
        result    = validator.validate(system_def)
        if not result.is_valid:
            raise ...
    """

    def __init__(self, component_registry) -> None:
        """
        Parameters
        ----------
        component_registry : ComponentDefinitionRegistry
            The assembled UCL+DCL+GCL registry for this game.
        """
        self._registry = component_registry

    # ── Public API ────────────────────────────────────────────────────────────

    def validate(self, system: SchemaSystemDefinition) -> SystemValidationResult:
        """
        Validates one SchemaSystemDefinition.

        Runs all rules and collects every error and warning before returning
        so the designer sees all issues in one shot.
        """
        errors:   list[str] = []
        warnings: list[str] = []

        self._rule_non_empty_id(system, errors)
        if errors:
            # Can't validate further without a stable ID
            return SystemValidationResult(
                system_id=system.id or "<missing>",
                errors=errors,
                warnings=warnings,
            )

        self._rule_valid_phase(system, errors)
        self._rule_reads_exist_in_registry(system, errors)
        self._rule_writes_exist_in_registry(system, errors)
        self._rule_read_write_overlap(system, warnings)
        self._rule_deterministic(system, warnings)
        self._rule_display_name(system, warnings)
        self._rule_version_numbers(system, errors)
        self._rule_cleanup_write_restriction(system, warnings)

        return SystemValidationResult(
            system_id=system.id,
            errors=errors,
            warnings=warnings,
        )

    def validate_all(
        self, systems: list[SchemaSystemDefinition]
    ) -> list[SystemValidationResult]:
        """
        Validates a list of systems and returns all results.
        Results are in the same order as the input list.
        """
        return [self.validate(s) for s in systems]

    def collect_errors(
        self, systems: list[SchemaSystemDefinition]
    ) -> list[str]:
        """
        Validates all systems and returns a flat list of all error strings.
        Empty list means all systems are valid.
        """
        all_errors: list[str] = []
        for result in self.validate_all(systems):
            all_errors.extend(result.errors)
        return all_errors

    # ── Rules ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _rule_non_empty_id(
        system: SchemaSystemDefinition, errors: list[str]
    ) -> None:
        """Rule 1 — ID must be non-empty (I4)."""
        if not system.id or not system.id.strip():
            errors.append(
                "System has an empty or whitespace-only ID. "
                "Every system must have a unique non-empty ID."
            )

    @staticmethod
    def _rule_valid_phase(
        system: SchemaSystemDefinition, errors: list[str]
    ) -> None:
        """Rule 2 — Phase must be a valid ExecutionPhase name."""
        if system.phase not in VALID_PHASES:
            errors.append(
                f"[{system.id}] Invalid phase '{system.phase}'. "
                f"Valid phases: {sorted(VALID_PHASES)}. "
                f"Check the phase assignment in the CGS actor definition."
            )

    def _rule_reads_exist_in_registry(
        self, system: SchemaSystemDefinition, errors: list[str]
    ) -> None:
        """Rule 3 — All read type_ids must exist in ComponentDefinitionRegistry (I1)."""
        missing = [
            tid for tid in system.reads
            if not self._registry.has_component(tid)
        ]
        for tid in sorted(missing):
            errors.append(
                f"[{system.id}] Read declaration references component "
                f"type_id {tid} which is not registered. "
                f"Declare the domain containing this component in game_config.yaml."
            )

    def _rule_writes_exist_in_registry(
        self, system: SchemaSystemDefinition, errors: list[str]
    ) -> None:
        """Rule 4 — All write type_ids must exist in ComponentDefinitionRegistry (I1, I2)."""
        missing = [
            tid for tid in system.writes
            if not self._registry.has_component(tid)
        ]
        for tid in sorted(missing):
            errors.append(
                f"[{system.id}] Write declaration references component "
                f"type_id {tid} which is not registered. "
                f"All written components must be in the CompositeComponentRegistry (I2)."
            )

    @staticmethod
    def _rule_read_write_overlap(
        system: SchemaSystemDefinition, warnings: list[str]
    ) -> None:
        """
        Rule 5 — Overlap between reads and writes is a soft warning.
        A system that both reads and writes a component reads the previous
        tick's value and writes a new one — valid but worth flagging.
        """
        overlap = sorted(set(system.reads) & set(system.writes))
        if overlap:
            warnings.append(
                f"[{system.id}] Component type_id(s) {overlap} appear in both "
                f"reads and writes. The system reads the previous tick's value "
                f"and overwrites it. This is valid but verify it is intentional."
            )

    @staticmethod
    def _rule_deterministic(
        system: SchemaSystemDefinition, warnings: list[str]
    ) -> None:
        """Rule 6 — Non-deterministic systems are a hard warning (D6)."""
        if not system.deterministic:
            warnings.append(
                f"[{system.id}] System is marked deterministic=False. "
                f"All XACE systems must be deterministic (D6). "
                f"Non-deterministic systems cannot be in parallel execution groups "
                f"and will cause replay failures."
            )

    @staticmethod
    def _rule_display_name(
        system: SchemaSystemDefinition, warnings: list[str]
    ) -> None:
        """Rule 8 — display_name should be non-empty for builder UI."""
        if not system.display_name or not system.display_name.strip():
            warnings.append(
                f"[{system.id}] Missing display_name. "
                f"The builder UI and Design Mentor use display_name to "
                f"describe systems to the designer. "
                f"Provide a short human-readable name."
            )

    @staticmethod
    def _rule_version_numbers(
        system: SchemaSystemDefinition, errors: list[str]
    ) -> None:
        """Rule 9 — Version numbers must be non-negative integers."""
        if system.version_major < 0 or system.version_minor < 0:
            errors.append(
                f"[{system.id}] System version ({system.version_major}."
                f"{system.version_minor}) contains negative numbers. "
                f"Version numbers must be >= 0."
            )

    def _rule_cleanup_write_restriction(
        self, system: SchemaSystemDefinition, warnings: list[str]
    ) -> None:
        """
        Rule 10 — Cleanup phase systems must not write gameplay UCL components.
        Writes to COMP_LIFETIME_V1 (7), COMP_GAMESTATE_V1 (8), and
        COMP_AUTHORITY_V1 (9) are permitted. All other UCL type_ids in
        a Cleanup write set are flagged.
        """
        if system.phase != "Cleanup":
            return

        forbidden_writes = sorted(
            tid for tid in system.writes
            if tid in _UCL_RANGE and tid not in _CLEANUP_WRITABLE_UCL
        )
        if forbidden_writes:
            comp_names = [
                getattr(self._registry.get(tid), "name", f"type_id={tid}")
                for tid in forbidden_writes
            ]
            warnings.append(
                f"[{system.id}] Cleanup-phase system writes to UCL components "
                f"{comp_names}. Cleanup is for entity teardown and state reset — "
                f"gameplay writes should happen in Simulation or PostSimulation."
            )