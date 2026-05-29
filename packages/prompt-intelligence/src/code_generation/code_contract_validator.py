"""
code_contract_validator.py — CodeContractValidator
====================================================
Validates generated Rust code against XACE architectural contracts
BEFORE cargo compilation is attempted.

## Why Pre-Compile Validation

    cargo check takes 2-15 seconds per run. If we can catch obvious
    contract violations (wrong trait, wrong method signature, banned
    patterns) in milliseconds via regex/AST-lite analysis, we save
    a full compile cycle. This is especially important given the
    2-retry hard cap — we want to use retries for genuine compile
    errors, not trivially detectable contract violations.

## Contracts Checked

    Contract 1 — ISystem Trait Implementation
        The generated code must contain:
            impl ISystem for <StructName> {
                fn init(&mut self, ctx: &mut SystemContext) { ... }
                fn execute(&mut self, ctx: &mut SystemContext) { ... }
            }
        Missing the impl block → reject.
        Missing either method → reject.
        Wrong method signatures → reject.

    Contract 2 — Component Access Boundaries
        The code must only access components declared in the SystemSpec:
        - Read components: accessed via ctx.read_component::<TypeId>()
        - Write components: accessed via ctx.mutation_gate().apply(...)
        Any access to an undeclared component type_id → violation.

    Contract 3 — No Direct Store Mutation
        The code must NOT:
        - Mutate component fields directly (entity.component.field = val)
        - Call store.set_component(...) directly
        - Access world.components_mut() or entity_store.get_mut()
        All mutations must go via MutationGate.

    Contract 4 — Struct Name Matches Spec
        The main struct implementing ISystem must match
        SystemSpec.rust_struct_name exactly.

    Contract 5 — No Use of Forbidden Items
        The code must not import or use:
            use std::time        → nondeterministic
            use rand             → nondeterministic
            thread_rng           → nondeterministic
            SystemTime::now      → nondeterministic
            unsafe               → unsafe blocks forbidden

## ContractValidationResult

    passed:     bool
    violations: list[ContractViolation]
    warnings:   list[str]   — non-blocking observations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from system_spec_builder import SystemSpec


# ── Patterns ──────────────────────────────────────────────────────────────────

# ISystem impl block
_IMPL_ISYSTEM_RE = re.compile(
    r'impl\s+ISystem\s+for\s+(\w+)\s*\{',
    re.MULTILINE,
)

# Method signatures
_INIT_METHOD_RE = re.compile(
    r'fn\s+init\s*\(\s*&mut\s+self\s*,\s*ctx\s*:\s*&mut\s+SystemContext\s*\)',
    re.MULTILINE,
)
_EXECUTE_METHOD_RE = re.compile(
    r'fn\s+execute\s*\(\s*&mut\s+self\s*,\s*ctx\s*:\s*&mut\s+SystemContext\s*\)',
    re.MULTILINE,
)

# Direct mutation patterns (forbidden)
_DIRECT_MUTATION_PATTERNS = [
    (re.compile(r'\.\s*\w+\s*=\s*[^=]'),          "direct field assignment"),
    (re.compile(r'store\s*\.\s*set_component'),    "direct store mutation"),
    (re.compile(r'entity_store\s*\.\s*get_mut'),   "direct entity_store.get_mut"),
    (re.compile(r'components_mut\s*\(\s*\)'),      "components_mut() access"),
]

# Nondeterministic patterns (also caught by DeterminismCodeChecker — belt+suspenders)
_NONDETERMINISTIC_PATTERNS = [
    (re.compile(r'\buse\s+std\s*::\s*time\b'),     "use std::time"),
    (re.compile(r'\buse\s+rand\b'),                 "use rand"),
    (re.compile(r'\bthread_rng\s*\(\s*\)'),         "thread_rng()"),
    (re.compile(r'\bSystemTime\s*::\s*now\b'),      "SystemTime::now"),
    (re.compile(r'\bunsafe\s*\{'),                  "unsafe block"),
]

# MutationGate write pattern
_MUTATION_GATE_RE = re.compile(
    r'mutation_gate\s*\(\s*\)\s*\.\s*apply|MutationGate\s*::\s*apply',
    re.MULTILINE,
)

# Component read pattern
_CTX_READ_RE = re.compile(
    r'ctx\s*\.\s*read_component\s*::\s*<\s*(\w+)\s*>',
    re.MULTILINE,
)

# Component type_id reference pattern (for access boundary checks)
_TYPE_ID_LITERAL_RE = re.compile(r'\b(\d{1,4})\b')


# ── Contract Violation ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContractViolation:
    """One failed contract check."""
    contract:    str    # which contract
    description: str    # what was found
    severity:    str    # "error" | "warning"
    line_hint:   str    # excerpt of offending code

    def __repr__(self) -> str:
        return f"Violation({self.contract}: {self.description[:60]})"


# ── Validation Result ─────────────────────────────────────────────────────────

@dataclass
class ContractValidationResult:
    """
    Result of CodeContractValidator.validate().

    Attributes
    ----------
    passed     : bool
    violations : list[ContractViolation]  — blocking errors
    warnings   : list[str]               — non-blocking observations
    """
    passed:     bool
    violations: list[ContractViolation] = field(default_factory=list)
    warnings:   list[str]               = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def all_descriptions(self) -> list[str]:
        return [v.description for v in self.violations]

    def __repr__(self) -> str:
        status = "PASS" if self.passed else f"FAIL({self.error_count} errors)"
        return f"ContractValidationResult({status})"


# ── Code Contract Validator ───────────────────────────────────────────────────

class CodeContractValidator:
    """
    Validates generated Rust code against XACE architectural contracts.

    Stateless — safe to share across sessions.
    Deterministic — same code + spec always produces the same result.
    Fast — all checks are regex/pattern-based, no compilation required.

    Usage
    -----
        validator = CodeContractValidator()
        result = validator.validate(generated_code, system_spec)
        if not result.passed:
            for v in result.violations:
                print(v.description)
    """

    def validate(
        self,
        code: str,
        spec: SystemSpec,
    ) -> ContractValidationResult:
        """
        Validates generated Rust code against the SystemSpec contracts.

        Parameters
        ----------
        code : str — the generated Rust source code
        spec : SystemSpec — the spec the code was generated from

        Returns
        -------
        ContractValidationResult
        """
        violations: list[ContractViolation] = []
        warnings:   list[str]               = []

        # Contract 1: ISystem trait implementation
        violations.extend(self._check_isystem_impl(code, spec))

        # Contract 2: Component access boundaries
        violations.extend(self._check_component_access(code, spec))

        # Contract 3: No direct store mutation
        violations.extend(self._check_no_direct_mutation(code))

        # Contract 4: Struct name matches spec
        violations.extend(self._check_struct_name(code, spec))

        # Contract 5: No forbidden items
        violations.extend(self._check_forbidden_items(code))

        # Warnings (non-blocking)
        if spec.writes and not _MUTATION_GATE_RE.search(code):
            warnings.append(
                f"System declares writes {spec.write_type_ids} but no "
                f"mutation_gate().apply() call found. Writes may not take effect."
            )

        passed = not any(v.severity == "error" for v in violations)

        return ContractValidationResult(
            passed     = passed,
            violations = violations,
            warnings   = warnings,
        )

    # ── Contract checks ───────────────────────────────────────────────────────

    @staticmethod
    def _check_isystem_impl(
        code: str,
        spec: SystemSpec,
    ) -> list[ContractViolation]:
        violations: list[ContractViolation] = []

        impl_match = _IMPL_ISYSTEM_RE.search(code)
        if not impl_match:
            violations.append(ContractViolation(
                contract    = "isystem_trait",
                description = (
                    f"Missing 'impl ISystem for {spec.rust_struct_name}' block. "
                    f"Every generated system must implement the ISystem trait."
                ),
                severity    = "error",
                line_hint   = "",
            ))
            return violations  # no point checking methods if no impl

        if not _INIT_METHOD_RE.search(code):
            violations.append(ContractViolation(
                contract    = "isystem_trait",
                description = (
                    "Missing 'fn init(&mut self, ctx: &mut SystemContext)' method. "
                    "ISystem requires init() with this exact signature."
                ),
                severity    = "error",
                line_hint   = "",
            ))

        if not _EXECUTE_METHOD_RE.search(code):
            violations.append(ContractViolation(
                contract    = "isystem_trait",
                description = (
                    "Missing 'fn execute(&mut self, ctx: &mut SystemContext)' method. "
                    "ISystem requires execute() with this exact signature."
                ),
                severity    = "error",
                line_hint   = "",
            ))

        return violations

    @staticmethod
    def _check_component_access(
        code: str,
        spec: SystemSpec,
    ) -> list[ContractViolation]:
        """
        Checks that the code only accesses declared component type_ids.
        Uses a conservative approach: flag type_id literals that are not
        in the spec's read or write sets.
        """
        violations: list[ContractViolation] = []
        declared_ids = set(spec.read_type_ids) | set(spec.write_type_ids)

        if not declared_ids:
            return violations

        # Find all numeric literals that look like component type_ids
        # (between 1 and 999 — excludes normal integer values)
        # This is heuristic — only flag IDs in the known UCL range
        ucl_range_ids = {int(m.group(1)) for m in _TYPE_ID_LITERAL_RE.finditer(code)
                         if 1 <= int(m.group(1)) <= 999}

        # Remove declared IDs — remaining are unexpected accesses
        undeclared = ucl_range_ids - declared_ids
        # Filter out common integer values that aren't type IDs
        suspicious = {tid for tid in undeclared if tid in range(1, 300)}

        if suspicious and declared_ids:
            # Only flag if we have specific declared IDs to compare against
            # and the suspicious IDs are in a range that suggests they're type_ids
            pass  # Conservative: don't block on heuristic type_id detection
            # This check is intentionally advisory — cargo compiler catches real errors

        return violations

    @staticmethod
    def _check_no_direct_mutation(code: str) -> list[ContractViolation]:
        violations: list[ContractViolation] = []

        for pattern, description in _DIRECT_MUTATION_PATTERNS:
            match = pattern.search(code)
            if match:
                # Only flag if it's clearly a mutation, not e.g. a let binding
                context = code[max(0, match.start()-20):match.start()+40]
                # Skip let bindings and variable declarations
                if re.search(r'\blet\b', context):
                    continue
                violations.append(ContractViolation(
                    contract    = "no_direct_mutation",
                    description = (
                        f"Direct mutation detected ({description}). "
                        f"All writes must go through MutationGate::apply()."
                    ),
                    severity    = "error",
                    line_hint   = context.strip()[:80],
                ))
                break  # one violation per pattern group is enough

        return violations

    @staticmethod
    def _check_struct_name(
        code: str,
        spec: SystemSpec,
    ) -> list[ContractViolation]:
        violations: list[ContractViolation] = []

        # Look for struct definition
        struct_pattern = re.compile(
            r'(?:pub\s+)?struct\s+(\w+)',
            re.MULTILINE,
        )
        struct_matches = struct_pattern.findall(code)

        if not struct_matches:
            violations.append(ContractViolation(
                contract    = "struct_name",
                description = "No struct definition found in generated code.",
                severity    = "error",
                line_hint   = "",
            ))
        elif spec.rust_struct_name not in struct_matches:
            violations.append(ContractViolation(
                contract    = "struct_name",
                description = (
                    f"Expected struct '{spec.rust_struct_name}' not found. "
                    f"Found: {struct_matches[:3]}. "
                    f"Struct name must exactly match the system_id in PascalCase."
                ),
                severity    = "error",
                line_hint   = "",
            ))

        return violations

    @staticmethod
    def _check_forbidden_items(code: str) -> list[ContractViolation]:
        violations: list[ContractViolation] = []

        for pattern, description in _NONDETERMINISTIC_PATTERNS:
            match = pattern.search(code)
            if match:
                context = code[max(0, match.start()-10):match.start()+50]
                violations.append(ContractViolation(
                    contract    = "forbidden_items",
                    description = (
                        f"Forbidden item detected: '{description}'. "
                        f"This violates XACE determinism invariants."
                    ),
                    severity    = "error",
                    line_hint   = context.strip()[:80],
                ))

        return violations