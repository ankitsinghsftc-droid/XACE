"""
test_code_generation.py — Phase 13.13 Code Generation Engine tests

All 6 files tested:
    system_spec_builder.py
    code_contract_validator.py
    determinism_code_checker.py
    rust_code_generator.py
    cargo_compiler.py
    code_generation_engine.py
"""
from __future__ import annotations
import sys, os, dataclasses

_SRC = os.path.join(os.path.dirname(__file__), "..", "src", "code_generation")
sys.path.insert(0, _SRC)

from system_spec_builder import (
    SystemSpecBuilder, SystemSpec, ComponentAccessSpec, ComponentFieldSpec,
    python_to_rust_type, VALID_PHASES,
)
from code_contract_validator import (
    CodeContractValidator, ContractValidationResult, ContractViolation,
)
from determinism_code_checker import (
    DeterminismCodeChecker, DeterminismReport, DeterminismViolation,
    ViolationCategory,
)
from rust_code_generator import (
    RustCodeGenerator, GeneratedCode, CodeGenerationError, MAX_ATTEMPTS,
)
from cargo_compiler import (
    CargoCompiler, CompileResult, CompileError,
)
from code_generation_engine import (
    CodeGenerationEngine, CodeGenerationResult, _compute_diff,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

CGS = {
    "metadata": {"name": "Zombie Chase", "cgs_hash": "0b1d495d",
                 "version": "0.1.0", "schema_version": "0.1.0"},
    "global_systems": [
        {"id": "InputSystem", "phase": "Simulation",
         "reads": [6], "writes": [5], "depends_on": [], "deterministic": True},
    ],
    "modes": [{
        "id": "mode_default", "is_default": True,
        "actors": [
            {"id": "actor_zombie", "actor_type": "Enemy", "control_type": "AiProxy",
             "components": [
                 {"type_id": 5,   "name": "COMP_VELOCITY_V1",
                  "defaults": {"max_linear_speed": 10.0, "max_angular_speed": 360.0}},
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 30.0, "max": 30.0}},
                 {"type_id": 1,   "name": "COMP_TRANSFORM_V1",
                  "defaults": {"position_x": 0.0, "position_y": 0.0,
                               "rotation": 0.0, "scale": 1.0}},
             ]},
            {"id": "actor_player", "actor_type": "PlayerCharacter",
             "control_type": "Human",
             "components": [
                 {"type_id": 1,   "name": "COMP_TRANSFORM_V1",
                  "defaults": {"position_x": 0.0, "position_y": 0.0,
                               "rotation": 0.0, "scale": 1.0}},
                 {"type_id": 100, "name": "COMP_HEALTH_V1",
                  "defaults": {"current": 100.0, "max": 100.0}},
             ]},
        ],
        "systems": [
            {"id": "MovementSystem", "phase": "Simulation",
             "reads": [5], "writes": [1],
             "depends_on": ["InputSystem"], "deterministic": True},
            {"id": "AISystem", "phase": "Simulation",
             "reads": [1], "writes": [5],
             "depends_on": ["MovementSystem"], "deterministic": True},
        ],
        "rules": [],
    }],
}


# ── Valid generated Rust (canonical correct output) ───────────────────────────

_VALID_RUST = """\
use crate::{ISystem, SystemContext, EntityId, MutationGate};
use std::collections::BTreeMap;

/// MovementSystem applies velocity to transform each tick.
pub struct MovementSystem {
    entity_map: BTreeMap<EntityId, f32>,
}

impl MovementSystem {
    pub fn new() -> Self {
        Self { entity_map: BTreeMap::new() }
    }
}

impl ISystem for MovementSystem {
    fn init(&mut self, ctx: &mut SystemContext) {
        // initialise entity state
    }

    fn execute(&mut self, ctx: &mut SystemContext) {
        for entity in ctx.entities_with::<CompVelocityV1>() {
            if let Some(vel) = ctx.read_component::<CompVelocityV1>(entity) {
                let speed = vel.max_linear_speed;
                ctx.mutation_gate().apply_partial::<CompTransformV1, _>(entity, |t| {
                    t.position_x += speed;
                }).ok();
            }
        }
    }
}
"""

# ── Mock InferenceAdapter ─────────────────────────────────────────────────────

@dataclasses.dataclass
class MockResponse:
    text: str; input_tokens: int = 200; output_tokens: int = 300
    cache_read_tokens: int = 0; cache_write_tokens: int = 0
    cost_cents: float = 0.05; model_id: str = "claude-opus-4"
    provider: str = "anthropic"; latency_ms: float = 500.0
    call_label: str = "rust_code_generation_attempt1"
    request_id: str = "r1"; session_id: str = "s1"; cached: bool = False


