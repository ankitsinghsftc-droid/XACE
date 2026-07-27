"""
code_generation_engine.py — CodeGenerationEngine
==================================================
Orchestrates the full code generation pipeline for one XACE system.

## Pipeline Order

    1. SystemSpecBuilder.build()         → SystemSpec (validate first)
    2. RustCodeGenerator.generate()      → GeneratedCode (TIER_XL, attempt 1)
    3. CodeContractValidator.validate()  → ContractValidationResult
    4. DeterminismCodeChecker.check()    → DeterminismReport
    5. CargoCompiler.compile()           → CompileResult

    If steps 3, 4, or 5 fail:
        → Build correction context from all failure messages
        → RustCodeGenerator.generate() attempt 2 (correction injected)
        → Repeat steps 3-5 on attempt 2

    If attempt 2 also fails:
        → Raise CodeGenerationError (escalated to ClarificationEngine)

## Retry Logic

    HARD CAP: MAX_ATTEMPTS = 2 (Audit 8).

    The correction context injected into attempt 2 includes:
        - Contract violations from CodeContractValidator
        - Determinism violations from DeterminismCodeChecker
        - Compiler errors from CargoCompiler (structured, not raw output)

    This gives the model maximum signal in one correction attempt.

## CodeGenerationResult

    On success:
        succeeded        : True
        final_code       : GeneratedCode
        compile_result   : CompileResult
        contract_result  : ContractValidationResult
        determinism_report: DeterminismReport
        attempts_used    : int (1 or 2)

    On failure:
        succeeded        : False
        error            : str
        needs_clarification : True
        (all result fields None)

## Diff for Designer Review

    Before the code is committed to the file system, the engine
    produces a diff between the old implementation (if any) and the
    new implementation via unified_diff(). This is shown to the
    designer in COLLABORATIVE/FULLY_ASSISTED mode so they can see
    exactly what changed.

    In ADVANCED/ARCHITECT_MODE the diff is available on request.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from typing import Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from system_spec_builder import SystemSpecBuilder, SystemSpec
from rust_code_generator import (
    RustCodeGenerator, GeneratedCode, CodeGenerationError, MAX_ATTEMPTS
)
from code_contract_validator import CodeContractValidator, ContractValidationResult
from determinism_code_checker import DeterminismCodeChecker, DeterminismReport
from cargo_compiler import CargoCompiler, CompileResult
from generated_system_safe_compiler import (
    GeneratedSystemSafeCompiler,
    SafeGeneratedSystemCompileResult,
)


# ── Code Generation Result ────────────────────────────────────────────────────

@dataclass
class CodeGenerationResult:
    """
    Full result of CodeGenerationEngine.generate_system().

    Attributes
    ----------
    succeeded             : bool
    system_id             : str
    final_code            : GeneratedCode | None
    compile_result        : CompileResult | None
    contract_result       : ContractValidationResult | None
    determinism_report    : DeterminismReport | None
    attempts_used         : int
    needs_clarification   : bool   — True when both attempts failed
    error                 : str    — human-readable failure reason
    diff_text             : str    — unified diff vs old implementation
    spec                  : SystemSpec | None
    """
    succeeded:           bool
    system_id:           str
    final_code:          GeneratedCode | None              = None
    compile_result:      CompileResult | None              = None
    contract_result:     ContractValidationResult | None   = None
    determinism_report:  DeterminismReport | None          = None
    safe_compile_result: SafeGeneratedSystemCompileResult | None = None
    signed_runtime_executor: dict[str, Any]                = field(default_factory=dict)
    attempts_used:       int                               = 0
    needs_clarification: bool                              = False
    error:               str                               = ""
    diff_text:           str                               = ""
    spec:                SystemSpec | None                 = None

    @property
    def rust_source(self) -> str:
        """Shortcut to the generated Rust source."""
        return self.final_code.rust_source if self.final_code else ""

    def all_warnings(self) -> list[str]:
        """Aggregates warnings from all validation stages."""
        warnings: list[str] = []
        if self.contract_result:
            warnings.extend(self.contract_result.warnings)
        if self.determinism_report:
            warnings.extend(self.determinism_report.warnings)
        if self.compile_result and self.compile_result.warnings_count > 0:
            warnings.append(
                f"{self.compile_result.warnings_count} compiler warning(s) — "
                f"check generated code."
            )
        return warnings

    def __repr__(self) -> str:
        status = "SUCCESS" if self.succeeded else "FAILED"
        return (
            f"CodeGenerationResult({status}, "
            f"system={self.system_id!r}, "
            f"attempts={self.attempts_used})"
        )


# ── Code Generation Engine ────────────────────────────────────────────────────

class CodeGenerationEngine:
    """
    Orchestrates the full code generation pipeline.

    One instance per PIL session. Stateless between calls.

    Usage
    -----
        engine = CodeGenerationEngine(inference_adapter)
        result = engine.generate_system(
            system_id   = "MovementSystem",
            cgs         = current_cgs,
            mode_id     = "mode_default",
            description = "Applies velocity to transform each tick.",
            session_id  = "s1",
            old_code    = existing_implementation or "",
        )
        if result.needs_clarification:
            return clarification_engine.create_session(...)
        if result.succeeded:
            show_diff_to_designer(result.diff_text)
            commit_to_filesystem(result.rust_source, system_id)
    """

    def __init__(
        self,
        adapter: Any,
        sgc_bin: str | os.PathLike[str] | None = None,
        safe_compiler: GeneratedSystemSafeCompiler | None = None,
    ) -> None:
        """
        Parameters
        ----------
        adapter : InferenceAdapter
            The shared InferenceAdapter (II1 — all LLM calls go through here).
        """
        self._adapter   = adapter
        self._spec_builder  = SystemSpecBuilder()
        self._generator     = RustCodeGenerator(adapter)
        self._contract_validator = CodeContractValidator()
        self._det_checker   = DeterminismCodeChecker()
        self._compiler      = CargoCompiler()
        self._safe_compiler = safe_compiler or GeneratedSystemSafeCompiler(sgc_bin=sgc_bin)

    def generate_system(
        self,
        system_id:    str,
        cgs:          dict[str, Any],
        mode_id:      str = "",
        description:  str = "",
        session_id:   str = "",
        old_code:     str = "",
        max_entities: int = 1000,
        tick_budget_us: int = 100,
    ) -> CodeGenerationResult:
        """
        Generates a Rust ISystem implementation for the named system.

        Parameters
        ----------
        system_id     : str   — e.g. "MovementSystem"
        cgs           : dict  — current CGS
        mode_id       : str   — which mode to search (empty = all)
        description   : str   — human-readable system purpose for prompt
        session_id    : str   — for telemetry
        old_code      : str   — existing implementation for diff (empty if new)
        max_entities  : int   — performance hint
        tick_budget_us: int   — microsecond budget hint

        Returns
        -------
        CodeGenerationResult
        """

        # ── Step 1: Build SystemSpec ──────────────────────────────────────────
        spec = self._spec_builder.build(
            system_id      = system_id,
            cgs            = cgs,
            mode_id        = mode_id,
            description    = description,
            max_entities   = max_entities,
            tick_budget_us = tick_budget_us,
        )

        if not spec.is_valid:
            return CodeGenerationResult(
                succeeded           = False,
                system_id           = system_id,
                needs_clarification = True,
                error               = (
                    f"SystemSpec validation failed: "
                    f"{'; '.join(spec.validation_errors)}"
                ),
                spec = spec,
            )

        # ── Attempt loop (hard cap MAX_ATTEMPTS=2) ────────────────────────────
        system_definition = self._find_system_definition(cgs, system_id, mode_id)
        runtime_executor: dict[str, Any] = {}
        if isinstance(system_definition, dict):
            raw_runtime_executor = system_definition.get("runtime_executor")
            if isinstance(raw_runtime_executor, dict):
                runtime_executor = raw_runtime_executor

        correction    = ""
        last_error    = ""
        code          = None
        contract_result:    ContractValidationResult | None = None
        det_report:         DeterminismReport | None        = None
        compile_result:     CompileResult | None            = None

        for attempt in range(1, MAX_ATTEMPTS + 1):

            # ── Step 2: Generate Rust code ────────────────────────────────────
            try:
                code = self._generator.generate(
                    spec       = spec,
                    session_id = session_id,
                    correction = correction,
                    attempt    = attempt,
                )
            except CodeGenerationError as exc:
                return CodeGenerationResult(
                    succeeded           = False,
                    system_id           = system_id,
                    needs_clarification = True,
                    error               = str(exc),
                    attempts_used       = attempt - 1,
                    spec                = spec,
                )

            # ── Step 3: Contract validation ───────────────────────────────────
            contract_result = self._contract_validator.validate(code.rust_source, spec)

            # ── Step 4: Determinism check ─────────────────────────────────────
            det_report = self._det_checker.check(code.rust_source)

            # ── Step 5: Cargo compile ─────────────────────────────────────────
            compile_result = self._compiler.compile(code.rust_source, spec)

            # ── Evaluate: did everything pass? ────────────────────────────────
            all_passed = (
                contract_result.passed
                and det_report.passed
                and (compile_result.passed or not compile_result.cargo_available)
            )

            if all_passed:
                safe_compile_result: SafeGeneratedSystemCompileResult | None = None
                signed_runtime_executor: dict[str, Any] = {}
                if runtime_executor:
                    safe_compile_result = self._safe_compiler.compile(
                        system_id=system_id,
                        cgs=cgs,
                        rust_source=code.rust_source,
                        mode_id=mode_id,
                        description=description,
                        max_entities=max_entities,
                        tick_budget_us=tick_budget_us,
                    )
                    if not safe_compile_result.succeeded:
                        return CodeGenerationResult(
                            succeeded           = False,
                            system_id           = system_id,
                            final_code          = code,
                            compile_result      = safe_compile_result.compile_result or compile_result,
                            contract_result     = safe_compile_result.contract_result or contract_result,
                            determinism_report  = safe_compile_result.determinism_report or det_report,
                            safe_compile_result = safe_compile_result,
                            attempts_used       = attempt,
                            needs_clarification = True,
                            error               = (
                                "Safe generated-system compile failed at "
                                f"{safe_compile_result.stage}: {safe_compile_result.error}"
                            ),
                            spec                = spec,
                        )
                    signed_runtime_executor = safe_compile_result.signed_runtime_executor

                diff_text = _compute_diff(
                    old_code          = old_code,
                    new_code          = code.rust_source,
                    system_id         = system_id,
                )
                return CodeGenerationResult(
                    succeeded          = True,
                    system_id          = system_id,
                    final_code         = code,
                    compile_result     = compile_result,
                    contract_result    = contract_result,
                    determinism_report = det_report,
                    safe_compile_result = safe_compile_result,
                    signed_runtime_executor = signed_runtime_executor,
                    attempts_used      = attempt,
                    diff_text          = diff_text,
                    spec               = spec,
                )

            # ── Build correction context for next attempt ─────────────────────
            if attempt < MAX_ATTEMPTS:
                correction, last_error = self._build_correction(
                    contract_result, det_report, compile_result
                )

        # ── Both attempts failed ──────────────────────────────────────────────
        last_error = last_error or self._build_correction(
            contract_result, det_report, compile_result
        )[1]

        return CodeGenerationResult(
            succeeded           = False,
            system_id           = system_id,
            final_code          = code,   # keep last attempt for inspection
            compile_result      = compile_result,
            contract_result     = contract_result,
            determinism_report  = det_report,
            attempts_used       = MAX_ATTEMPTS,
            needs_clarification = True,
            error               = (
                f"Code generation failed after {MAX_ATTEMPTS} attempt(s). "
                f"Last errors: {last_error[:200]}"
            ),
            spec = spec,
        )

    # ── Correction context builder ────────────────────────────────────────────

    @staticmethod
    def _build_correction(
        contract_result: ContractValidationResult | None,
        det_report:      DeterminismReport | None,
        compile_result:  CompileResult | None,
    ) -> tuple[str, str]:
        """
        Builds the correction prompt and a brief last_error string.
        Returns (correction_prompt, last_error_brief).
        """
        parts: list[str] = []

        if contract_result and not contract_result.passed:
            parts.append("CONTRACT VIOLATIONS:")
            for v in contract_result.violations[:5]:
                parts.append(f"  - [{v.contract}] {v.description}")

        if det_report and not det_report.passed:
            parts.append("DETERMINISM VIOLATIONS:")
            for v in det_report.violations[:5]:
                parts.append(f"  - [{v.category}] {v.description}")

        if compile_result and not compile_result.passed and compile_result.cargo_available:
            parts.append(compile_result.formatted_errors())

        correction  = "\n".join(parts)
        last_error  = "; ".join(
            p[:80] for p in parts[:3]
        )
        return correction, last_error

    def generate_for_all_systems(
        self,
        cgs:       dict[str, Any],
        mode_id:   str = "",
        session_id: str = "",
    ) -> dict[str, CodeGenerationResult]:
        """
        Generates code for every system in the specified mode (or all modes).

        Returns a dict of system_id → CodeGenerationResult.
        Systems are processed in depends_on order (topological sort).
        """
        # Collect all system IDs in topological order
        ordered_ids = self._topological_order(cgs, mode_id)

        results: dict[str, CodeGenerationResult] = {}
        for sid in ordered_ids:
            results[sid] = self.generate_system(
                system_id  = sid,
                cgs        = cgs,
                mode_id    = mode_id,
                session_id = session_id,
            )
        return results

    @staticmethod
    def _topological_order(
        cgs:     dict[str, Any],
        mode_id: str,
    ) -> list[str]:
        """
        Returns system IDs in topological order (dependencies first).
        Uses Kahn's algorithm on the depends_on graph.
        """
        all_systems: list[dict] = list(cgs.get("global_systems", []))
        for mode in cgs.get("modes", []):
            if mode_id and mode.get("id") != mode_id:
                continue
            all_systems.extend(mode.get("systems", []))

        # Build adjacency: id → [dependents]
        deps:   dict[str, list[str]] = {s["id"]: s.get("depends_on", [])
                                         for s in all_systems}
        in_deg: dict[str, int]       = {sid: 0 for sid in deps}
        for sid, d_list in deps.items():
            for dep in d_list:
                if dep in in_deg:
                    in_deg[sid] = in_deg.get(sid, 0) + 1

        # Kahn's algorithm
        queue  = sorted(sid for sid, deg in in_deg.items() if deg == 0)
        result: list[str] = []
        while queue:
            sid = queue.pop(0)
            result.append(sid)
            for other, d_list in deps.items():
                if sid in d_list:
                    in_deg[other] -= 1
                    if in_deg[other] == 0:
                        queue.append(other)
                        queue.sort()

        # Add any remaining (cycle detection fallback)
        for sid in sorted(deps.keys()):
            if sid not in result:
                result.append(sid)

        return result

    @staticmethod
    def _find_system_definition(
        cgs: dict[str, Any],
        system_id: str,
        mode_id: str,
    ) -> dict[str, Any] | None:
        """Finds the CGS system definition used by safe generated-code routing."""
        for system in cgs.get("global_systems", []):
            if isinstance(system, dict) and system.get("id") == system_id:
                return system

        for mode in cgs.get("modes", []):
            if not isinstance(mode, dict):
                continue
            if mode_id and mode.get("id") != mode_id:
                continue
            for system in mode.get("systems", []):
                if isinstance(system, dict) and system.get("id") == system_id:
                    return system

        return None


# ── Diff computation ──────────────────────────────────────────────────────────

def _compute_diff(
    old_code:  str,
    new_code:  str,
    system_id: str,
) -> str:
    """
    Produces a unified diff between old and new implementations.
    Returns empty string if old_code is empty (new system).
    """
    if not old_code.strip():
        lines = new_code.splitlines()
        return (
            f"=== NEW SYSTEM: {system_id} ===\n"
            f"{len(lines)} lines generated.\n"
            f"(No previous implementation to diff against.)"
        )

    diff_lines = list(difflib.unified_diff(
        old_code.splitlines(keepends=True),
        new_code.splitlines(keepends=True),
        fromfile = f"{system_id}_old.rs",
        tofile   = f"{system_id}_new.rs",
        n        = 3,   # 3 lines of context
    ))

    if not diff_lines:
        return f"=== {system_id}: No changes. ==="

    diff_str = "".join(diff_lines)
    # Cap diff output for UI display
    if len(diff_str) > 4000:
        diff_str = diff_str[:3900] + "\n... (diff truncated)"

    return diff_str
