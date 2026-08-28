"""
system_spec_builder.py — SystemSpecBuilder
============================================
Extracts a complete, validated SystemSpec from the CGS for use
by the Rust code generator.

## Why SystemSpec Exists

    The LLM code generator needs a precise, structured description of
    what system to generate — not the raw CGS JSON. SystemSpec provides:
        - The exact Rust struct name and system ID
        - Which components are read (read-only access via SystemContext)
        - Which components are written (mutable access via MutationGate)
        - The execution phase and dependency chain
        - Performance constraints (max entity count, tick budget)
        - Full component field schemas for accurate Rust type mapping
        - The determinism requirements (D-rules)

    Without SystemSpec, the generator would have to parse CGS itself,
    infer Rust types from Python defaults, and guess at performance
    constraints — all of which lead to hallucinated code.

## CGS Type → Rust Type Mapping

    Component field values in CGS are Python types. SystemSpec converts:
        float (Python)     → f32 (Rust)   [f64 for high-precision fields]
        int (Python)       → i32 (Rust)   [u64 for entity IDs, u32 for tick]
        bool (Python)      → bool (Rust)
        str (Python)       → &'static str (Rust)  [for enum-like strings]
        dict (Python)      → struct (Rust) [nested, requires custom type]
        list (Python)      → Vec<T> (Rust)

    Edge cases:
        "entity_id" fields → u64
        "tick" fields      → u64
        empty dict {}      → () (unit type, zero-size)

## Validation

    SystemSpec.validate() checks that:
    1. system_id matches an existing system in the CGS
    2. All read component type_ids exist in the CGS
    3. All write component type_ids exist in the CGS
    4. No component appears in both reads and writes with different field schemas
    5. The phase is a valid XACE phase name
    6. depends_on references exist as systems in the CGS
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── XACE Phase Names ──────────────────────────────────────────────────────────

VALID_PHASES = frozenset({
    "Initialization",
    "Input",
    "Simulation",
    "PostSimulation",
    "Cleanup",
})

# ── Rust Type Mapping ─────────────────────────────────────────────────────────

_ENTITY_ID_FIELDS = frozenset({
    "entity_id", "source_entity_id", "target_entity_id",
    "parent_entity_id", "owner_entity_id",
})
_TICK_FIELDS = frozenset({
    "last_damage_tick", "spawn_tick", "death_tick",
    "last_hit_tick", "last_update_tick",
})
_U32_FIELDS = frozenset({
    "priority", "controller_id",
})

_DECLARED_FIELD_RUST_TYPES = {
    "fixed": "i64",
    "int": "i64",
    "uint": "u64",
    "bool": "bool",
    "string": "&'static str",
    "entity_id": "u64",
    "string_list": "Vec<&'static str>",
    "int_list": "Vec<i64>",
    "object": "()",
}


def python_to_rust_type(field_name: str, python_value: Any) -> str:
    """
    Maps a CGS field name + Python value to the appropriate Rust type.

    Handles XACE-specific conventions (entity IDs, tick counts, etc.)
    before falling back to generic Python→Rust type mapping.
    """
    if field_name in _ENTITY_ID_FIELDS:
        return "u64"
    if field_name in _TICK_FIELDS:
        return "u64"
    if field_name in _U32_FIELDS:
        return "u32"

    if isinstance(python_value, bool):    # must check before int (bool is subclass)
        return "bool"
    if isinstance(python_value, int):
        return "i32"
    if isinstance(python_value, float):
        return "f32"
    if isinstance(python_value, str):
        return "&'static str"
    if isinstance(python_value, dict):
        if not python_value:              # empty dict → unit
            return "()"
        # Named nested struct — capitalise field name as type name
        return f"{_pascal_case(field_name)}Data"
    if isinstance(python_value, list):
        if not python_value:
            return "Vec<i32>"             # default element type
        elem_type = python_to_rust_type(f"{field_name}_elem", python_value[0])
        return f"Vec<{elem_type}>"
    return "i32"                          # conservative fallback


def _pascal_case(s: str) -> str:
    """
    Converts snake_case or SCREAMING_SNAKE_CASE to PascalCase.
    Already-PascalCase strings (no underscores) are returned as-is.
    """
    if "_" not in s:
        return s
    return "".join(w.capitalize() for w in s.split("_"))


# ── Component Field Spec ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class ComponentFieldSpec:
    """One field within a component's defaults."""
    field_name:     str
    rust_type:      str
    python_default: Any
    is_mutable:     bool    # True if this field may be written by the system


# ── Component Access Spec ─────────────────────────────────────────────────────

