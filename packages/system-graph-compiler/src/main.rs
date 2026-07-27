//! XACE System Graph Compiler CLI entry point.
//!
//! Reads system definitions JSON from stdin, compiles them with the real SGC
//! pipeline, and writes an ExecutionPlan JSON document to stdout.

use std::io::{self, Read, Write};
use std::process;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use xace_core::schema::system_definition::{ExecutionPhase, SystemDefinition, SystemVersion};
use xace_system_graph_compiler::compilation_error::CompilationError;
use xace_system_graph_compiler::sgc_pipeline::SgcPipeline;

const EXIT_INVALID_INPUT: i32 = 1;
const EXIT_CYCLE: i32 = 2;
const EXIT_CONFLICT: i32 = 3;
const EXIT_IO: i32 = 4;
const ENGINE_ADAPTER_PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Deserialize)]
struct SgcInput {
    systems: Vec<RawSystemDefinition>,
    #[serde(default = "default_schema_version")]
    schema_version: String,
    #[serde(default = "default_plan_version")]
    plan_version: u32,
    #[serde(default)]
    cgs_hash: String,
}

#[derive(Debug, Deserialize)]
struct RawSystemDefinition {
    id: String,
    #[serde(default)]
    display_name: String,
    phase: Value,
    #[serde(default)]
    reads: Vec<u32>,
    #[serde(default)]
    writes: Vec<u32>,
    #[serde(default)]
    depends_on: Vec<String>,
    #[serde(default = "default_deterministic")]
    deterministic: bool,
    #[serde(default)]
    version: Option<SystemVersion>,
    #[serde(default)]
    version_major: Option<u32>,
    #[serde(default)]
    version_minor: Option<u32>,
    #[serde(default)]
    description: String,
}

fn main() {
    let input = read_stdin_or_exit();
    let parsed = parse_input_or_exit(&input);
    let plan = match SgcPipeline::compile_and_verify_with_identity(
        &parsed.systems,
        &parsed.schema_version,
        parsed.plan_version,
        &parsed.cgs_hash,
        ENGINE_ADAPTER_PROTOCOL_VERSION,
    ) {
        Ok(plan) => plan,
        Err(error) => exit_for_compilation_error(error),
    };

    match serde_json::to_string_pretty(&plan) {
        Ok(json_out) => {
            print!("{}", json_out);
            io::stdout().flush().ok();
            process::exit(0);
        }
        Err(error) => {
            exit_with_error(
                EXIT_IO,
                "SERIALIZE_EXECUTION_PLAN_FAILED",
                "io",
                format!("Failed to serialize ExecutionPlan: {}", error),
                None,
            );
        }
    }
}

#[derive(Debug, Serialize)]
struct SgcCliError {
    schema: &'static str,
    ok: bool,
    code: &'static str,
    category: &'static str,
    message: String,
    exit_code: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    system_id: Option<String>,
}

struct ParsedInput {
    systems: Vec<SystemDefinition>,
    schema_version: String,
    plan_version: u32,
    cgs_hash: String,
}

fn read_stdin_or_exit() -> String {
    let mut input = String::new();
    if let Err(error) = io::stdin().read_to_string(&mut input) {
        exit_with_error(
            EXIT_IO,
            "STDIN_READ_FAILED",
            "io",
            format!("I/O error reading stdin: {}", error),
            None,
        );
    }
    if input.trim().is_empty() {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "EMPTY_INPUT",
            "invalid_input",
            "Empty input: expected JSON envelope with a 'systems' array.",
            None,
        );
    }
    input
}

fn parse_input_or_exit(input: &str) -> ParsedInput {
    let envelope: SgcInput = match serde_json::from_str(input) {
        Ok(value) => value,
        Err(error) => {
            exit_with_error(
                EXIT_INVALID_INPUT,
                "JSON_PARSE_ERROR",
                "invalid_input",
                format!("JSON parse error: {}", error),
                None,
            );
        }
    };

    if envelope.schema_version.trim().is_empty() {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "EMPTY_SCHEMA_VERSION",
            "invalid_input",
            "schema_version must not be empty.",
            None,
        );
    }
    if envelope.plan_version == 0 {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "INVALID_PLAN_VERSION",
            "invalid_input",
            "plan_version must be >= 1.",
            None,
        );
    }

    let mut systems = Vec::with_capacity(envelope.systems.len());
    for raw in envelope.systems {
        let system = normalize_system_or_exit(raw);
        if let Err(reason) = system.validate() {
            exit_with_error(
                EXIT_INVALID_INPUT,
                "INVALID_SYSTEM_DEFINITION",
                "invalid_input",
                format!("Invalid system definition '{}': {}", system.id, reason),
                Some(system.id.clone()),
            );
        }
        systems.push(system);
    }

    ParsedInput {
        systems,
        schema_version: envelope.schema_version,
        plan_version: envelope.plan_version,
        cgs_hash: normalize_cgs_hash_or_exit(envelope.cgs_hash),
    }
}

