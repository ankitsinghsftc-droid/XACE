"""
cargo_compiler.py — CargoCompiler
====================================
Runs `cargo check` on generated Rust code, captures errors, and
feeds them back to RustCodeGenerator for self-correction.

## Role in the Pipeline

    RustCodeGenerator  → GeneratedCode
        → CodeContractValidator  → ContractValidationResult (passed)
        → DeterminismCodeChecker → DeterminismReport (passed)
        → CargoCompiler          → CompileResult
            if passed  → GeneratedCode committed to file system
            if failed  → error + original code fed back to RustCodeGenerator
                         (within the 2-attempt hard cap)

## How It Works

    1. Creates a temporary Rust project in /tmp/xace_codegen_{hash}/
    2. Writes a Cargo.toml that imports xace_engine as a local path dep
       (or a stub Cargo.toml for isolated test environments)
    3. Writes the generated code to src/lib.rs
    4. Runs `cargo check --message-format json` via subprocess
    5. Parses compiler error JSON output (rustc's machine-readable format)
    6. Returns CompileResult with structured error list

## Error Feedback Format

    When cargo check fails, CompileResult.formatted_errors() returns
    a string suitable for injection into the next generation attempt:

        COMPILE ERRORS:
        [E0277] src/lib.rs:42 — the trait `ISystem` is not implemented for `MovementSystem`
            note: required because of the requirements on the impl of `ISystem`
        [E0308] src/lib.rs:67 — mismatched types: expected `f32`, found `i32`

    This format is precise enough for the model to fix the specific
    errors on the second attempt.

## Fallback for Test Environments

    If `cargo` is not installed or not on PATH, CargoCompiler returns
    a CompileResult indicating cargo is unavailable. The engine treats
    this as a WARNING (not a block) and proceeds — the code will be
    compiled at actual Rust build time.

## Hard Cap

    The CargoCompiler does NOT enforce the retry cap itself — that is
    done by CodeGenerationEngine. CargoCompiler simply runs cargo check
    once and returns the result.

## Temp Directory Management

    Temp directories are created under /tmp/ and cleaned up after each
    compile run. They are NOT reused between calls to prevent stale
    state from affecting results.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from system_spec_builder import SystemSpec


# ── Constants ─────────────────────────────────────────────────────────────────

CARGO_TIMEOUT_SECONDS  = 60     # max time for cargo check
CARGO_CHECK_COMMAND    = "cargo"
CARGO_CHECK_ARGS       = ["check", "--message-format", "json", "--quiet"]


# ── Compile Error ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompileError:
    """One structured compiler error."""
    error_code: str    # e.g. "E0277"
    message:    str    # human-readable error message
    file:       str    # source file path (relative)
    line:       int    # line number (0 if unknown)
    column:     int    # column (0 if unknown)
    level:      str    # "error" | "warning" | "note"
    context:    str    # additional context (notes, help text)

    def __repr__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"CompileError({self.error_code}, {loc}: {self.message[:60]})"

    def formatted(self) -> str:
        loc     = f"{self.file}:{self.line}" if self.line else ""
        code    = f"[{self.error_code}] " if self.error_code else ""
        context = f"\n    note: {self.context[:100]}" if self.context else ""
        return f"{code}{loc} — {self.message}{context}"


# ── Compile Result ────────────────────────────────────────────────────────────

@dataclass
class CompileResult:
    """
    Result of one CargoCompiler.compile() call.

    Attributes
    ----------
    passed           : bool             — True if cargo check succeeded
    errors           : list[CompileError] — compiler errors (empty on pass)
    warnings_count   : int              — number of warnings (non-blocking)
    cargo_available  : bool             — False if cargo not installed
    duration_ms      : float            — wall-clock time for cargo check
    raw_output       : str              — full cargo check output
    temp_dir_used    : str              — temp directory path (cleaned up)
    """
    passed:         bool
    errors:         list[CompileError] = field(default_factory=list)
    warnings_count: int                = 0
    cargo_available: bool              = True
    duration_ms:    float              = 0.0
    raw_output:     str                = ""
    temp_dir_used:  str                = ""

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def formatted_errors(self) -> str:
        """
        Returns a formatted error report suitable for LLM correction prompt.
        """
        if self.passed:
            return ""
        if not self.cargo_available:
            return "(cargo not available — code will be validated at build time)"

        lines = ["COMPILE ERRORS (fix all before retrying):"]
        for i, err in enumerate(self.errors[:8], 1):   # cap at 8
            lines.append(f"  {i}. {err.formatted()}")
        if len(self.errors) > 8:
            lines.append(f"  ... and {len(self.errors) - 8} more errors.")
        return "\n".join(lines)

    def __repr__(self) -> str:
        if not self.cargo_available:
            return "CompileResult(cargo_unavailable)"
        status = "PASS" if self.passed else f"FAIL({self.error_count} errors)"
        return f"CompileResult({status}, {self.duration_ms:.0f}ms)"


# ── Cargo Compiler ────────────────────────────────────────────────────────────

class CargoCompiler:
    """
    Wraps `cargo check` for generated Rust code validation.

    Stateless — one instance shared across the session.

    Usage
    -----
        compiler = CargoCompiler()
        result   = compiler.compile(generated_code, spec)
        if not result.passed:
            error_feedback = result.formatted_errors()
            # feed error_feedback to RustCodeGenerator for retry
    """

    def compile(
        self,
        code:          str,
        spec:          SystemSpec,
        extra_cargo_toml_deps: str = "",
    ) -> CompileResult:
        """
        Runs cargo check on the generated Rust code.

        Parameters
        ----------
        code                   : str  — generated Rust source
        spec                   : SystemSpec
        extra_cargo_toml_deps  : str  — additional [dependencies] lines

        Returns
        -------
        CompileResult
        """
        # Check cargo availability
        if not self._cargo_available():
            return CompileResult(
                passed          = False,
                cargo_available = False,
                raw_output      = "cargo not found on PATH",
            )

        temp_dir = ""
        try:
            temp_dir = self._setup_temp_project(code, spec, extra_cargo_toml_deps)
            return self._run_cargo_check(temp_dir)
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ── Project setup ─────────────────────────────────────────────────────────

    @staticmethod
    def _setup_temp_project(
        code:      str,
        spec:      SystemSpec,
        extra_deps: str,
    ) -> str:
        """
        Creates a temporary Cargo project with the generated code.
        Returns the temp directory path.
        """
        temp_dir = tempfile.mkdtemp(prefix=f"xace_codegen_{spec.system_id}_")

        # Create src/ directory
        src_dir = os.path.join(temp_dir, "src")
        os.makedirs(src_dir, exist_ok=True)

        # Write Cargo.toml
        cargo_toml = _build_cargo_toml(spec.system_id, extra_deps)
        with open(os.path.join(temp_dir, "Cargo.toml"), "w") as f:
            f.write(cargo_toml)

        # Write lib.rs with XACE stubs at crate root and generated code in an
        # isolated module. Generated systems commonly import crate interfaces;
        # putting them at crate root would make those imports collide with stubs.
        lib_content = (
            _XACE_STUBS
            + "\n\n"
            + _build_component_stubs(spec)
            + "\n\npub mod generated_system {\n"
            + "use super::*;\n\n"
            + code
            + "\n}\n"
        )
        with open(os.path.join(src_dir, "lib.rs"), "w") as f:
            f.write(lib_content)

        return temp_dir

    # ── Cargo execution ───────────────────────────────────────────────────────

    @staticmethod
    def _run_cargo_check(temp_dir: str) -> CompileResult:
        """Runs cargo check and parses the output."""
        start_ms = time.monotonic() * 1000

        try:
            proc = subprocess.run(
                [CARGO_CHECK_COMMAND] + CARGO_CHECK_ARGS,
                cwd     = temp_dir,
                capture_output = True,
                text    = True,
                timeout = CARGO_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                passed     = False,
                errors     = [CompileError(
                    error_code = "TIMEOUT",
                    message    = f"cargo check timed out after {CARGO_TIMEOUT_SECONDS}s",
                    file       = "src/lib.rs",
                    line       = 0, column = 0,
                    level      = "error", context = "",
                )],
                duration_ms = CARGO_TIMEOUT_SECONDS * 1000,
                raw_output  = "TIMEOUT",
                temp_dir_used = temp_dir,
            )
        except FileNotFoundError:
            return CompileResult(
                passed          = False,
                cargo_available = False,
                raw_output      = "cargo binary not found",
            )

        duration = time.monotonic() * 1000 - start_ms
        raw      = proc.stdout + proc.stderr

        # Parse JSON diagnostic messages
        errors:   list[CompileError] = []
        warnings: int                = 0

        for line in (proc.stdout + proc.stderr).splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            if msg.get("reason") != "compiler-message":
                continue

            diag    = msg.get("message", {})
            level   = diag.get("level", "")
            message = diag.get("message", "")
            code    = (diag.get("code") or {}).get("code", "")
            spans   = diag.get("spans", [])

            if level == "warning":
                warnings += 1
                continue
            if level not in {"error", "error[E]"}:
                continue

            # Extract location from first span
            file_name = "src/lib.rs"
            line_num  = 0
            col_num   = 0
            if spans:
                primary = next((s for s in spans if s.get("is_primary")), spans[0])
                file_name = primary.get("file_name", "src/lib.rs")
                line_num  = primary.get("line_start", 0)
                col_num   = primary.get("column_start", 0)

            # Gather notes/help from children
            context_parts: list[str] = []
            for child in diag.get("children", []):
                child_msg = child.get("message", "")
                if child_msg and child.get("level") in {"note", "help"}:
                    context_parts.append(child_msg[:100])

            errors.append(CompileError(
                error_code = code,
                message    = message,
                file       = file_name,
                line       = line_num,
                column     = col_num,
                level      = "error",
                context    = " | ".join(context_parts[:2]),
            ))

        # If no JSON errors but proc.returncode != 0, try text parsing
        if not errors and proc.returncode != 0:
            errors = _parse_text_errors(proc.stderr or proc.stdout)

        passed = proc.returncode == 0 and not errors

        return CompileResult(
            passed          = passed,
            errors          = errors,
            warnings_count  = warnings,
            cargo_available = True,
            duration_ms     = duration,
            raw_output      = raw[:3000],
            temp_dir_used   = temp_dir,
        )

    # ── Availability check ────────────────────────────────────────────────────

    @staticmethod
    def _cargo_available() -> bool:
        """Returns True if `cargo` is installed and on PATH."""
        return shutil.which(CARGO_CHECK_COMMAND) is not None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_cargo_toml(system_name: str, extra_deps: str = "") -> str:
    """Generates a Cargo.toml for the temporary project."""
    base_deps = extra_deps or ""
    return f"""\