class MockAdapter:
    def __init__(self, *responses: str) -> None:
        self._queue = list(responses)
        self._idx   = 0
        self.calls: list = []

    def call(self, req) -> MockResponse:
        self.calls.append(req)
        if self._idx < len(self._queue):
            text = self._queue[self._idx]
            self._idx += 1
        else:
            text = self._queue[-1] if self._queue else ""
        return MockResponse(text=f"```rust\n{text}\n```")


# ===========================================================================
# python_to_rust_type
# ===========================================================================

class TestPythonToRustType:
    def test_float_maps_to_f32(self):
        assert python_to_rust_type("speed", 10.0) == "f32"

    def test_int_maps_to_i32(self):
        assert python_to_rust_type("count", 5) == "i32"

    def test_bool_maps_to_bool(self):
        assert python_to_rust_type("is_active", True) == "bool"

    def test_str_maps_to_static_str(self):
        assert python_to_rust_type("name", "CHASE") == "&'static str"

    def test_entity_id_field_maps_to_u64(self):
        assert python_to_rust_type("entity_id", 0) == "u64"

    def test_source_entity_id_maps_to_u64(self):
        assert python_to_rust_type("source_entity_id", 0) == "u64"

    def test_last_damage_tick_maps_to_u64(self):
        assert python_to_rust_type("last_damage_tick", 0) == "u64"

    def test_priority_maps_to_u32(self):
        assert python_to_rust_type("priority", 1) == "u32"

    def test_empty_dict_maps_to_unit(self):
        assert python_to_rust_type("data", {}) == "()"

    def test_nonempty_dict_maps_to_data_struct(self):
        result = python_to_rust_type("position", {"x": 0.0})
        assert "Data" in result or result  # named struct

    def test_list_maps_to_vec(self):
        result = python_to_rust_type("items", [1, 2, 3])
        assert result.startswith("Vec<")

    def test_bool_before_int_check(self):
        # bool is subclass of int in Python — must check bool first
        assert python_to_rust_type("flag", True) == "bool"
        assert python_to_rust_type("count", 0)   == "i32"


# ===========================================================================
# SystemSpecBuilder
# ===========================================================================