fn normalize_system_or_exit(raw: RawSystemDefinition) -> SystemDefinition {
    let id = raw.id.trim().to_string();
    if id.is_empty() {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "EMPTY_SYSTEM_ID",
            "invalid_input",
            "SystemDefinition.id must not be empty.",
            None,
        );
    }

    let phase = parse_phase_or_exit(&id, raw.phase);
    let version = raw.version.unwrap_or_else(|| {
        SystemVersion::new(
            raw.version_major.unwrap_or(1),
            raw.version_minor.unwrap_or(0),
        )
    });
    let display_name = if raw.display_name.trim().is_empty() {
        id.clone()
    } else {
        raw.display_name
    };

    let mut reads = raw.reads;
    reads.sort_unstable();
    reads.dedup();
    let mut writes = raw.writes;
    writes.sort_unstable();
    writes.dedup();
    let mut depends_on = raw.depends_on;
    depends_on.sort();
    depends_on.dedup();

    SystemDefinition {
        id,
        display_name,
        phase,
        reads,
        writes,
        depends_on,
        deterministic: raw.deterministic,
        version,
        description: raw.description,
    }
}

fn parse_phase_or_exit(system_id: &str, value: Value) -> ExecutionPhase {
    if let Some(number) = value.as_u64() {
        if let Some(phase) = ExecutionPhase::from_u8(number as u8) {
            return phase;
        }
    }
    if let Some(raw) = value.as_str() {
        let normalized = raw.trim().replace(['-', '_', ' '], "").to_ascii_lowercase();
        return match normalized.as_str() {
            "initialization" | "init" => ExecutionPhase::Initialization,
            "input" => ExecutionPhase::Input,
            "simulation" | "sim" => ExecutionPhase::Simulation,
            "postsimulation" | "postsim" | "post" => ExecutionPhase::PostSimulation,
            "cleanup" => ExecutionPhase::Cleanup,
            _ => {
                exit_with_error(
                    EXIT_INVALID_INPUT,
                    "INVALID_PHASE",
                    "invalid_input",
                    format!(
                        "Invalid phase for system '{}': '{}'. Valid phases: Initialization, Input, Simulation, PostSimulation, Cleanup.",
                        system_id, raw
                    ),
                    Some(system_id.to_string()),
                );
            }
        };
    }
    exit_with_error(
        EXIT_INVALID_INPUT,
        "INVALID_PHASE_TYPE",
        "invalid_input",
        format!(
            "Invalid phase for system '{}': expected string or phase ordinal.",
            system_id
        ),
        Some(system_id.to_string()),
    );
}

fn exit_for_compilation_error(error: CompilationError) -> ! {
    if error.is_cycle() {
        exit_with_error(
            EXIT_CYCLE,
            "CYCLE_DETECTED",
            "cycle",
            error.to_string(),
            None,
        );
    }
    if error.is_conflict() {
        exit_with_error(
            EXIT_CONFLICT,
            "CONFLICT_DETECTED",
            "conflict",
            error.to_string(),
            None,
        );
    }
    if matches!(error, CompilationError::InvalidDefinition(_)) {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "INVALID_SYSTEM_DEFINITION",
            "invalid_input",
            error.to_string(),
            None,
        );
    }
    if error.is_phase() {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "PHASE_VIOLATION",
            "invalid_input",
            error.to_string(),
            None,
        );
    }
    exit_with_error(
        EXIT_INVALID_INPUT,
        "COMPILATION_FAILED",
        "invalid_input",
        error.to_string(),
        None,
    );
}

fn exit_with_error(
    exit_code: i32,
    code: &'static str,
    category: &'static str,
    message: impl Into<String>,
    system_id: Option<String>,
) -> ! {
    let error = SgcCliError {
        schema: "xace.sgc.cli.error.v1",
        ok: false,
        code,
        category,
        message: message.into(),
        exit_code,
        system_id,
    };
    let encoded = serde_json::to_string_pretty(&error).unwrap_or_else(|_| {
        format!(
            r#"{{"schema":"xace.sgc.cli.error.v1","ok":false,"code":"{}","category":"{}","message":"SGC failed before error serialization","exit_code":{}}}"#,
            code, category, exit_code
        )
    });
    eprintln!("{}", encoded);
    process::exit(exit_code);
}

fn normalize_cgs_hash_or_exit(raw: String) -> String {
    let trimmed = raw.trim();
    if trimmed.len() != 64
        || !trimmed
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        exit_with_error(
            EXIT_INVALID_INPUT,
            "INVALID_CGS_HASH",
            "invalid_input",
            "cgs_hash must be a lowercase 64-character SHA-256 digest.",
            None,
        );
    }
    trimmed.to_string()
}

fn default_schema_version() -> String {
    "0.1.0".to_string()
}

fn default_plan_version() -> u32 {
    1
}