[package]
name = "{system_name.lower().replace('_', '-')}"
version = "0.1.0"
edition = "2021"

[dependencies]
{base_deps}

[lib]
name = "{system_name.lower()}"
path = "src/lib.rs"

[profile.dev]
opt-level = 0
debug = false
"""


def _build_component_stubs(spec: SystemSpec) -> str:
    """Generates minimal component structs referenced by the generated system."""
    lines: list[str] = []
    seen: set[str] = set()
    for component in spec.all_components:
        if component.rust_struct in seen:
            continue
        seen.add(component.rust_struct)
        lines.append("#[derive(Default, Clone)]")
        lines.append(f"pub struct {component.rust_struct} {{")
        for field in component.fields:
            lines.append(f"    pub {field.field_name}: {field.rust_type},")
        lines.append("}")
        lines.append(f"impl Component for {component.rust_struct} {{}}")
        lines.append("")
    return "\n".join(lines)


def _parse_text_errors(stderr: str) -> list[CompileError]:
    """
    Fallback text parser for cargo error output when JSON parsing yields nothing.
    Handles the human-readable `error[EXXXX]: message` format.
    """
    errors: list[CompileError] = []
    pattern = re.compile(
        r'error\[?(E\d+)?\]?:\s*(.+)',
        re.MULTILINE,
    )
    loc_pattern = re.compile(r'-->\s*([^:]+):(\d+):(\d+)')

    for match in pattern.finditer(stderr):
        code    = match.group(1) or ""
        message = match.group(2).strip()

        # Look for location on next line
        loc_match = loc_pattern.search(stderr, match.end())
        file_name = "src/lib.rs"
        line_num  = 0
        col_num   = 0
        if loc_match and loc_match.start() < match.end() + 200:
            file_name = loc_match.group(1)
            line_num  = int(loc_match.group(2))
            col_num   = int(loc_match.group(3))

        errors.append(CompileError(
            error_code = code,
            message    = message[:200],
            file       = file_name,
            line       = line_num,
            column     = col_num,
            level      = "error",
            context    = "",
        ))

    return errors[:10]  # cap at 10


# ── XACE Stubs (for isolated compilation) ────────────────────────────────────

_XACE_STUBS = """\
//! XACE engine stubs for cargo check validation.
//! These mirror the real XACE interfaces without implementation.