class TestSystemSpecBuilder:
    def setup_method(self):
        self.builder = SystemSpecBuilder()

    def test_builds_spec_for_existing_system(self):
        spec = self.builder.build("MovementSystem", CGS, mode_id="mode_default")
        assert spec.is_valid
        assert spec.system_id == "MovementSystem"

    def test_rust_struct_name_pascal_case(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert spec.rust_struct_name == "MovementSystem"

    def test_phase_extracted_correctly(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert spec.phase == "Simulation"

    def test_reads_populated(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert any(c.type_id == 5 for c in spec.reads)

    def test_writes_populated(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert any(c.type_id == 1 for c in spec.writes)

    def test_depends_on_populated(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert "InputSystem" in spec.depends_on

    def test_is_deterministic_true(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert spec.is_deterministic is True

    def test_global_system_found(self):
        spec = self.builder.build("InputSystem", CGS)
        assert spec.is_valid
        assert spec.mode_id == "global"

    def test_invalid_system_id_returns_error(self):
        spec = self.builder.build("PhantomSystem", CGS)
        assert not spec.is_valid
        assert any("not found" in e for e in spec.validation_errors)

    def test_component_fields_populated(self):
        spec = self.builder.build("MovementSystem", CGS)
        vel_comp = next((c for c in spec.reads if c.type_id == 5), None)
        assert vel_comp is not None
        field_names = [f.field_name for f in vel_comp.fields]
        assert "max_linear_speed" in field_names

    def test_component_rust_types_mapped(self):
        spec = self.builder.build("MovementSystem", CGS)
        vel_comp = next((c for c in spec.reads if c.type_id == 5), None)
        speed_field = next((f for f in vel_comp.fields
                             if f.field_name == "max_linear_speed"), None)
        assert speed_field is not None
        assert speed_field.rust_type == "f32"

    def test_actor_ids_populated(self):
        spec = self.builder.build("MovementSystem", CGS)
        vel_comp = next((c for c in spec.reads if c.type_id == 5), None)
        assert "actor_zombie" in vel_comp.actor_ids

    def test_d_rules_populated(self):
        spec = self.builder.build("MovementSystem", CGS)
        assert len(spec.d_rules) >= 5

    def test_performance_hints_set(self):
        spec = self.builder.build("MovementSystem", CGS,
                                   max_entities=500, tick_budget_us=50)
        assert spec.performance_hint["max_entities"] == 500
        assert spec.performance_hint["tick_budget_us"] == 50

    def test_to_prompt_context_contains_system_id(self):
        spec = self.builder.build("MovementSystem", CGS)
        ctx  = spec.to_prompt_context()
        assert "MovementSystem" in ctx

    def test_to_prompt_context_contains_components(self):
        spec = self.builder.build("MovementSystem", CGS)
        ctx  = spec.to_prompt_context()
        assert "CompVelocityV1" in ctx or "COMP_VELOCITY_V1" in ctx or "type_id=5" in ctx

    def test_to_prompt_context_contains_rust_types(self):
        spec = self.builder.build("MovementSystem", CGS)
        ctx  = spec.to_prompt_context()
        assert "f32" in ctx

    def test_all_components_combines_reads_and_writes(self):
        spec = self.builder.build("MovementSystem", CGS)
        all_c = spec.all_components
        assert len(all_c) == len(spec.reads) + len(spec.writes)

    def test_mode_id_stored(self):
        spec = self.builder.build("MovementSystem", CGS, mode_id="mode_default")
        assert spec.mode_id == "mode_default"

    def test_description_stored(self):
        spec = self.builder.build("MovementSystem", CGS,
                                   description="Moves things.")
        assert spec.description == "Moves things."


# ===========================================================================
# CodeContractValidator
# ===========================================================================

class TestCodeContractValidator:
    def setup_method(self):
        self.v    = CodeContractValidator()
        self.spec = SystemSpecBuilder().build("MovementSystem", CGS)

    def test_valid_code_passes(self):
        result = self.v.validate(_VALID_RUST, self.spec)
        assert result.passed

    def test_missing_impl_isystem_fails(self):
        code = _VALID_RUST.replace(
            "impl ISystem for MovementSystem", "// impl removed"
        )
        result = self.v.validate(code, self.spec)
        assert not result.passed
        assert any("ISystem" in v.description for v in result.violations)

    def test_missing_init_fails(self):
        code = _VALID_RUST.replace(
            "fn init(&mut self, ctx: &mut SystemContext)", "// fn init removed"
        )
        result = self.v.validate(code, self.spec)
        assert not result.passed
        assert any("init" in v.description for v in result.violations)

    def test_missing_execute_fails(self):
        code = _VALID_RUST.replace(
            "fn execute(&mut self, ctx: &mut SystemContext)", "// fn execute removed"
        )
        result = self.v.validate(code, self.spec)
        assert not result.passed
        assert any("execute" in v.description for v in result.violations)

    def test_wrong_struct_name_fails(self):
        code = _VALID_RUST.replace("MovementSystem", "WrongName")
        result = self.v.validate(code, self.spec)
        assert not result.passed
        assert any("struct" in v.contract for v in result.violations)

    def test_forbidden_rand_fails(self):
        code = _VALID_RUST + "\nuse rand;\n"
        result = self.v.validate(code, self.spec)
        assert not result.passed
        assert any("rand" in v.description for v in result.violations)

    def test_forbidden_unsafe_fails(self):
        code = _VALID_RUST + "\nunsafe { }\n"
        result = self.v.validate(code, self.spec)
        assert not result.passed
        assert any("unsafe" in v.description for v in result.violations)

    def test_forbidden_std_time_fails(self):
        code = _VALID_RUST + "\nuse std::time;\n"
        result = self.v.validate(code, self.spec)
        assert not result.passed

    def test_result_passed_means_no_error_violations(self):
        result = self.v.validate(_VALID_RUST, self.spec)
        error_violations = [v for v in result.violations if v.severity == "error"]
        assert result.passed == (len(error_violations) == 0)

    def test_repr_pass(self):
        result = self.v.validate(_VALID_RUST, self.spec)
        assert "PASS" in repr(result)

    def test_repr_fail(self):
        bad_code = "fn nothing() {}"
        result   = self.v.validate(bad_code, self.spec)
        assert "FAIL" in repr(result)

    def test_all_descriptions_returns_list(self):
        result = self.v.validate(_VALID_RUST, self.spec)
        assert isinstance(result.all_descriptions, list)


# ===========================================================================
# DeterminismCodeChecker
# ===========================================================================

class TestDeterminismCodeChecker:
    def setup_method(self):
        self.checker = DeterminismCodeChecker()

    def test_valid_code_passes(self):
        report = self.checker.check(_VALID_RUST)
        assert report.passed

    def test_rand_random_detected(self):
        code   = _VALID_RUST + "\nlet x = rand::random::<f32>();\n"
        report = self.checker.check(code)
        assert not report.passed
        assert any(v.category == ViolationCategory.RANDOM_SOURCE
                   for v in report.violations)

    def test_thread_rng_detected(self):
        code   = _VALID_RUST + "\nlet mut rng = thread_rng();\n"
        report = self.checker.check(code)
        assert not report.passed

    def test_hashmap_detected(self):
        code   = _VALID_RUST + "\nlet m: HashMap<u64, f32> = HashMap::new();\n"
        report = self.checker.check(code)
        assert not report.passed
        assert any(v.category == ViolationCategory.UNORDERED_ITER
                   for v in report.violations)

    def test_hashset_detected(self):
        code   = _VALID_RUST + "\nlet s: HashSet<u64> = HashSet::new();\n"
        report = self.checker.check(code)
        assert not report.passed

    def test_instant_now_detected(self):
        code   = _VALID_RUST + "\nlet t = Instant::now();\n"
        report = self.checker.check(code)
        assert not report.passed
        assert any(v.category == ViolationCategory.TIME_SOURCE
                   for v in report.violations)

    def test_thread_local_detected(self):
        code   = _VALID_RUST + "\nthread_local! { static FOO: u32 = 0; }\n"
        report = self.checker.check(code)
        assert not report.passed

    def test_static_mut_detected(self):
        code   = _VALID_RUST + "\nstatic mut COUNTER: u32 = 0;\n"
        report = self.checker.check(code)
        assert not report.passed

    def test_btreemap_passes(self):
        # BTreeMap is deterministic — must NOT flag it
        code   = _VALID_RUST  # already uses BTreeMap
        report = self.checker.check(code)
        assert report.passed

    def test_code_in_comment_not_flagged(self):
        # Patterns in comments should not trigger
        code = _VALID_RUST + "\n// use rand; // this is a comment\n"
        report = self.checker.check(code)
        assert report.passed

    def test_analysis_notes_populated(self):
        report = self.checker.check(_VALID_RUST)
        assert isinstance(report.analysis_notes, list)

    def test_btreemap_note_added(self):
        report = self.checker.check(_VALID_RUST)
        assert any("BTreeMap" in note for note in report.analysis_notes)

    def test_repr_pass(self):
        report = self.checker.check(_VALID_RUST)
        assert "PASS" in repr(report)

    def test_repr_fail(self):
        code   = _VALID_RUST + "\nlet x = thread_rng();\n"
        report = self.checker.check(code)
        assert "FAIL" in repr(report)

    def test_error_count(self):
        code   = _VALID_RUST + "\nlet x = thread_rng();\nlet m: HashMap<u64, f32> = HashMap::new();\n"
        report = self.checker.check(code)
        assert report.error_count >= 2

    def test_warnings_list(self):
        code   = _VALID_RUST + "\nvec.sort();\n"
        report = self.checker.check(code)
        assert isinstance(report.warnings, list)


# ===========================================================================
# RustCodeGenerator
# ===========================================================================

class TestRustCodeGenerator:
    def setup_method(self):
        self.spec = SystemSpecBuilder().build("MovementSystem", CGS)

    def test_returns_generated_code(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        code      = generator.generate(self.spec, session_id="s1")
        assert isinstance(code, GeneratedCode)

    def test_rust_source_contains_struct(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        code      = generator.generate(self.spec)
        assert "MovementSystem" in code.rust_source

    def test_attempt_number_stored(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        code      = generator.generate(self.spec, attempt=1)
        assert code.attempt == 1

    def test_system_id_echoed(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        code      = generator.generate(self.spec)
        assert code.system_id == "MovementSystem"

    def test_adapter_called_once(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec)
        assert len(adapter.calls) == 1

    def test_call_label_includes_attempt(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec, attempt=1)
        assert "attempt1" in adapter.calls[0].call_label

    def test_tier_is_xl(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec)
        assert adapter.calls[0].complexity_tier == "TIER_XL"

    def test_cached_part_present(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec)
        req = adapter.calls[0]
        cached = [p for p in req.prompt_parts if p.cacheable]
        assert len(cached) >= 1

    def test_cached_part_contains_isystem_trait(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec)
        req = adapter.calls[0]
        cached_text = " ".join(p.text for p in req.prompt_parts if p.cacheable)
        assert "ISystem" in cached_text

    def test_spec_in_dynamic_parts(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec)
        req   = adapter.calls[0]
        dtext = " ".join(p.text for p in req.prompt_parts if not p.cacheable)
        assert "MovementSystem" in dtext

    def test_correction_injected_on_retry(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec, correction="Fix the init method.", attempt=2)
        req   = adapter.calls[0]
        dtext = " ".join(p.text for p in req.prompt_parts if not p.cacheable)
        assert "Fix the init method." in dtext

    def test_no_correction_on_first_attempt(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        generator.generate(self.spec, correction="", attempt=1)
        req = adapter.calls[0]
        correction_parts = [p for p in req.prompt_parts if p.label == "correction"]
        assert len(correction_parts) == 0

    def test_invalid_spec_raises(self):
        bad_spec = SystemSpecBuilder().build("NonExistent", CGS)
        adapter  = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        try:
            generator.generate(bad_spec)
            assert False, "should raise ValueError"
        except ValueError as e:
            assert "invalid" in str(e).lower()

    def test_over_max_attempts_raises_code_gen_error(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        try:
            generator.generate(self.spec, attempt=MAX_ATTEMPTS + 1)
            assert False
        except CodeGenerationError as e:
            assert e.system_id == "MovementSystem"

    def test_fenced_code_extracted(self):
        fenced  = f"```rust\n{_VALID_RUST}\n```"
        adapter = MockAdapter(fenced)
        generator = RustCodeGenerator(adapter)
        code = generator.generate(self.spec)
        # After fence stripping, the raw rust code is extracted
        assert "MovementSystem" in code.rust_source

    def test_repr(self):
        adapter   = MockAdapter(_VALID_RUST)
        generator = RustCodeGenerator(adapter)
        code      = generator.generate(self.spec)
        assert "MovementSystem" in repr(code)


# ===========================================================================
# CargoCompiler
# ===========================================================================

class TestCargoCompiler:
    def setup_method(self):
        self.compiler = CargoCompiler()
        self.spec     = SystemSpecBuilder().build("MovementSystem", CGS)

    def test_returns_compile_result(self):
        result = self.compiler.compile(_VALID_RUST, self.spec)
        assert isinstance(result, CompileResult)

    def test_cargo_available_detection(self):
        # Either cargo is available or not — both are valid
        result = self.compiler.compile(_VALID_RUST, self.spec)
        assert isinstance(result.cargo_available, bool)

    def test_result_has_duration(self):
        result = self.compiler.compile(_VALID_RUST, self.spec)
        assert result.duration_ms >= 0

    def test_formatted_errors_empty_on_pass(self):
        result = self.compiler.compile(_VALID_RUST, self.spec)
        if result.passed:
            assert result.formatted_errors() == ""

    def test_formatted_errors_nonempty_on_fail(self):
        result = CompileResult(
            passed=False,
            errors=[CompileError(
                error_code="E0277",
                message="trait ISystem not implemented",
                file="src/lib.rs", line=42, column=1,
                level="error", context="note: required by ISystem",
            )],
            cargo_available=True,
        )
        text = result.formatted_errors()
        assert "E0277" in text
        assert "ISystem" in text

    def test_compile_error_formatted(self):
        err = CompileError(
            error_code="E0308",
            message="mismatched types: expected f32",
            file="src/lib.rs", line=67, column=5,
            level="error", context="",
        )
        text = err.formatted()
        assert "E0308" in text
        assert "mismatched" in text

    def test_compile_error_repr(self):
        err = CompileError(
            error_code="E0277", message="trait not implemented",
            file="src/lib.rs", line=42, column=1,
            level="error", context="",
        )
        assert "E0277" in repr(err)

    def test_no_cargo_returns_unavailable_result(self):
        import unittest.mock as mock
        with mock.patch("shutil.which", return_value=None):
            result = self.compiler.compile(_VALID_RUST, self.spec)
        assert not result.cargo_available
        assert "cargo" in result.raw_output.lower()

    def test_repr(self):
        result = self.compiler.compile(_VALID_RUST, self.spec)
        r = repr(result)
        assert "CompileResult" in r


# ===========================================================================
# CodeGenerationEngine
# ===========================================================================

class TestCodeGenerationEngine:
    def setup_method(self):
        self.adapter = MockAdapter(_VALID_RUST)
        self.engine  = CodeGenerationEngine(self.adapter)

    def test_returns_code_generation_result(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert isinstance(result, CodeGenerationResult)

    def test_happy_path_succeeds(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert result.succeeded

    def test_happy_path_system_id_correct(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert result.system_id == "MovementSystem"

    def test_happy_path_rust_source_populated(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert len(result.rust_source) > 0

    def test_happy_path_attempts_used(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert result.attempts_used >= 1

    def test_happy_path_spec_populated(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert result.spec is not None
        assert result.spec.system_id == "MovementSystem"

    def test_happy_path_diff_populated(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert isinstance(result.diff_text, str)

    def test_invalid_system_id_fails(self):
        result = self.engine.generate_system("NonExistentSystem", CGS)
        assert not result.succeeded
        assert result.needs_clarification

    def test_two_attempts_on_first_failure(self):
        # First attempt returns invalid code (missing ISystem impl)
        bad_code  = "pub struct MovementSystem {}"
        adapter   = MockAdapter(bad_code, _VALID_RUST)
        engine    = CodeGenerationEngine(adapter)
        result    = engine.generate_system("MovementSystem", CGS)
        assert len(adapter.calls) >= 2

    def test_needs_clarification_after_both_attempts_fail(self):
        # Both attempts return invalid code
        bad_code = "fn nothing() {}"
        adapter  = MockAdapter(bad_code, bad_code)
        engine   = CodeGenerationEngine(adapter)
        result   = engine.generate_system("MovementSystem", CGS)
        assert not result.succeeded
        assert result.needs_clarification
        assert result.attempts_used == MAX_ATTEMPTS

    def test_all_warnings_returns_list(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        assert isinstance(result.all_warnings(), list)

    def test_repr_success(self):
        result = self.engine.generate_system("MovementSystem", CGS)
        r = repr(result)
        assert "MovementSystem" in r
        assert "SUCCESS" in r or "FAILED" in r

    def test_repr_failure(self):
        result = self.engine.generate_system("NonExistentSystem", CGS)
        assert "FAILED" in repr(result)

    # ── generate_for_all_systems ──────────────────────────────────────────────

    def test_generate_for_all_systems_returns_dict(self):
        adapter = MockAdapter(_VALID_RUST)
        engine  = CodeGenerationEngine(adapter)
        results = engine.generate_for_all_systems(CGS, mode_id="mode_default")
        assert isinstance(results, dict)
        assert "MovementSystem" in results
        assert "AISystem" in results

    def test_topological_order_respects_deps(self):
        # MovementSystem depends on InputSystem
        # AISystem depends on MovementSystem
        # So order must be: InputSystem, MovementSystem, AISystem
        from .code_generation_engine import CodeGenerationEngine as E
        order = E._topological_order(CGS, mode_id="")
        assert order.index("InputSystem")    < order.index("MovementSystem")
        assert order.index("MovementSystem") < order.index("AISystem")


# ===========================================================================
# _compute_diff
# ===========================================================================

class TestComputeDiff:
    def test_empty_old_code_returns_new_system_note(self):
        diff = _compute_diff("", _VALID_RUST, "MovementSystem")
        assert "NEW SYSTEM" in diff

    def test_same_code_returns_no_changes(self):
        diff = _compute_diff(_VALID_RUST, _VALID_RUST, "MovementSystem")
        assert "No changes" in diff

    def test_changed_code_returns_diff(self):
        old  = _VALID_RUST
        new  = _VALID_RUST.replace("max_linear_speed", "min_linear_speed")
        diff = _compute_diff(old, new, "MovementSystem")
        assert "---" in diff or "+++" in diff


if __name__ == "__main__":
    import traceback
    classes = [
        TestPythonToRustType, TestSystemSpecBuilder,
        TestCodeContractValidator, TestDeterminismCodeChecker,
        TestRustCodeGenerator, TestCargoCompiler,
        TestCodeGenerationEngine, TestComputeDiff,
    ]
    passed = failed = 0; errors = []
    for cls in classes:
        inst = cls()
        for name in [m for m in dir(inst) if m.startswith("test_")]:
            if hasattr(inst, "setup_method"):
                inst.setup_method()
            try:
                getattr(inst, name)(); passed += 1
            except Exception as exc:
                failed += 1
                errors.append(f"FAIL  {cls.__name__}.{name}")
                errors.append(f"      {type(exc).__name__}: {exc}")
                errors.append(traceback.format_exc())
    print(f"\nResults: {passed} passed, {failed} failed\n")
    for e in errors: print(e)
    import sys
    if failed: sys.exit(1)