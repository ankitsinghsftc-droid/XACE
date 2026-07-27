"""
determinism_code_checker.py — DeterminismCodeChecker
======================================================
Deep static analysis of generated Rust code for nondeterminism.

This is a SECOND line of defence after CodeContractValidator.
While CodeContractValidator checks architectural contracts (trait
implementation, access boundaries), DeterminismCodeChecker performs
deeper semantic analysis specifically targeting determinism violations.

## Why Two Checkers?

    CodeContractValidator catches structural problems.
    DeterminismCodeChecker catches subtle nondeterminism that compiles
    cleanly but produces different results across replays:

    - HashMap/HashSet iteration: different order on each run in Rust
      (hash-randomised by default since Rust 1.36)
    - Floating-point non-associativity: parallel fold with different
      ordering → different sums
    - Thread-local state: any use of thread_local! or lazy_static!
    - Clock reads: Instant::now(), SystemTime::now()
    - OS randomness: getrandom::getrandom(), rand::random()
    - Atomic non-determinism: Ordering::Relaxed reads in execute()
    - Unordered entity iteration: any .iter() on HashMap<EntityId, _>
      without explicit sort

## Checks Performed

    Check 1 — Random Sources
        Detects: rand::random, thread_rng, OsRng, getrandom,
                 rand_chacha without seed, StdRng::from_entropy

    Check 2 — Unordered Iteration
        Detects: HashMap::iter(), HashSet::iter() without .collect
        then sort, or BTreeMap alternative.
        BTreeMap, BTreeSet, and Vec (which is always ordered) are ALLOWED.

    Check 3 — Time Sources
        Detects: Instant::now(), SystemTime::now(), Duration::from_secs
        when used to seed or generate values (not just timing benchmarks).

    Check 4 — Thread-Local / Static Mutation
        Detects: thread_local!, static mut, lazy_static!,
                 once_cell::sync::OnceCell writes

    Check 5 — Relaxed Atomics in execute()
        Detects: Ordering::Relaxed or fetch_add/fetch_sub inside
                 fn execute() — these can produce different values
                 on different runs depending on thread scheduling.

    Check 6 — Direct MutationGate Bypass
        Detects: Accessing component fields via raw pointer or transmute,
                 bypassing the MutationGate contract.

    Check 7 — Non-Deterministic Sort
        Detects: sort() without sort_by_key() or sort_by() with a
                 stable comparator — unstable sort on equal elements
                 can differ between runs.

## DeterminismReport

    passed:        bool
    violations:    list[DeterminismViolation]
    warnings:      list[str]
    analysis_notes: list[str]   — informational, not violations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Violation categories ──────────────────────────────────────────────────────

class ViolationCategory:
    RANDOM_SOURCE      = "random_source"
    UNORDERED_ITER     = "unordered_iteration"
    TIME_SOURCE        = "time_source"
    FLOAT_EDGE_CASE    = "float_edge_case"
    NONDETERMINISTIC_SERIALIZATION = "nondeterministic_serialization"
    THREAD_LOCAL       = "thread_local_state"
    RELAXED_ATOMIC     = "relaxed_atomic"
    MUTATION_BYPASS    = "mutation_bypass"
    UNSTABLE_SORT      = "unstable_sort"


# ── Patterns ──────────────────────────────────────────────────────────────────

# Random sources
_RANDOM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\brand\s*::\s*random\b'),           "rand::random()"),
    (re.compile(r'\bthread_rng\s*\(\s*\)'),           "thread_rng()"),
    (re.compile(r'\bOsRng\b'),                        "OsRng"),
    (re.compile(r'\bgetrandom\s*::\s*getrandom\b'),   "getrandom::getrandom"),
    (re.compile(r'\bStdRng\s*::\s*from_entropy\b'),   "StdRng::from_entropy"),
    (re.compile(r'\bSmallRng\s*::\s*from_entropy\b'), "SmallRng::from_entropy"),
    (re.compile(r'\bRng\s*::\s*gen\b'),               "Rng::gen"),
    (re.compile(r'\bRng\s*::\s*gen_range\b'),         "Rng::gen_range"),
]

# Unordered iteration — HashMap/HashSet without explicit sort
_UNORDERED_ITER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'use\s+std\s*::\s*collections\s*::\s*\{[^}]*\bHashMap\b'),
     "HashMap import - generated systems must use BTreeMap for deterministic order."),
    (re.compile(r'use\s+std\s*::\s*collections\s*::\s*\{[^}]*\bHashSet\b'),
     "HashSet import - generated systems must use BTreeSet for deterministic order."),
    (re.compile(r'use\s+std\s*::\s*collections\s*::\s*HashMap\b'),
     "HashMap import - generated systems must use BTreeMap for deterministic order."),
    (re.compile(r'use\s+std\s*::\s*collections\s*::\s*HashSet\b'),
     "HashSet import - generated systems must use BTreeSet for deterministic order."),
    (re.compile(r'HashMap\s*::\s*new\s*\(\s*\)'),
     "HashMap::new() — iteration order is non-deterministic. Use BTreeMap."),
    (re.compile(r'HashSet\s*::\s*new\s*\(\s*\)'),
     "HashSet::new() — iteration order is non-deterministic. Use BTreeSet."),
    (re.compile(r'\bHashMap\s*<'),
     "HashMap<...> field — iteration order is non-deterministic. Use BTreeMap."),
    (re.compile(r'\bHashSet\s*<'),
     "HashSet<...> field — iteration order is non-deterministic. Use BTreeSet."),
    (re.compile(r'FxHashMap|AHashMap|DashMap'),
     "Hash-randomised map detected — non-deterministic iteration. Use BTreeMap."),
]

# Time sources
_TIME_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bInstant\s*::\s*now\b'),           "Instant::now()"),
    (re.compile(r'\bSystemTime\s*::\s*now\b'),         "SystemTime::now()"),
    (re.compile(r'\bDuration\s*::\s*from_secs\b'),     "Duration::from_secs"),
]

_FLOAT_EDGE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bf(?:32|64)\s*::\s*NAN\b|\bNaN\b'),
     "NaN literal/constant in generated system - NaN comparisons and serialization are not deterministic contracts."),
    (re.compile(r'\bf(?:32|64)\s*::\s*(?:INFINITY|NEG_INFINITY)\b'),
     "Infinity literal/constant in generated system - clamp to finite gameplay ranges before codegen."),
    (re.compile(r'\bpartial_cmp\s*\([^)]*\)\s*\.\s*unwrap\s*\('),
     "partial_cmp(...).unwrap() on floats can panic or diverge on NaN - use finite validated values."),
]

# Direct serialization in generated systems can hide unordered maps, debug
# formatting, or platform-shaped output. Runtime-owned canonical serializers
# and SHA-256 world hashing are the authoritative replay path.
_NONDETERMINISTIC_SERIALIZATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bserde_json\s*::\s*to_string(?:_pretty)?\b'),
     "serde_json::to_string() in generated system - use XACE canonical serialization outside system code."),
    (re.compile(r'\bserde_json\s*::\s*to_vec(?:_pretty)?\b'),
     "serde_json::to_vec() in generated system - use XACE canonical serialization outside system code."),
    (re.compile(r'\bserde_json\s*::\s*to_value\b'),
     "serde_json::to_value() in generated system - serialization order may be non-authoritative."),
    (re.compile(r'\bserde_json\s*::\s*json\s*!'),
     "serde_json::json! in generated system - construct typed component updates instead."),
    (re.compile(r'format!\s*\(\s*r?#?"\s*\{\s*:\s*\?\s*\}'),
     "Debug formatting serialization detected - Debug output is not a replay contract."),
    (re.compile(r'\bDefaultHasher\b|\bSipHasher\b|\bRandomState\b'),
     "Non-canonical hash/serialization helper detected - use XACE SHA-256 world hashing only."),
]

# Thread-local / static mutation
_THREAD_LOCAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bthread_local\s*!\s*\{'),           "thread_local! macro"),
    (re.compile(r'\bstatic\s+mut\b'),                  "static mut"),
    (re.compile(r'\blazy_static\s*!\s*\{'),            "lazy_static! macro"),
    (re.compile(r'\bOnceCell\s*::\s*new\b'),           "OnceCell::new"),
]

# Relaxed atomics
_RELAXED_ATOMIC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'Ordering\s*::\s*Relaxed'),           "Ordering::Relaxed"),
    (re.compile(r'fetch_add\s*\([^)]+Relaxed'),        "fetch_add with Relaxed ordering"),
    (re.compile(r'fetch_sub\s*\([^)]+Relaxed'),        "fetch_sub with Relaxed ordering"),
]

# MutationGate bypass
_MUTATION_BYPASS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'transmute\s*::\s*<'),                "transmute — unsafe type cast"),
    (re.compile(r'as\s+\*mut\s+\w'),                   "raw mutable pointer cast"),
    (re.compile(r'\*\s*\w+\s*=\s*[^=]'),              "raw pointer write"),
]

# Unstable sort
_UNSTABLE_SORT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\.\s*sort\s*\(\s*\)'),
     ".sort() — may be unstable. Use .sort_by_key() or .sort_by() with stable comparator."),
    (re.compile(r'sort_unstable\s*\(\s*\)'),
     "sort_unstable() — explicitly unstable. Use sort() or sort_by_key()."),
]


# ── Determinism Violation ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class DeterminismViolation:
    """One detected determinism violation."""
    category:    str    # ViolationCategory constant
    description: str    # what was found
    severity:    str    # "error" | "warning"
    line_context: str   # excerpt of offending code (≤100 chars)
    line_number:  int   # approximate line number (0 if unknown)

    def __repr__(self) -> str:
        return (
            f"DeterminismViolation({self.category}: "
            f"{self.description[:50]}...)"
        )


# ── Determinism Report ────────────────────────────────────────────────────────

@dataclass
class DeterminismReport:
    """
    Output of DeterminismCodeChecker.check().

    Attributes
    ----------
    passed          : bool
    violations      : list[DeterminismViolation]  — error-severity violations
    warnings        : list[str]                   — advisory non-blocking
    analysis_notes  : list[str]                   — informational findings
    """
    passed:         bool
    violations:     list[DeterminismViolation] = field(default_factory=list)
    warnings:       list[str]                  = field(default_factory=list)
    analysis_notes: list[str]                  = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def all_descriptions(self) -> list[str]:
        return [v.description for v in self.violations]

    def __repr__(self) -> str:
        status = "PASS" if self.passed else f"FAIL({self.error_count} violations)"
        return f"DeterminismReport({status})"


# ── Determinism Code Checker ──────────────────────────────────────────────────

class DeterminismCodeChecker:
    """
    Deep static analysis for nondeterminism in generated Rust code.

    Stateless — safe to share across sessions.
    Deterministic — same code always produces the same report.
    Fast — all checks are regex-based, O(n) in code length.

    Usage
    -----
        checker = DeterminismCodeChecker()
        report  = checker.check(generated_rust_code)
        if not report.passed:
            for v in report.violations:
                print(f"[{v.category}] {v.description}")
    """

    def check(self, code: str) -> DeterminismReport:
        """
        Analyses generated Rust code for determinism violations.

        Parameters
        ----------
        code : str — the full generated Rust source

        Returns
        -------
        DeterminismReport
        """
        violations: list[DeterminismViolation] = []
        warnings:   list[str]                  = []
        notes:      list[str]                  = []

        lines = code.splitlines()

        # Check 1: Random sources
        violations.extend(
            self._scan(code, lines, ViolationCategory.RANDOM_SOURCE,
                       _RANDOM_PATTERNS, "error")
        )

        # Check 2: Unordered iteration
        violations.extend(
            self._scan(code, lines, ViolationCategory.UNORDERED_ITER,
                       _UNORDERED_ITER_PATTERNS, "error")
        )

        # Check 3: Time sources
        violations.extend(
            self._scan(code, lines, ViolationCategory.TIME_SOURCE,
                       _TIME_PATTERNS, "error")
        )

        # Check 4: Float edge cases
        violations.extend(
            self._scan(code, lines, ViolationCategory.FLOAT_EDGE_CASE,
                       _FLOAT_EDGE_PATTERNS, "error")
        )

        # Check 5: Non-deterministic serialization
        violations.extend(
            self._scan(code, lines, ViolationCategory.NONDETERMINISTIC_SERIALIZATION,
                       _NONDETERMINISTIC_SERIALIZATION_PATTERNS, "error")
        )

        # Check 6: Thread-local / static mutation
        violations.extend(
            self._scan(code, lines, ViolationCategory.THREAD_LOCAL,
                       _THREAD_LOCAL_PATTERNS, "error")
        )

        # Check 7: Relaxed atomics — only flag if inside execute()
        execute_block = self._extract_execute_block(code)
        if execute_block:
            atomic_violations = self._scan(
                execute_block, lines, ViolationCategory.RELAXED_ATOMIC,
                _RELAXED_ATOMIC_PATTERNS, "error"
            )
            if atomic_violations:
                violations.extend(atomic_violations)
            else:
                notes.append("Relaxed atomics not found in execute() — OK.")

        # Check 8: MutationGate bypass
        bypass_violations = self._scan(
            code, lines, ViolationCategory.MUTATION_BYPASS,
            _MUTATION_BYPASS_PATTERNS, "error"
        )
        # Filter out false positives: pointer casts in comments or strings
        for v in bypass_violations:
            if not v.line_context.strip().startswith("//"):
                violations.append(v)

        # Check 9: Unstable sort
        sort_violations = self._scan(
            code, lines, ViolationCategory.UNSTABLE_SORT,
            _UNSTABLE_SORT_PATTERNS, "warning"
        )
        for v in sort_violations:
            if v.severity == "warning":
                warnings.append(f"[{v.category}] {v.description}")
            else:
                violations.append(v)

        # Positive notes
        if "BTreeMap" in code:
            notes.append("Uses BTreeMap — deterministic ordered iteration ✓")
        if "sort_by_key" in code or "sort_by" in code:
            notes.append("Uses stable sort comparator ✓")
        if "ctx.deterministic_rng()" in code:
            notes.append("Uses XACE deterministic RNG ✓")

        passed = not any(v.severity == "error" for v in violations)

        return DeterminismReport(
            passed         = passed,
            violations     = violations,
            warnings       = warnings,
            analysis_notes = notes,
        )

    # ── Pattern scanning ──────────────────────────────────────────────────────

    @staticmethod
    def _scan(
        code:      str,
        all_lines: list[str],
        category:  str,
        patterns:  list[tuple[re.Pattern, str]],
        severity:  str,
    ) -> list[DeterminismViolation]:
        """Scans code for all patterns in the list, skipping comments."""
        found: list[DeterminismViolation] = []
        seen_descriptions: set[str] = set()

        for pattern, description in patterns:
            match = pattern.search(code)
            if not match:
                continue

            # Skip matches in single-line comments
            line_start = code.rfind("\n", 0, match.start()) + 1
            line_content = code[line_start:code.find("\n", match.start())]
            if line_content.lstrip().startswith("//"):
                continue

            if description in seen_descriptions:
                continue
            seen_descriptions.add(description)

            # Find approximate line number
            line_num = code[:match.start()].count("\n") + 1
            context  = code[max(0, match.start()-20):match.start()+60].strip()

            found.append(DeterminismViolation(
                category     = category,
                description  = description,
                severity     = severity,
                line_context = context[:100],
                line_number  = line_num,
            ))

        return found

    @staticmethod
    def _extract_execute_block(code: str) -> str:
        """
        Extracts the body of fn execute() for targeted analysis.
        Returns empty string if not found.
        """
        execute_match = re.search(
            r'fn\s+execute\s*\([^)]+\)\s*\{',
            code, re.MULTILINE,
        )
        if not execute_match:
            return ""

        # Find matching closing brace
        start    = execute_match.end()
        depth    = 1
        pos      = start
        code_len = len(code)

        while pos < code_len and depth > 0:
            c = code[pos]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            pos += 1

        return code[start:pos - 1] if depth == 0 else code[start:]