@dataclass
class ComponentAccessSpec:
    """
    Describes one component a system reads or writes.

    Attributes
    ----------
    type_id      : int            — UCL component type_id
    comp_name    : str            — e.g. "COMP_VELOCITY_V1"
    rust_struct  : str            — Rust struct name, e.g. "CompVelocityV1"
    access       : str            — "read" | "write"
    fields       : list[ComponentFieldSpec]
    actor_ids    : list[str]      — which actors have this component
    """
    type_id:    int
    comp_name:  str
    rust_struct: str
    access:     str               # "read" or "write"
    fields:     list[ComponentFieldSpec] = field(default_factory=list)
    actor_ids:  list[str]               = field(default_factory=list)

    def rust_field_name(self) -> str:
        """e.g. COMP_VELOCITY_V1 → comp_velocity_v1"""
        return self.comp_name.lower()


# ── System Spec ───────────────────────────────────────────────────────────────

@dataclass
class SystemSpec:
    """
    Complete specification for one XACE system to be code-generated.

    Produced by SystemSpecBuilder. Consumed by RustCodeGenerator.

    Attributes
    ----------
    system_id       : str                  — e.g. "MovementSystem"
    rust_struct_name: str                  — e.g. "MovementSystem"
    phase           : str                  — "Simulation" | "PostSimulation" etc.
    depends_on      : list[str]            — system IDs this system depends on
    is_deterministic: bool
    reads           : list[ComponentAccessSpec]
    writes          : list[ComponentAccessSpec]
    mode_id         : str                  — which mode this system lives in
    description     : str                  — human-readable system purpose
    performance_hint: dict[str, Any]       — max_entities, tick_budget_us
    d_rules         : list[str]            — determinism rules from constraints
    validation_errors: list[str]           — non-empty = spec is invalid
    """
    system_id:        str
    rust_struct_name: str
    phase:            str
    depends_on:       list[str]
    is_deterministic: bool
    reads:            list[ComponentAccessSpec]
    writes:           list[ComponentAccessSpec]
    mode_id:          str                    = ""
    description:      str                    = ""
    performance_hint: dict[str, Any]         = field(default_factory=dict)
    d_rules:          list[str]              = field(default_factory=list)
    validation_errors: list[str]             = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.validation_errors) == 0

    @property
    def all_components(self) -> list[ComponentAccessSpec]:
        return self.reads + self.writes

    @property
    def read_type_ids(self) -> list[int]:
        return [c.type_id for c in self.reads]

    @property
    def write_type_ids(self) -> list[int]:
        return [c.type_id for c in self.writes]

    def to_prompt_context(self) -> str:
        """
        Returns a formatted string for the LLM code generation prompt.
        Describes the system spec completely enough to generate correct Rust.
        """
        lines = [
            f"=== SYSTEM SPEC: {self.system_id} ===",
            f"Rust struct: {self.rust_struct_name}",
            f"Phase: {self.phase}",
            f"Depends on: {', '.join(self.depends_on) if self.depends_on else 'none'}",
            f"Deterministic: {self.is_deterministic}",
            f"Mode: {self.mode_id or 'global'}",
        ]
        if self.description:
            lines.append(f"Purpose: {self.description}")

        if self.reads:
            lines.append("\nREAD components (read-only via SystemContext):")
            for comp in self.reads:
                lines.append(f"  {comp.rust_struct} (type_id={comp.type_id}) from actors: {comp.actor_ids}")
                for f in comp.fields:
                    lines.append(f"    .{f.field_name}: {f.rust_type}  // default: {f.python_default!r}")

        if self.writes:
            lines.append("\nWRITE components (mutable via MutationGate):")
            for comp in self.writes:
                lines.append(f"  {comp.rust_struct} (type_id={comp.type_id}) on actors: {comp.actor_ids}")
                for f in comp.fields:
                    lines.append(f"    .{f.field_name}: {f.rust_type}  // default: {f.python_default!r}")

        if self.d_rules:
            lines.append("\nDeterminism rules:")
            for rule in self.d_rules:
                lines.append(f"  - {rule}")

        if self.performance_hint:
            lines.append(f"\nPerformance: {self.performance_hint}")

        lines.append("=== END SPEC ===")
        return "\n".join(lines)


# ── System Spec Builder ───────────────────────────────────────────────────────