fn default_deterministic() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_CGS_HASH_A: &str =
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const TEST_CGS_HASH_B: &str =
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

    #[test]
    fn parses_legacy_builder_input_shape() {
        let input = format!(
            r#"{{
                "schema_version": "0.2.0",
                "plan_version": 7,
                "cgs_hash": "{TEST_CGS_HASH_A}",
                "systems": [
                    {{
                        "id": "MovementSystem",
                        "phase": "Simulation",
                        "reads": [6, 1, 1],
                        "writes": [5],
                        "depends_on": ["InputSystem", "InputSystem"],
                        "deterministic": true,
                        "version_major": 2,
                        "version_minor": 3
                    }}
                ]
            }}"#
        );
        let parsed = parse_input_or_exit(&input);

        assert_eq!(parsed.schema_version, "0.2.0");
        assert_eq!(parsed.plan_version, 7);
        assert_eq!(parsed.cgs_hash, TEST_CGS_HASH_A);
        assert_eq!(parsed.systems.len(), 1);
        let system = &parsed.systems[0];
        assert_eq!(system.id, "MovementSystem");
        assert_eq!(system.display_name, "MovementSystem");
        assert_eq!(system.phase, ExecutionPhase::Simulation);
        assert_eq!(system.reads, vec![1, 6]);
        assert_eq!(system.writes, vec![5]);
        assert_eq!(system.depends_on, vec!["InputSystem"]);
        assert_eq!(system.version, SystemVersion::new(2, 3));
    }

    #[test]
    fn parsed_input_compiles_through_real_pipeline() {
        let input = format!(
            r#"{{
                "schema_version": "0.1.0",
                "plan_version": 1,
                "cgs_hash": "{TEST_CGS_HASH_B}",
                "systems": [
                    {{
                        "id": "InputSystem",
                        "phase": "Input",
                        "reads": [6],
                        "writes": [5]
                    }},
                    {{
                        "id": "MovementSystem",
                        "phase": "Simulation",
                        "reads": [5],
                        "writes": [1],
                        "depends_on": ["InputSystem"]
                    }}
                ]
            }}"#
        );
        let parsed = parse_input_or_exit(&input);

        let plan = SgcPipeline::compile_and_verify_with_identity(
            &parsed.systems,
            &parsed.schema_version,
            parsed.plan_version,
            &parsed.cgs_hash,
            ENGINE_ADAPTER_PROTOCOL_VERSION,
        )
        .unwrap();

        assert_eq!(plan.schema_version, "0.1.0");
        assert_eq!(plan.plan_version, 1);
        assert_eq!(plan.compiled_from_cgs_hash, TEST_CGS_HASH_B);
        assert_eq!(
            plan.adapter_protocol_version,
            ENGINE_ADAPTER_PROTOCOL_VERSION
        );
        assert_eq!(plan.migration_status, "current");
        assert_eq!(
            plan.component_access_sets
                .by_system
                .get("MovementSystem")
                .unwrap()
                .reads,
            vec![5]
        );
        assert_eq!(
            plan.system_metadata
                .systems
                .get("MovementSystem")
                .unwrap()
                .depends_on,
            vec!["InputSystem"]
        );
        assert_eq!(plan.proof_bundle.compiled_from_cgs_hash, TEST_CGS_HASH_B);
        assert_eq!(plan.proof_bundle.plan_hash, plan.plan_hash);
        assert_eq!(plan.total_system_count(), 2);
        assert!(plan.contains_system("InputSystem"));
        assert!(plan.contains_system("MovementSystem"));
    }

    #[test]
    fn identical_input_serializes_byte_for_byte_identically() {
        let input = format!(
            r#"{{
                "schema_version": "0.1.0",
                "plan_version": 1,
                "cgs_hash": "{TEST_CGS_HASH_A}",
                "systems": [
                    {{
                        "id": "InputSystem",
                        "phase": "Input",
                        "reads": [6],
                        "writes": [5]
                    }},
                    {{
                        "id": "MovementSystem",
                        "phase": "Simulation",
                        "reads": [5],
                        "writes": [1],
                        "depends_on": ["InputSystem"]
                    }}
                ]
            }}"#
        );
        let first = parse_input_or_exit(&input);
        let second = parse_input_or_exit(&input);

        let first_plan = SgcPipeline::compile_and_verify_with_identity(
            &first.systems,
            &first.schema_version,
            first.plan_version,
            &first.cgs_hash,
            ENGINE_ADAPTER_PROTOCOL_VERSION,
        )
        .unwrap();
        let second_plan = SgcPipeline::compile_and_verify_with_identity(
            &second.systems,
            &second.schema_version,
            second.plan_version,
            &second.cgs_hash,
            ENGINE_ADAPTER_PROTOCOL_VERSION,
        )
        .unwrap();
        let first_json = serde_json::to_string_pretty(&first_plan).unwrap();
        let second_json = serde_json::to_string_pretty(&second_plan).unwrap();

        assert_eq!(first_plan.plan_hash, second_plan.plan_hash);
        assert_eq!(first_json, second_json);
    }
}