#![allow(unused_variables, dead_code, unused_imports)]

use std::collections::BTreeMap;

pub type EntityId = u64;

pub trait Component: 'static + Send + Sync {}

pub struct SystemContext {
    _phantom: std::marker::PhantomData<()>,
}

impl SystemContext {
    pub fn read_component<C: Component>(&self, entity: EntityId) -> Option<&C> {
        unimplemented!()
    }
    pub fn entities_with<C: Component>(&self) -> Vec<EntityId> {
        vec![]
    }
    pub fn mutation_gate(&mut self) -> &mut MutationGate {
        unimplemented!()
    }
    pub fn deterministic_rng(&mut self) -> &mut DeterministicRng {
        unimplemented!()
    }
    pub fn current_tick(&self) -> u64 { 0 }
}

pub struct MutationGate;

#[derive(Debug)]
pub struct MutationError;

impl MutationGate {
    pub fn apply<C: Component>(&mut self, entity: EntityId, mutation: C) -> Result<(), MutationError> {
        Ok(())
    }
    pub fn apply_partial<C: Component, F>(&mut self, entity: EntityId, f: F) -> Result<(), MutationError>
    where F: FnOnce(&mut C) {
        Ok(())
    }
}

pub struct DeterministicRng;

impl DeterministicRng {
    pub fn next_u32(&mut self) -> u32 { 0 }
    pub fn next_f32(&mut self) -> f32 { 0.0 }
    pub fn next_range(&mut self, low: i32, high: i32) -> i32 { low }
}

pub trait ISystem: Send + Sync {
    fn init(&mut self, ctx: &mut SystemContext);
    fn execute(&mut self, ctx: &mut SystemContext);
}
"""