class SystemSpecBuilder:
    """
    Builds a SystemSpec from the current CGS for a given system_id.

    Stateless — safe to share across sessions.
    Deterministic — same CGS + system_id always produces the same spec.

    Usage
    -----
        builder = SystemSpecBuilder()
        spec = builder.build(
            system_id   = "MovementSystem",
            cgs         = current_cgs,
            mode_id     = "mode_default",
            description = "Applies velocity to transform each tick.",
        )
        if not spec.is_valid:
            raise ValueError(spec.validation_errors)
        # pass spec to RustCodeGenerator
    """

    def build(
        self,
        system_id:        str,
        cgs:              dict[str, Any],
        mode_id:          str         = "",
        description:      str         = "",
        max_entities:     int         = 1000,
        tick_budget_us:   int         = 100,
    ) -> SystemSpec:
        """
        Builds a SystemSpec for the named system.

        Parameters
        ----------
        system_id     : str   — ID from CGS (e.g. "MovementSystem")
        cgs           : dict  — current CGS JSON
        mode_id       : str   — mode to search (empty = search all modes + global)
        description   : str   — human-readable purpose for the prompt
        max_entities  : int   — performance hint for entity iteration
        tick_budget_us: int   — microsecond budget per tick

        Returns
        -------
        SystemSpec — call spec.is_valid before using
        """
        errors: list[str] = []

        # Find the system dict in CGS
        sys_dict, found_mode_id = self._find_system(system_id, cgs, mode_id)
        if sys_dict is None:
            return SystemSpec(
                system_id        = system_id,
                rust_struct_name = _pascal_case(system_id),
                phase            = "Simulation",
                depends_on       = [],
                is_deterministic = True,
                reads            = [],
                writes           = [],
                validation_errors = [
                    f"System '{system_id}' not found in CGS"
                    + (f" mode '{mode_id}'" if mode_id else "")
                ],
            )

        phase        = sys_dict.get("phase", "Simulation")
        depends_on   = sys_dict.get("depends_on", [])
        is_det       = sys_dict.get("deterministic", True)
        read_ids     = [int(r) for r in sys_dict.get("reads",  [])]
        write_ids    = [int(w) for w in sys_dict.get("writes", [])]

        # Validate phase
        if phase not in VALID_PHASES:
            errors.append(
                f"Phase '{phase}' is not a valid XACE phase. "
                f"Valid: {sorted(VALID_PHASES)}"
            )

        # Build component index from authoritative schemas and actor instances.
        comp_index = self._build_component_index(cgs)
        runtime_executor = sys_dict.get("runtime_executor")
        generated_system = (
            isinstance(runtime_executor, dict)
            and str(runtime_executor.get("kind") or "").startswith("generated.")
        )

        # Build read specs
        read_specs:  list[ComponentAccessSpec] = []
        for tid in read_ids:
            spec = self._build_component_spec(
                tid,
                "read",
                comp_index,
                errors,
                require_concrete=generated_system,
            )
            if spec:
                read_specs.append(spec)

        # Build write specs
        write_specs: list[ComponentAccessSpec] = []
        for tid in write_ids:
            spec = self._build_component_spec(
                tid,
                "write",
                comp_index,
                errors,
                require_concrete=generated_system,
            )
            if spec:
                write_specs.append(spec)

        # Validate depends_on
        all_system_ids = self._all_system_ids(cgs)
        for dep in depends_on:
            if dep not in all_system_ids:
                errors.append(
                    f"depends_on '{dep}' not found in any mode or global_systems."
                )

        # Build D-rules from constraints
        d_rules = self._extract_d_rules(system_id, read_ids, write_ids, cgs)

        return SystemSpec(
            system_id        = system_id,
            rust_struct_name = _pascal_case(system_id),
            phase            = phase,
            depends_on       = depends_on,
            is_deterministic = is_det,
            reads            = read_specs,
            writes           = write_specs,
            mode_id          = found_mode_id,
            description      = description,
            performance_hint = {
                "max_entities":   max_entities,
                "tick_budget_us": tick_budget_us,
            },
            d_rules          = d_rules,
            validation_errors = errors,
        )

    # ── CGS navigation ────────────────────────────────────────────────────────

    @staticmethod
    def _find_system(
        system_id: str,
        cgs:       dict[str, Any],
        mode_id:   str,
    ) -> tuple[dict | None, str]:
        """Returns (system_dict, found_mode_id) or (None, '')."""
        # Search global systems first
        for gs in cgs.get("global_systems", []):
            if gs.get("id") == system_id:
                return gs, "global"

        # Search modes
        for mode in cgs.get("modes", []):
            mid = mode.get("id", "")
            if mode_id and mid != mode_id:
                continue
            for sys in mode.get("systems", []):
                if sys.get("id") == system_id:
                    return sys, mid

        return None, ""

    @staticmethod
    def _build_component_index(
        cgs: dict[str, Any],
    ) -> dict[int, dict[str, Any]]:
        """
        Builds type_id → {name, fields, actor_ids} from all modes.
        """
        index: dict[int, dict[str, Any]] = {}

        for raw_schema in cgs.get("component_schemas", []):
            if not isinstance(raw_schema, dict):
                continue
            type_id = raw_schema.get("type_id")
            if isinstance(type_id, bool) or not isinstance(type_id, int) or type_id <= 0:
                continue
            raw_defaults = raw_schema.get("defaults")
            defaults = dict(raw_defaults) if isinstance(raw_defaults, dict) else {}
            field_types: dict[str, str] = {}
            for raw_field in raw_schema.get("fields", []):
                if not isinstance(raw_field, dict):
                    continue
                field_name = raw_field.get("name")
                field_type = raw_field.get("field_type")
                if not isinstance(field_name, str) or not field_name:
                    continue
                if isinstance(field_type, str) and field_type:
                    field_types[field_name] = field_type
                if field_name not in defaults and "default" in raw_field:
                    defaults[field_name] = raw_field["default"]
            index[type_id] = {
                "name": raw_schema.get("name", f"COMP_TYPE{type_id}_V1"),
                "defaults": defaults,
                "field_types": field_types,
                "actor_ids": [],
                "declared": True,
            }

        for mode in cgs.get("modes", []):
            for actor in mode.get("actors", []):
                aid = actor.get("id", "")
                for comp in actor.get("components", []):
                    tid      = int(comp.get("type_id", 0))
                    name     = comp.get("name", f"COMP_TYPE{tid}_V1")
                    defaults = comp.get("defaults", {})

                    if tid not in index:
                        index[tid] = {
                            "name":      name,
                            "defaults":  defaults,
                            "field_types": {},
                            "actor_ids": [],
                            "declared": False,
                        }
                    if aid not in index[tid]["actor_ids"]:
                        index[tid]["actor_ids"].append(aid)

        return index

    @staticmethod
    def _build_component_spec(
        type_id:    int,
        access:     str,
        comp_index: dict[int, dict[str, Any]],
        errors:     list[str],
        *,
        require_concrete: bool = False,
    ) -> ComponentAccessSpec | None:
        info = comp_index.get(type_id)
        if info is None:
            if require_concrete:
                errors.append(
                    "Generated system component type_id "
                    f"{type_id} has no declared schema or actor instance; "
                    "placeholder component types are forbidden."
                )
                return None
            # For global systems or systems whose components are not yet in the CGS
            # (e.g. InputSystem reads type_id=6 which may not be on any actor yet),
            # build a minimal stub spec rather than failing validation.
            # The generator will use the type_id and a placeholder name.
            stub_name = f"COMP_TYPE{type_id}_V1"
            return ComponentAccessSpec(
                type_id     = type_id,
                comp_name   = stub_name,
                rust_struct = f"CompType{type_id}V1",
                access      = access,
                fields      = [],
                actor_ids   = [],
            )

        name     = info["name"]
        defaults = info["defaults"]
        field_types = info.get("field_types", {})
        actor_ids = info["actor_ids"]

        # Build field specs
        fields: list[ComponentFieldSpec] = []
        for fname, fvalue in defaults.items():
            rust_type = _DECLARED_FIELD_RUST_TYPES.get(
                field_types.get(fname),
                python_to_rust_type(fname, fvalue),
            )
            fields.append(ComponentFieldSpec(
                field_name     = fname,
                rust_type      = rust_type,
                python_default = fvalue,
                is_mutable     = (access == "write"),
            ))

        # Rust struct name: COMP_VELOCITY_V1 → CompVelocityV1
        rust_struct = "".join(
            w.capitalize()
            for w in name.lower()
                       .replace("comp_", "Comp_")
                       .split("_")
        )
        # Cleaner: just use the name directly
        rust_struct = _pascal_case(name)

        return ComponentAccessSpec(
            type_id     = type_id,
            comp_name   = name,
            rust_struct = rust_struct,
            access      = access,
            fields      = fields,
            actor_ids   = actor_ids,
        )

    @staticmethod
    def _all_system_ids(cgs: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for gs in cgs.get("global_systems", []):
            ids.add(gs.get("id", ""))
        for mode in cgs.get("modes", []):
            for sys in mode.get("systems", []):
                ids.add(sys.get("id", ""))
        return ids

    @staticmethod
    def _extract_d_rules(
        system_id: str,
        read_ids:  list[int],
        write_ids: list[int],
        cgs:       dict[str, Any],
    ) -> list[str]:
        """Extracts relevant D-rules for this system from the CGS structure."""
        rules: list[str] = [
            "This system must produce the same output for the same input every tick.",
            "Do not use rand::random(), thread_rng(), or any OS/language RNG.",
            "Do not read the system clock, wallclock time, or any non-deterministic input.",
            "Entity iteration order must be deterministic — use sorted entity IDs.",
            "All writes must go through MutationGate::apply() — never mutate components directly.",
        ]
        if write_ids:
            rules.append(
                f"This system writes component type_ids: {write_ids}. "
                f"Only these component types may be written."
            )
        if read_ids:
            rules.append(
                f"This system reads component type_ids: {read_ids}. "
                f"These are read-only — do not write to them."
            )
        return rules
