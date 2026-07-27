"""
unsupported_generated_system_guard.py - Generated-system rejection policy.

This scanner catches generated Rust constructs that XACE does not allow in
gameplay systems before source can reach SGC-backed runtime registration. It is
deliberately conservative: generated gameplay code must stay inside the
declarative runtime ABI and cannot touch the filesystem, network, process
environment, engine APIs, unsafe Rust, or nondeterministic sources directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256


UNSUPPORTED_GENERATED_SYSTEM_POLICY_SCHEMA = "xace.generated_system_unsupported_policy.v1"
UNSUPPORTED_GENERATED_SYSTEM_POLICY_VERSION = 1


@dataclass(frozen=True)
class UnsupportedPattern:
    code: str
    category: str
    message: str
    pattern: str


@dataclass(frozen=True)
class UnsupportedGeneratedSystemFinding:
    code: str
    category: str
    message: str
    line_number: int
    line_context: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "line_number": self.line_number,
            "line_context": self.line_context,
        }


@dataclass
class UnsupportedGeneratedSystemReport:
    schema: str = UNSUPPORTED_GENERATED_SYSTEM_POLICY_SCHEMA
    policy_hash: str = ""
    passed: bool = True
    findings: list[UnsupportedGeneratedSystemFinding] = field(default_factory=list)

    @property
    def all_reasons(self) -> list[str]:
        return [
            f"{finding.code} line {finding.line_number}: {finding.message}"
            for finding in self.findings
        ]

    def summary(self) -> str:
        return "; ".join(self.all_reasons)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy_hash": self.policy_hash,
            "passed": self.passed,
            "findings": [finding.as_dict() for finding in self.findings],
        }


_PATTERNS: tuple[UnsupportedPattern, ...] = (
    UnsupportedPattern(
        "unsupported.unsafe_block",
        "unsafe_rust",
        "unsafe blocks are forbidden in generated gameplay systems",
        r"\bunsafe\s*\{",
    ),
    UnsupportedPattern(
        "unsupported.unsafe_fn",
        "unsafe_rust",
        "unsafe functions are forbidden in generated gameplay systems",
        r"\bunsafe\s+fn\b",
    ),
    UnsupportedPattern(
        "unsupported.unsafe_impl",
        "unsafe_rust",
        "unsafe impl blocks are forbidden in generated gameplay systems",
        r"\bunsafe\s+impl\b",
    ),
    UnsupportedPattern(
        "unsupported.extern_ffi",
        "unsafe_rust",
        "FFI extern blocks are forbidden in generated gameplay systems",
        r'\bextern\s+"(?:C|system|stdcall|cdecl)"',
    ),
    UnsupportedPattern(
        "unsupported.raw_pointer",
        "unsafe_rust",
        "raw pointer access is forbidden in generated gameplay systems",
        r"\b(?:\*mut|\*const)\b|as\s+\*mut|as\s+\*const",
    ),
    UnsupportedPattern(
        "unsupported.transmute",
        "unsafe_rust",
        "transmute is forbidden in generated gameplay systems",
        r"\b(?:std\s*::\s*mem\s*::\s*)?transmute\s*(?:<|\()",
    ),
    UnsupportedPattern(
        "unsupported.filesystem_access",
        "filesystem_access",
        "filesystem access is forbidden; generated systems must use CGS/runtime state only",
        r"\bstd\s*::\s*fs\b|\bfs\s*::\s*(?:read|read_to_string|write|copy|rename|remove_file|remove_dir|metadata|canonicalize)|\bFile\s*::\s*(?:open|create)|\bOpenOptions\b|\binclude_(?:str|bytes)!\s*\(",
    ),
    UnsupportedPattern(
        "unsupported.network_access",
        "network_access",
        "network access is forbidden; generated systems must not open sockets or HTTP clients",
        r"\bstd\s*::\s*net\b|\b(?:TcpStream|TcpListener|UdpSocket)\b|(?:reqwest|hyper|ureq|tokio\s*::\s*net)\s*::",
    ),
    UnsupportedPattern(
        "unsupported.process_env_access",
        "process_env_access",
        "process and environment access are forbidden in generated gameplay systems",
        r"\bstd\s*::\s*process\b|\bCommand\s*::\s*new\b|\bstd\s*::\s*env\b|\benv\s*::\s*(?:var|args|set_var|remove_var)\b",
    ),
    UnsupportedPattern(
        "unsupported.thread_or_async_spawn",
        "threading_async",
        "generated systems must not spawn threads, async tasks, or parallel jobs directly",
        r"\bstd\s*::\s*thread\b|\bthread\s*::\s*spawn\b|\btokio\s*::\s*spawn\b|\brayon\s*::|\basync\s+fn\b|\bspawn_blocking\b",
    ),
    UnsupportedPattern(
        "unsupported.engine_api_godot",
        "engine_only_api",
        "Godot APIs are engine-owned and cannot be called from generated runtime systems",
        r"\bgodot\s*::|\bgdnative\s*::|\bGodot\b",
    ),
    UnsupportedPattern(
        "unsupported.engine_api_unity",
        "engine_only_api",
        "Unity APIs are engine-owned and cannot be called from generated runtime systems",
        r"\bUnityEngine\b|\bMonoBehaviour\b",
    ),
    UnsupportedPattern(
        "unsupported.engine_api_unreal",
        "engine_only_api",
        "Unreal APIs are engine-owned and cannot be called from generated runtime systems",
        r"\bunreal\s*::|\bUWorld\b|\bAActor\b|\bFVector\b|\bUObject\b",
    ),
    UnsupportedPattern(
        "unsupported.engine_adapter_escape",
        "engine_only_api",
        "engine adapter calls are forbidden; generated systems must emit semantic runtime events instead",
        r"\bxace_engine_adapter\b|\bEngineAdapter\b|\bemit_engine_command\b|\bspawn_engine\b|\bctx\s*\.\s*engine_",
    ),
    UnsupportedPattern(
        "nondeterministic.random_source",
        "nondeterministic_construct",
        "nondeterministic random sources are forbidden; use the ABI RNG hook only",
        r"\brand\s*::\s*random\b|\bthread_rng\s*\(|\bOsRng\b|\bgetrandom\s*::",
    ),
    UnsupportedPattern(
        "nondeterministic.time_source",
        "nondeterministic_construct",
        "wall-clock time sources are forbidden; use current_tick only when declared in the ABI",
        r"\bInstant\s*::\s*now\b|\bSystemTime\s*::\s*now\b",
    ),
    UnsupportedPattern(
        "nondeterministic.unordered_collection",
        "nondeterministic_construct",
        "unordered collections are forbidden in generated systems; use BTreeMap/BTreeSet or sorted Vec",
        r"\bHashMap\b|\bHashSet\b|\bDashMap\b|\bRandomState\b",
    ),
)


def check_unsupported_generated_system(code: str) -> UnsupportedGeneratedSystemReport:
    findings: list[UnsupportedGeneratedSystemFinding] = []
    seen_codes: set[str] = set()
    lines = code.splitlines()

    for pattern in _PATTERNS:
        regex = re.compile(pattern.pattern)
        for line_number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("//"):
                continue
            match = regex.search(line)
            if not match:
                continue
            if pattern.code in seen_codes:
                break
            seen_codes.add(pattern.code)
            findings.append(
                UnsupportedGeneratedSystemFinding(
                    code=pattern.code,
                    category=pattern.category,
                    message=pattern.message,
                    line_number=line_number,
                    line_context=line.strip()[:120],
                )
            )
            break

    return UnsupportedGeneratedSystemReport(
        policy_hash=unsupported_policy_hash(),
        passed=not findings,
        findings=findings,
    )


def unsupported_policy_manifest() -> dict[str, object]:
    return {
        "schema": UNSUPPORTED_GENERATED_SYSTEM_POLICY_SCHEMA,
        "version": UNSUPPORTED_GENERATED_SYSTEM_POLICY_VERSION,
        "patterns": [
            {
                "code": pattern.code,
                "category": pattern.category,
                "message": pattern.message,
                "pattern": pattern.pattern,
            }
            for pattern in _PATTERNS
        ],
    }


def unsupported_policy_hash() -> str:
    payload = json.dumps(
        unsupported_policy_manifest(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()
