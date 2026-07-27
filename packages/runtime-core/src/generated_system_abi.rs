//! Deterministic ABI for generated gameplay systems.
//!
//! Generated systems are not allowed to call runtime internals directly. The
//! runtime accepts a small declarative executor contract, normalizes it into a
//! `GeneratedSystemAbiSpec`, and executes it only through `SystemContext`.
//! This keeps reads, writes, events, RNG, errors, and rollback behavior visible
//! before the system is registered.

use std::collections::BTreeMap;

use crate::fixed_json::{fixed_from_json, fixed_value, IntegerEncoding};
use anyhow::Result;
use serde_json::Value;
use sha2::{Digest, Sha256};
use xace_core::contracts::interfaces::{ISystem, ISystemContext};
use xace_core::errors::xace_error::{ErrorContext, XaceError};
use xace_core::events::event_struct::Event;
use xace_core::events::event_type::EventType;
use xace_core::fixed_point::Fixed64;
use xace_core::runtime::phase_enum::PhaseEnum;

pub const GENERATED_SYSTEM_ABI_SCHEMA: &str = "xace.generated_system_abi.v1";
pub const RUNTIME_EXECUTOR_ABI_SCHEMA: &str = "xace.runtime_executor_abi.v1";
pub const GENERATED_SYSTEM_ABI_VERSION: u32 = 1;
pub const GENERATED_SYSTEM_COMPILE_ARTIFACT_SCHEMA: &str =
    "xace.generated_system_compile_artifact.v1";
pub const GENERATED_SYSTEM_COMPILE_ARTIFACT_SIGNING_KEY_ID: &str = "xace-local-generated-system-v1";
pub const GENERATED_SYSTEM_UNSUPPORTED_POLICY_HASH: &str =
    "3306f82262ec3e951b9d8d7de53dac45f3e69fac8b6b00d0959c89877c5e47c5";
pub const GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND: &str =
    "generated.increment_numeric_field";
pub const GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND: &str =
    "generated.emit_event_on_rng_threshold";
pub const PLUGIN_SET_JSON_FIELD_EXECUTOR_KIND: &str = "plugin.set_json_field";
pub const PLUGIN_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND: &str = "plugin.increment_numeric_field";
pub const EXTERNAL_COPY_NUMERIC_FIELD_EXECUTOR_KIND: &str = "external.copy_numeric_field";
pub const EXTERNAL_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND: &str = "external.increment_numeric_field";
const GENERATED_SYSTEM_COMPILE_ARTIFACT_STEPS: [&str; 9] = [
    "system_spec_validation",
    "runtime_abi_validation",
    "unsupported_api_rejection",
    "code_contract_validation",
    "determinism_static_check",
    "cargo_check_sandbox",
    "sgc_compile",
    "artifact_signature",
    "runtime_registration",
];

#[derive(Debug, Clone, PartialEq)]
pub struct GeneratedSystemAbiSpec {
    pub system_id: String,
    pub kind: String,
    pub source: RuntimeExecutorSource,
    pub phase: PhaseEnum,
    pub abi_version: u32,
    pub reads: Vec<u32>,
    pub writes: Vec<u32>,
    pub inputs: GeneratedSystemInputs,
    pub events: GeneratedSystemEvents,
    pub rng: GeneratedSystemRng,
    pub errors: GeneratedSystemErrors,
    pub rollback: GeneratedSystemRollbackHooks,
    pub operation: GeneratedSystemOperation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeExecutorSource {
    Generated,
    Plugin,
    External,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedSystemInputs {
    pub query_components: Vec<u32>,
    pub component_reads: Vec<u32>,
    pub current_tick: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedSystemEvents {
    pub emits: Vec<GeneratedEventDeclaration>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedEventDeclaration {
    pub event_type: String,
    pub broadcast: bool,
    pub payload: BTreeMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedSystemRng {
    pub allowed: bool,
    pub max_calls_per_entity: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedSystemErrors {
    pub policy: GeneratedErrorPolicy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GeneratedErrorPolicy {
    HaltAndRollback,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GeneratedSystemRollbackHooks {
    pub mutation_hook: GeneratedRollbackHook,
    pub event_hook: GeneratedRollbackHook,
    pub rng_hook: GeneratedRollbackHook,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GeneratedRollbackHook {
    MutationGateDeferred,
    EventBusPhaseBuffered,
    RngWindowed,
}

#[derive(Debug, Clone, PartialEq)]
pub enum GeneratedSystemOperation {
    IncrementNumericField {
        component_type_id: u32,
        field: String,
        amount: Fixed64,
    },
    SetJsonField {
        component_type_id: u32,
        field: String,
        value: Value,
    },
    CopyNumericField {
        source_component_type_id: u32,
        source_field: String,
        target_component_type_id: u32,
        target_field: String,
        scale: Fixed64,
        offset: Fixed64,
    },
    EmitEventOnRngThreshold {
        component_type_id: u32,
        chance: Fixed64,
        event_type: String,
        payload: BTreeMap<String, String>,
    },
}

pub fn spec_from_runtime_executor(
    system_id: &str,
    phase: &str,
    reads: &[u32],
    writes: &[u32],
    runtime_executor: &Value,
) -> Result<Option<GeneratedSystemAbiSpec>> {
    if runtime_executor.is_null() {
        return Ok(None);
    }

    let system_id = system_id.trim();
    let executor = runtime_executor.as_object().ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor must be an object",
            system_id
        )
    })?;
    let kind = executor
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    if kind.is_empty() {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.kind is required",
            system_id
        );
    }

    let source = runtime_executor_source_for_kind(kind)?;
    let phase = parse_phase(phase)?;
    let reads = sorted_unique_u32(reads);
    let writes = sorted_unique_u32(writes);
    let operation = parse_operation(system_id, kind, executor, &reads, &writes)?;
    let mut spec =
        default_abi_for_operation(system_id, kind, source, phase, reads, writes, operation);
    if let Some(abi) = executor.get("abi") {
        validate_explicit_abi(&spec, abi)?;
    }
    if let Some(compile_artifact) = executor.get("compile_artifact") {
        validate_compile_artifact(&spec, executor, compile_artifact)?;
    }
    spec.abi_version = GENERATED_SYSTEM_ABI_VERSION;
    Ok(Some(spec))
}

pub fn build_generated_runtime_system(spec: GeneratedSystemAbiSpec) -> Box<dyn ISystem> {
    Box::new(GeneratedRuntimeSystem { spec })
}

struct GeneratedRuntimeSystem {
    spec: GeneratedSystemAbiSpec,
}

impl GeneratedRuntimeSystem {
    fn validation_error(&self, operation: &str, message: String, failed_path: String) -> XaceError {
        generated_validation_error(&self.spec.system_id, operation, message, failed_path)
    }

    fn execute_increment(
        &self,
        context: &mut dyn ISystemContext,
        component_type_id: u32,
        field: &str,
        amount: Fixed64,
    ) -> std::result::Result<(), XaceError> {
        let mut prepared = Vec::new();
        for entity_id in context.query_entities(&[component_type_id])? {
            let Some(component_json) = context.get_component(entity_id, component_type_id)? else {
                continue;
            };
            let updated =
                self.increment_component_json(component_json, component_type_id, field, amount)?;
            prepared.push((entity_id, updated));
        }

        for (entity_id, component_json) in prepared {
            context.submit_mutation(entity_id, component_type_id, component_json)?;
        }
        Ok(())
    }

    fn increment_component_json(
        &self,
        component_json: &str,
        component_type_id: u32,
        field: &str,
        amount: Fixed64,
    ) -> std::result::Result<String, XaceError> {
        let mut component = serde_json::from_str::<Value>(component_json).map_err(|err| {
            self.validation_error(
                "execute",
                format!(
                    "Generated system '{}' could not parse component {} JSON: {}",
                    self.spec.system_id, component_type_id, err
                ),
                format!("component:{}", component_type_id),
            )
        })?;
        let object = component.as_object_mut().ok_or_else(|| {
            self.validation_error(
                "execute",
                format!(
                    "Generated system '{}' requires component {} to be a JSON object",
                    self.spec.system_id, component_type_id
                ),
                format!("component:{}", component_type_id),
            )
        })?;
        let current = match object.get(field) {
            Some(value) => fixed_from_json(value, IntegerEncoding::RawMicroUnits).ok_or_else(|| {
                self.validation_error(
                    "execute",
                    format!(
                        "Generated system '{}' requires field '{}' on component {} to be fixed-point numeric",
                        self.spec.system_id, field, component_type_id
                    ),
                    format!("component:{}.{}", component_type_id, field),
                )
            })?,
            None => Fixed64::ZERO,
        };
        object.insert(field.to_string(), fixed_value(current + amount));
        Ok(component.to_string())
    }

    fn execute_set_json_field(
        &self,
        context: &mut dyn ISystemContext,
        component_type_id: u32,
        field: &str,
        value: &Value,
    ) -> std::result::Result<(), XaceError> {
        let mut prepared = Vec::new();
        for entity_id in context.query_entities(&[component_type_id])? {
            let Some(component_json) = context.get_component(entity_id, component_type_id)? else {
                continue;
            };
            let mut component =
                parse_component_object(&self.spec.system_id, component_type_id, component_json)?;
            let Some(object) = component.as_object_mut() else {
                return Err(self.validation_error(
                    "execute",
                    format!(
                        "Runtime executor system '{}' requires component {} to be a JSON object",
                        self.spec.system_id, component_type_id
                    ),
                    format!("component:{}", component_type_id),
                ));
            };
            object.insert(field.to_string(), value.clone());
            prepared.push((entity_id, component.to_string()));
        }

        for (entity_id, component_json) in prepared {
            context.submit_mutation(entity_id, component_type_id, component_json)?;
        }
        Ok(())
    }

    fn execute_copy_numeric_field(
        &self,
        context: &mut dyn ISystemContext,
        source_component_type_id: u32,
        source_field: &str,
        target_component_type_id: u32,
        target_field: &str,
        scale: Fixed64,
        offset: Fixed64,
    ) -> std::result::Result<(), XaceError> {
        let mut prepared = Vec::new();
        for entity_id in
            context.query_entities(&[source_component_type_id, target_component_type_id])?
        {
            let Some(source_json) = context.get_component(entity_id, source_component_type_id)?
            else {
                continue;
            };
            let Some(target_json) = context.get_component(entity_id, target_component_type_id)?
            else {
                continue;
            };
            let source = parse_component_object(
                &self.spec.system_id,
                source_component_type_id,
                source_json,
            )?;
            let source_number = source
                .get(source_field)
                .and_then(|value| fixed_from_json(value, IntegerEncoding::RawMicroUnits))
                .ok_or_else(|| {
                    self.validation_error(
                        "execute",
                        format!(
                            "Runtime executor system '{}' requires field '{}' on component {} to be fixed-point numeric",
                            self.spec.system_id, source_field, source_component_type_id
                        ),
                        format!("component:{}.{}", source_component_type_id, source_field),
                    )
                })?;
            let mut target = parse_component_object(
                &self.spec.system_id,
                target_component_type_id,
                target_json,
            )?;
            let Some(object) = target.as_object_mut() else {
                return Err(self.validation_error(
                    "execute",
                    format!(
                        "Runtime executor system '{}' requires component {} to be a JSON object",
                        self.spec.system_id, target_component_type_id
                    ),
                    format!("component:{}", target_component_type_id),
                ));
            };
            object.insert(
                target_field.to_string(),
                fixed_value(source_number * scale + offset),
            );
            prepared.push((entity_id, target.to_string()));
        }

        for (entity_id, component_json) in prepared {
            context.submit_mutation(entity_id, target_component_type_id, component_json)?;
        }
        Ok(())
    }

    fn execute_rng_event(
        &self,
        context: &mut dyn ISystemContext,
        component_type_id: u32,
        chance: Fixed64,
        event_type: &str,
        payload: &BTreeMap<String, String>,
    ) -> std::result::Result<(), XaceError> {
        let mut prepared = Vec::new();
        for entity_id in context.query_entities(&[component_type_id])? {
            let Some(component_json) = context.get_component(entity_id, component_type_id)? else {
                continue;
            };
            validate_json_object(&self.spec.system_id, component_type_id, component_json)?;
            let draw = context.next_random()?;
            if draw < chance {
                let mut event = Event::broadcast(
                    entity_id,
                    parse_event_type(event_type),
                    context.current_tick(),
                    self.spec.phase,
                );
                event.payload = payload.clone();
                prepared.push(event);
            }
        }

        for event in prepared {
            context.emit_event(event)?;
        }
        Ok(())
    }
}

impl ISystem for GeneratedRuntimeSystem {
    fn system_id(&self) -> &str {
        &self.spec.system_id
    }

    fn execute(&self, context: &mut dyn ISystemContext) -> std::result::Result<(), XaceError> {
        match &self.spec.operation {
            GeneratedSystemOperation::IncrementNumericField {
                component_type_id,
                field,
                amount,
            } => self.execute_increment(context, *component_type_id, field, *amount),
            GeneratedSystemOperation::SetJsonField {
                component_type_id,
                field,
                value,
            } => self.execute_set_json_field(context, *component_type_id, field, value),
            GeneratedSystemOperation::CopyNumericField {
                source_component_type_id,
                source_field,
                target_component_type_id,
                target_field,
                scale,
                offset,
            } => self.execute_copy_numeric_field(
                context,
                *source_component_type_id,
                source_field,
                *target_component_type_id,
                target_field,
                *scale,
                *offset,
            ),
            GeneratedSystemOperation::EmitEventOnRngThreshold {
                component_type_id,
                chance,
                event_type,
                payload,
            } => self.execute_rng_event(context, *component_type_id, *chance, event_type, payload),
        }
    }

    fn declared_reads(&self) -> &[u32] {
        &self.spec.reads
    }

    fn declared_writes(&self) -> &[u32] {
        &self.spec.writes
    }
}

fn parse_operation(
    system_id: &str,
    kind: &str,
    executor: &serde_json::Map<String, Value>,
    reads: &[u32],
    writes: &[u32],
) -> Result<GeneratedSystemOperation> {
    match kind {
        GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND
        | PLUGIN_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND
        | EXTERNAL_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND => {
            let component_type_id =
                runtime_executor_component_type_id(executor.get("component_type_id"), system_id)?;
            let field = required_field_name(executor.get("field"), system_id)?;
            let amount = fixed_number(executor.get("amount"), system_id, "amount")?;
            require_component_access(system_id, component_type_id, reads, writes, true)?;
            Ok(GeneratedSystemOperation::IncrementNumericField {
                component_type_id,
                field,
                amount,
            })
        }
        PLUGIN_SET_JSON_FIELD_EXECUTOR_KIND => {
            let component_type_id =
                runtime_executor_component_type_id(executor.get("component_type_id"), system_id)?;
            let field = required_field_name(executor.get("field"), system_id)?;
            let value = scalar_json_value(executor.get("value"), system_id, "value")?;
            require_component_access(system_id, component_type_id, reads, writes, true)?;
            Ok(GeneratedSystemOperation::SetJsonField {
                component_type_id,
                field,
                value,
            })
        }
        EXTERNAL_COPY_NUMERIC_FIELD_EXECUTOR_KIND => {
            let source_component_type_id = required_u32(
                executor.get("source_component_type_id"),
                system_id,
                "source_component_type_id",
            )?;
            let source_field = required_field_name(executor.get("source_field"), system_id)?;
            let target_component_type_id = required_u32(
                executor.get("target_component_type_id"),
                system_id,
                "target_component_type_id",
            )?;
            let target_field = required_field_name(executor.get("target_field"), system_id)?;
            let scale =
                fixed_number_or_default(executor.get("scale"), system_id, "scale", Fixed64::ONE)?;
            let offset = fixed_number_or_default(
                executor.get("offset"),
                system_id,
                "offset",
                Fixed64::ZERO,
            )?;
            require_component_read(system_id, source_component_type_id, reads)?;
            require_component_read(system_id, target_component_type_id, reads)?;
            require_component_write(system_id, target_component_type_id, writes)?;
            Ok(GeneratedSystemOperation::CopyNumericField {
                source_component_type_id,
                source_field,
                target_component_type_id,
                target_field,
                scale,
                offset,
            })
        }
        GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND => {
            let component_type_id =
                runtime_executor_component_type_id(executor.get("component_type_id"), system_id)?;
            let chance = fixed_number(executor.get("chance"), system_id, "chance")?;
            if chance < Fixed64::ZERO || chance > Fixed64::ONE {
                anyhow::bail!(
                    "CGS system '{}' runtime_executor.chance must be between 0 and 1",
                    system_id
                );
            }
            require_component_access(system_id, component_type_id, reads, writes, false)?;
            let event_type = executor
                .get("event_type")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .trim()
                .to_string();
            if event_type.is_empty() {
                anyhow::bail!(
                    "CGS system '{}' runtime_executor.event_type is required",
                    system_id
                );
            }
            let payload = parse_payload(executor.get("payload"), system_id)?;
            Ok(GeneratedSystemOperation::EmitEventOnRngThreshold {
                component_type_id,
                chance,
                event_type,
                payload,
            })
        }
        other => anyhow::bail!(
            "CGS system '{}' runtime_executor.kind '{}' is not supported by this runtime",
            system_id,
            other
        ),
    }
}

fn runtime_executor_source_for_kind(kind: &str) -> Result<RuntimeExecutorSource> {
    if kind.starts_with("generated.") {
        return Ok(RuntimeExecutorSource::Generated);
    }
    if kind.starts_with("plugin.") {
        return Ok(RuntimeExecutorSource::Plugin);
    }
    if kind.starts_with("external.") {
        return Ok(RuntimeExecutorSource::External);
    }
    anyhow::bail!(
        "runtime_executor.kind '{}' must start with generated., plugin., or external.",
        kind
    )
}

fn default_abi_for_operation(
    system_id: &str,
    kind: &str,
    source: RuntimeExecutorSource,
    phase: PhaseEnum,
    reads: Vec<u32>,
    writes: Vec<u32>,
    operation: GeneratedSystemOperation,
) -> GeneratedSystemAbiSpec {
    let (inputs, events, rng) = match &operation {
        GeneratedSystemOperation::IncrementNumericField {
            component_type_id, ..
        } => (
            GeneratedSystemInputs {
                query_components: vec![*component_type_id],
                component_reads: vec![*component_type_id],
                current_tick: false,
            },
            GeneratedSystemEvents { emits: Vec::new() },
            GeneratedSystemRng {
                allowed: false,
                max_calls_per_entity: 0,
            },
        ),
        GeneratedSystemOperation::SetJsonField {
            component_type_id, ..
        } => (
            GeneratedSystemInputs {
                query_components: vec![*component_type_id],
                component_reads: vec![*component_type_id],
                current_tick: false,
            },
            GeneratedSystemEvents { emits: Vec::new() },
            GeneratedSystemRng {
                allowed: false,
                max_calls_per_entity: 0,
            },
        ),
        GeneratedSystemOperation::CopyNumericField {
            source_component_type_id,
            target_component_type_id,
            ..
        } => (
            GeneratedSystemInputs {
                query_components: sorted_unique_u32(&[
                    *source_component_type_id,
                    *target_component_type_id,
                ]),
                component_reads: sorted_unique_u32(&[
                    *source_component_type_id,
                    *target_component_type_id,
                ]),
                current_tick: false,
            },
            GeneratedSystemEvents { emits: Vec::new() },
            GeneratedSystemRng {
                allowed: false,
                max_calls_per_entity: 0,
            },
        ),
        GeneratedSystemOperation::EmitEventOnRngThreshold {
            component_type_id,
            event_type,
            payload,
            ..
        } => (
            GeneratedSystemInputs {
                query_components: vec![*component_type_id],
                component_reads: vec![*component_type_id],
                current_tick: true,
            },
            GeneratedSystemEvents {
                emits: vec![GeneratedEventDeclaration {
                    event_type: event_type.clone(),
                    broadcast: true,
                    payload: payload.clone(),
                }],
            },
            GeneratedSystemRng {
                allowed: true,
                max_calls_per_entity: 1,
            },
        ),
    };

    GeneratedSystemAbiSpec {
        system_id: system_id.to_string(),
        kind: kind.to_string(),
        source,
        phase,
        abi_version: GENERATED_SYSTEM_ABI_VERSION,
        reads,
        writes,
        inputs,
        events,
        rng,
        errors: GeneratedSystemErrors {
            policy: GeneratedErrorPolicy::HaltAndRollback,
        },
        rollback: GeneratedSystemRollbackHooks {
            mutation_hook: GeneratedRollbackHook::MutationGateDeferred,
            event_hook: GeneratedRollbackHook::EventBusPhaseBuffered,
            rng_hook: GeneratedRollbackHook::RngWindowed,
        },
        operation,
    }
}

fn validate_explicit_abi(spec: &GeneratedSystemAbiSpec, abi: &Value) -> Result<()> {
    let abi = abi.as_object().ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor.abi must be an object",
            spec.system_id
        )
    })?;
    let schema = abi
        .get("schema")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if schema != GENERATED_SYSTEM_ABI_SCHEMA && schema != RUNTIME_EXECUTOR_ABI_SCHEMA {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.schema must be '{}' or '{}'",
            spec.system_id,
            GENERATED_SYSTEM_ABI_SCHEMA,
            RUNTIME_EXECUTOR_ABI_SCHEMA
        );
    }
    let version = abi.get("version").and_then(Value::as_u64).unwrap_or(0);
    if version != GENERATED_SYSTEM_ABI_VERSION as u64 {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.version must be {}",
            spec.system_id,
            GENERATED_SYSTEM_ABI_VERSION
        );
    }

    let inputs = required_object(abi, "inputs", &spec.system_id)?;
    let query_components = required_u32_array(inputs, "query_components", &spec.system_id)?;
    let component_reads = required_u32_array(inputs, "component_reads", &spec.system_id)?;
    let current_tick = required_bool(inputs, "current_tick", &spec.system_id)?;
    if query_components != spec.inputs.query_components {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.inputs.query_components does not match executor inputs",
            spec.system_id
        );
    }
    if component_reads != spec.inputs.component_reads {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.inputs.component_reads does not match executor reads",
            spec.system_id
        );
    }
    if current_tick != spec.inputs.current_tick {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.inputs.current_tick does not match executor tick usage",
            spec.system_id
        );
    }

    let rng = required_object(abi, "rng", &spec.system_id)?;
    let rng_allowed = required_bool(rng, "allowed", &spec.system_id)?;
    let max_calls = required_u32_allow_zero(
        rng.get("max_calls_per_entity"),
        &spec.system_id,
        "rng.max_calls_per_entity",
    )?;
    if rng_allowed != spec.rng.allowed || max_calls != spec.rng.max_calls_per_entity {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.rng does not match executor RNG usage",
            spec.system_id
        );
    }

    validate_explicit_events(spec, required_object(abi, "events", &spec.system_id)?)?;

    let errors = required_object(abi, "errors", &spec.system_id)?;
    let error_policy = errors
        .get("policy")
        .and_then(Value::as_str)
        .unwrap_or_default();
    if error_policy != "halt_and_rollback" {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.errors.policy must be 'halt_and_rollback'",
            spec.system_id
        );
    }

    let rollback = required_object(abi, "rollback", &spec.system_id)?;
    require_string_value(
        rollback,
        "mutation_hook",
        "mutation_gate_deferred",
        &spec.system_id,
    )?;
    require_string_value(
        rollback,
        "event_hook",
        "event_bus_phase_buffered",
        &spec.system_id,
    )?;
    require_string_value(rollback, "rng_hook", "rng_windowed", &spec.system_id)?;
    Ok(())
}

fn validate_compile_artifact(
    spec: &GeneratedSystemAbiSpec,
    executor: &serde_json::Map<String, Value>,
    compile_artifact: &Value,
) -> Result<()> {
    let artifact = compile_artifact.as_object().ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor.compile_artifact must be an object",
            spec.system_id
        )
    })?;
    require_artifact_string(
        artifact,
        "schema",
        GENERATED_SYSTEM_COMPILE_ARTIFACT_SCHEMA,
        &spec.system_id,
    )?;
    require_artifact_string(artifact, "system_id", &spec.system_id, &spec.system_id)?;
    require_artifact_string(
        artifact,
        "signing_key_id",
        GENERATED_SYSTEM_COMPILE_ARTIFACT_SIGNING_KEY_ID,
        &spec.system_id,
    )?;

    for field in [
        "cgs_hash",
        "source_hash",
        "runtime_executor_hash",
        "abi_hash",
        "sgc_plan_hash",
        "unsupported_policy_hash",
        "sandbox_hash",
        "signature",
    ] {
        let value = required_artifact_str(artifact, field, &spec.system_id)?;
        if !is_lower_hex_64(value) {
            anyhow::bail!(
                "CGS system '{}' runtime_executor.compile_artifact.{} must be a lowercase 64-character SHA-256 digest",
                spec.system_id,
                field
            );
        }
    }

    let steps = artifact
        .get("validation_steps")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            anyhow::anyhow!(
                "CGS system '{}' runtime_executor.compile_artifact.validation_steps must be an array",
                spec.system_id
            )
        })?;
    let parsed_steps = steps
        .iter()
        .map(|step| step.as_str().unwrap_or_default())
        .collect::<Vec<_>>();
    if parsed_steps != GENERATED_SYSTEM_COMPILE_ARTIFACT_STEPS {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.validation_steps does not match the required safe-compile gate order",
            spec.system_id
        );
    }

    let expected_abi_hash = match executor.get("abi") {
        Some(abi) => stable_json_hash(abi)?,
        None => anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact requires an explicit runtime_executor.abi block",
            spec.system_id
        ),
    };
    let actual_abi_hash = required_artifact_str(artifact, "abi_hash", &spec.system_id)?;
    if actual_abi_hash != expected_abi_hash {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.abi_hash does not match runtime_executor.abi",
            spec.system_id
        );
    }

    let expected_executor_hash = runtime_executor_hash_without_artifact(executor)?;
    let actual_executor_hash =
        required_artifact_str(artifact, "runtime_executor_hash", &spec.system_id)?;
    if actual_executor_hash != expected_executor_hash {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.runtime_executor_hash does not match runtime_executor",
            spec.system_id
        );
    }

    let expected_signature = compile_artifact_signature(artifact)?;
    let actual_signature = required_artifact_str(artifact, "signature", &spec.system_id)?;
    if actual_signature != expected_signature {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.signature does not verify",
            spec.system_id
        );
    }

    let unsupported_policy_hash =
        required_artifact_str(artifact, "unsupported_policy_hash", &spec.system_id)?;
    if unsupported_policy_hash != GENERATED_SYSTEM_UNSUPPORTED_POLICY_HASH {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.unsupported_policy_hash does not match the generated-system rejection policy",
            spec.system_id
        );
    }
    Ok(())
}

fn required_artifact_str<'a>(
    artifact: &'a serde_json::Map<String, Value>,
    field: &str,
    system_id: &str,
) -> Result<&'a str> {
    let value = artifact
        .get(field)
        .and_then(Value::as_str)
        .unwrap_or_default();
    if value.is_empty() {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.{} is required",
            system_id,
            field
        );
    }
    Ok(value)
}

fn require_artifact_string(
    artifact: &serde_json::Map<String, Value>,
    field: &str,
    expected: &str,
    system_id: &str,
) -> Result<()> {
    let actual = required_artifact_str(artifact, field, system_id)?;
    if actual != expected {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.compile_artifact.{} must be '{}'",
            system_id,
            field,
            expected
        );
    }
    Ok(())
}

fn compile_artifact_signature(artifact: &serde_json::Map<String, Value>) -> Result<String> {
    Ok(sha256_hex(
        compile_artifact_signature_material(artifact)?.as_bytes(),
    ))
}

fn compile_artifact_signature_material(
    artifact: &serde_json::Map<String, Value>,
) -> Result<String> {
    let fields = [
        "schema",
        "system_id",
        "cgs_hash",
        "source_hash",
        "runtime_executor_hash",
        "abi_hash",
        "sgc_plan_hash",
        "unsupported_policy_hash",
        "sandbox_hash",
        "signing_key_id",
    ];
    let mut lines = Vec::with_capacity(fields.len() + 1);
    for field in fields {
        lines.push(format!(
            "{}={}",
            field,
            required_artifact_str(
                artifact,
                field,
                artifact
                    .get("system_id")
                    .and_then(Value::as_str)
                    .unwrap_or("<unknown>")
            )?
        ));
    }
    let steps = artifact
        .get("validation_steps")
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow::anyhow!("compile artifact validation_steps must be an array"))?
        .iter()
        .map(|step| step.as_str().unwrap_or_default())
        .collect::<Vec<_>>()
        .join(",");
    lines.push(format!("validation_steps={}", steps));
    Ok(lines.join("\n"))
}

fn runtime_executor_hash_without_artifact(
    executor: &serde_json::Map<String, Value>,
) -> Result<String> {
    let mut stripped = executor.clone();
    stripped.remove("compile_artifact");
    stable_json_hash(&Value::Object(stripped))
}

fn stable_json_hash(value: &Value) -> Result<String> {
    Ok(sha256_hex(serde_json::to_string(value)?.as_bytes()))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("{:x}", digest)
}

fn is_lower_hex_64(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn validate_explicit_events(
    spec: &GeneratedSystemAbiSpec,
    events: &serde_json::Map<String, Value>,
) -> Result<()> {
    let emits = events
        .get("emits")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            anyhow::anyhow!(
                "CGS system '{}' runtime_executor.abi.events.emits must be an array",
                spec.system_id
            )
        })?;
    if emits.len() != spec.events.emits.len() {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.events.emits does not match executor event declarations",
            spec.system_id
        );
    }
    for (index, expected) in spec.events.emits.iter().enumerate() {
        let actual = emits[index].as_object().ok_or_else(|| {
            anyhow::anyhow!(
                "CGS system '{}' runtime_executor.abi.events.emits[{}] must be an object",
                spec.system_id,
                index
            )
        })?;
        let event_type = actual
            .get("event_type")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let broadcast = actual
            .get("broadcast")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if event_type != expected.event_type || broadcast != expected.broadcast {
            anyhow::bail!(
                "CGS system '{}' runtime_executor.abi.events.emits[{}] does not match executor event declaration",
                spec.system_id,
                index
            );
        }
        let payload = parse_payload(actual.get("payload"), &spec.system_id)?;
        if payload != expected.payload {
            anyhow::bail!(
                "CGS system '{}' runtime_executor.abi.events.emits[{}].payload does not match executor payload",
                spec.system_id,
                index
            );
        }
    }
    Ok(())
}

fn required_object<'a>(
    parent: &'a serde_json::Map<String, Value>,
    key: &str,
    system_id: &str,
) -> Result<&'a serde_json::Map<String, Value>> {
    parent.get(key).and_then(Value::as_object).ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor.abi.{} must be an object",
            system_id,
            key
        )
    })
}

fn required_u32_array(
    parent: &serde_json::Map<String, Value>,
    key: &str,
    system_id: &str,
) -> Result<Vec<u32>> {
    let values = parent.get(key).and_then(Value::as_array).ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor.abi.{} must be an array",
            system_id,
            key
        )
    })?;
    let mut parsed = Vec::with_capacity(values.len());
    for value in values {
        parsed.push(required_u32(Some(value), system_id, key)?);
    }
    Ok(sorted_unique_u32(&parsed))
}

fn required_bool(
    parent: &serde_json::Map<String, Value>,
    key: &str,
    system_id: &str,
) -> Result<bool> {
    parent.get(key).and_then(Value::as_bool).ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor.abi.{} must be a boolean",
            system_id,
            key
        )
    })
}

fn require_string_value(
    parent: &serde_json::Map<String, Value>,
    key: &str,
    expected: &str,
    system_id: &str,
) -> Result<()> {
    let actual = parent.get(key).and_then(Value::as_str).unwrap_or_default();
    if actual != expected {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.abi.rollback.{} must be '{}'",
            system_id,
            key,
            expected
        );
    }
    Ok(())
}

fn runtime_executor_component_type_id(value: Option<&Value>, system_id: &str) -> Result<u32> {
    let Some(value) = value else {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.component_type_id is required",
            system_id
        );
    };
    required_u32(Some(value), system_id, "component_type_id")
}

fn required_u32(value: Option<&Value>, system_id: &str, field: &str) -> Result<u32> {
    let Some(value) = value else {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} is required",
            system_id,
            field
        );
    };
    let Some(raw) = value.as_u64() else {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} must be an integer",
            system_id,
            field
        );
    };
    if raw == 0 || raw > u32::MAX as u64 {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} {} is outside the supported u32 range",
            system_id,
            field,
            raw
        );
    }
    Ok(raw as u32)
}

fn required_u32_allow_zero(value: Option<&Value>, system_id: &str, field: &str) -> Result<u32> {
    let Some(value) = value else {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} is required",
            system_id,
            field
        );
    };
    let Some(raw) = value.as_u64() else {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} must be an integer",
            system_id,
            field
        );
    };
    if raw > u32::MAX as u64 {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} {} is outside the supported u32 range",
            system_id,
            field,
            raw
        );
    }
    Ok(raw as u32)
}

fn required_field_name(value: Option<&Value>, system_id: &str) -> Result<String> {
    let field = value
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_string();
    if field.is_empty() {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.field is required",
            system_id
        );
    }
    if field.contains('.') {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.field must be a top-level JSON object field",
            system_id
        );
    }
    Ok(field)
}

fn fixed_number(value: Option<&Value>, system_id: &str, field: &str) -> Result<Fixed64> {
    value
        .and_then(|value| fixed_from_json(value, IntegerEncoding::WholeUnits))
        .ok_or_else(|| {
            anyhow::anyhow!(
                "CGS system '{}' runtime_executor.{} must be a fixed-point number",
                system_id,
                field
            )
        })
}

fn fixed_number_or_default(
    value: Option<&Value>,
    system_id: &str,
    field: &str,
    default: Fixed64,
) -> Result<Fixed64> {
    match value {
        Some(value) => fixed_number(Some(value), system_id, field),
        None => Ok(default),
    }
}

fn scalar_json_value(value: Option<&Value>, system_id: &str, field: &str) -> Result<Value> {
    let Some(value) = value else {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.{} is required",
            system_id,
            field
        )
    };
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(value.clone()),
        Value::Number(_) => fixed_from_json(value, IntegerEncoding::WholeUnits)
            .map(fixed_value)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "CGS system '{}' runtime_executor.{} must be a fixed-point scalar",
                    system_id,
                    field
                )
            }),
        _ => anyhow::bail!(
            "CGS system '{}' runtime_executor.{} must be a scalar JSON value",
            system_id,
            field
        ),
    }
}

fn require_component_access(
    system_id: &str,
    component_type_id: u32,
    reads: &[u32],
    writes: &[u32],
    requires_write: bool,
) -> Result<()> {
    require_component_read(system_id, component_type_id, reads)?;
    if requires_write && !writes.contains(&component_type_id) {
        anyhow::bail!(
            "CGS system '{}' runtime_executor.component_type_id {} must be declared in writes",
            system_id,
            component_type_id
        );
    }
    Ok(())
}

fn require_component_read(system_id: &str, component_type_id: u32, reads: &[u32]) -> Result<()> {
    if !reads.contains(&component_type_id) {
        anyhow::bail!(
            "CGS system '{}' runtime_executor component_type_id {} must be declared in reads",
            system_id,
            component_type_id
        );
    }
    Ok(())
}

fn require_component_write(system_id: &str, component_type_id: u32, writes: &[u32]) -> Result<()> {
    if !writes.contains(&component_type_id) {
        anyhow::bail!(
            "CGS system '{}' runtime_executor component_type_id {} must be declared in writes",
            system_id,
            component_type_id
        );
    }
    Ok(())
}

fn parse_payload(value: Option<&Value>, system_id: &str) -> Result<BTreeMap<String, String>> {
    let mut payload = BTreeMap::new();
    let Some(value) = value else {
        return Ok(payload);
    };
    let object = value.as_object().ok_or_else(|| {
        anyhow::anyhow!(
            "CGS system '{}' runtime_executor.payload must be an object",
            system_id
        )
    })?;
    for (key, value) in object {
        let text = match value {
            Value::String(text) => text.clone(),
            Value::Bool(value) => value.to_string(),
            Value::Number(number) => number.to_string(),
            _ => {
                anyhow::bail!(
                    "CGS system '{}' runtime_executor.payload.{} must be a scalar value",
                    system_id,
                    key
                );
            }
        };
        payload.insert(key.clone(), text);
    }
    Ok(payload)
}

fn parse_phase(phase: &str) -> Result<PhaseEnum> {
    match phase.trim() {
        "Initialization" | "initialization" => Ok(PhaseEnum::Initialization),
        "Input" | "input" => Ok(PhaseEnum::Input),
        "Simulation" | "simulation" | "" => Ok(PhaseEnum::Simulation),
        "PostSimulation" | "post_simulation" | "postsimulation" => Ok(PhaseEnum::PostSimulation),
        "Cleanup" | "cleanup" => Ok(PhaseEnum::Cleanup),
        other => anyhow::bail!("CGS runtime_executor phase '{}' is not supported", other),
    }
}

fn parse_event_type(name: &str) -> EventType {
    match name.strip_prefix("domain:") {
        Some(domain) => EventType::Domain(domain.to_string()),
        None => EventType::Domain(name.to_string()),
    }
}

fn validate_json_object(
    system_id: &str,
    component_type_id: u32,
    component_json: &str,
) -> std::result::Result<(), XaceError> {
    let value = parse_component_object(system_id, component_type_id, component_json)?;
    if !value.is_object() {
        return Err(generated_validation_error(
            system_id,
            "execute",
            format!(
                "Generated system '{}' requires component {} to be a JSON object",
                system_id, component_type_id
            ),
            format!("component:{}", component_type_id),
        ));
    }
    Ok(())
}

fn parse_component_object(
    system_id: &str,
    component_type_id: u32,
    component_json: &str,
) -> std::result::Result<Value, XaceError> {
    let value = serde_json::from_str::<Value>(component_json).map_err(|err| {
        generated_validation_error(
            system_id,
            "execute",
            format!(
                "Generated system '{}' could not parse component {} JSON: {}",
                system_id, component_type_id, err
            ),
            format!("component:{}", component_type_id),
        )
    })?;
    if !value.is_object() {
        return Err(generated_validation_error(
            system_id,
            "execute",
            format!(
                "Generated system '{}' requires component {} to be a JSON object",
                system_id, component_type_id
            ),
            format!("component:{}", component_type_id),
        ));
    }
    Ok(value)
}

fn generated_validation_error(
    system_id: &str,
    operation: &str,
    message: String,
    failed_path: String,
) -> XaceError {
    XaceError::ValidationFailure {
        message,
        context: ErrorContext::new(system_id, operation),
        rule_violated: "generated_system_abi".into(),
        failed_path,
    }
}

fn sorted_unique_u32(values: &[u32]) -> Vec<u32> {
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    sorted.dedup();
    sorted
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn legacy_increment_executor_normalizes_to_full_abi() {
        let spec = spec_from_runtime_executor(
            "GeneratedCounterSystem",
            "Simulation",
            &[300],
            &[300],
            &json!({
                "kind": GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
                "component_type_id": 300,
                "field": "count",
                "amount": 1
            }),
        )
        .unwrap()
        .unwrap();

        assert_eq!(spec.inputs.query_components, vec![300]);
        assert_eq!(spec.rng.allowed, false);
        assert!(spec.events.emits.is_empty());
        assert_eq!(
            spec.rollback.mutation_hook,
            GeneratedRollbackHook::MutationGateDeferred
        );
    }

    #[test]
    fn explicit_rng_event_abi_is_validated() {
        let spec = spec_from_runtime_executor(
            "GeneratedLootRollSystem",
            "Simulation",
            &[301],
            &[],
            &json!({
                "kind": GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND,
                "component_type_id": 301,
                "chance": 1,
                "event_type": "generated.loot_roll",
                "payload": {"source": "generated"},
                "abi": {
                    "schema": GENERATED_SYSTEM_ABI_SCHEMA,
                    "version": GENERATED_SYSTEM_ABI_VERSION,
                    "inputs": {
                        "query_components": [301],
                        "component_reads": [301],
                        "current_tick": true
                    },
                    "events": {
                        "emits": [
                            {
                                "event_type": "generated.loot_roll",
                                "broadcast": true,
                                "payload": {"source": "generated"}
                            }
                        ]
                    },
                    "rng": {"allowed": true, "max_calls_per_entity": 1},
                    "errors": {"policy": "halt_and_rollback"},
                    "rollback": {
                        "mutation_hook": "mutation_gate_deferred",
                        "event_hook": "event_bus_phase_buffered",
                        "rng_hook": "rng_windowed"
                    }
                }
            }),
        )
        .unwrap()
        .unwrap();

        assert_eq!(spec.rng.max_calls_per_entity, 1);
        assert_eq!(spec.events.emits[0].event_type, "generated.loot_roll");
    }

    #[test]
    fn plugin_executor_normalizes_through_runtime_abi_contract() {
        let spec = spec_from_runtime_executor(
            "PluginWeatherSystem",
            "PostSimulation",
            &[700],
            &[700],
            &json!({
                "kind": PLUGIN_SET_JSON_FIELD_EXECUTOR_KIND,
                "component_type_id": 700,
                "field": "active",
                "value": true,
                "abi": {
                    "schema": RUNTIME_EXECUTOR_ABI_SCHEMA,
                    "version": GENERATED_SYSTEM_ABI_VERSION,
                    "inputs": {
                        "query_components": [700],
                        "component_reads": [700],
                        "current_tick": false
                    },
                    "events": {"emits": []},
                    "rng": {"allowed": false, "max_calls_per_entity": 0},
                    "errors": {"policy": "halt_and_rollback"},
                    "rollback": {
                        "mutation_hook": "mutation_gate_deferred",
                        "event_hook": "event_bus_phase_buffered",
                        "rng_hook": "rng_windowed"
                    }
                }
            }),
        )
        .unwrap()
        .unwrap();

        assert_eq!(spec.source, RuntimeExecutorSource::Plugin);
        assert_eq!(spec.kind, PLUGIN_SET_JSON_FIELD_EXECUTOR_KIND);
        assert_eq!(spec.inputs.query_components, vec![700]);
    }

    #[test]
    fn external_executor_normalizes_through_runtime_abi_contract() {
        let spec = spec_from_runtime_executor(
            "ExternalMirrorSystem",
            "Simulation",
            &[701, 702],
            &[702],
            &json!({
                "kind": EXTERNAL_COPY_NUMERIC_FIELD_EXECUTOR_KIND,
                "source_component_type_id": 701,
                "source_field": "power",
                "target_component_type_id": 702,
                "target_field": "mirrored_power",
                "scale": 2,
                "offset": 1,
                "abi": {
                    "schema": RUNTIME_EXECUTOR_ABI_SCHEMA,
                    "version": GENERATED_SYSTEM_ABI_VERSION,
                    "inputs": {
                        "query_components": [701, 702],
                        "component_reads": [701, 702],
                        "current_tick": false
                    },
                    "events": {"emits": []},
                    "rng": {"allowed": false, "max_calls_per_entity": 0},
                    "errors": {"policy": "halt_and_rollback"},
                    "rollback": {
                        "mutation_hook": "mutation_gate_deferred",
                        "event_hook": "event_bus_phase_buffered",
                        "rng_hook": "rng_windowed"
                    }
                }
            }),
        )
        .unwrap()
        .unwrap();

        assert_eq!(spec.source, RuntimeExecutorSource::External);
        assert_eq!(spec.kind, EXTERNAL_COPY_NUMERIC_FIELD_EXECUTOR_KIND);
        assert_eq!(spec.inputs.component_reads, vec![701, 702]);
    }

    #[test]
    fn explicit_abi_rejects_rng_budget_mismatch() {
        let err = spec_from_runtime_executor(
            "GeneratedLootRollSystem",
            "Simulation",
            &[301],
            &[],
            &json!({
                "kind": GENERATED_EMIT_RNG_THRESHOLD_EVENT_EXECUTOR_KIND,
                "component_type_id": 301,
                "chance": 1,
                "event_type": "generated.loot_roll",
                "abi": {
                    "schema": GENERATED_SYSTEM_ABI_SCHEMA,
                    "version": GENERATED_SYSTEM_ABI_VERSION,
                    "inputs": {
                        "query_components": [301],
                        "component_reads": [301],
                        "current_tick": true
                    },
                    "events": {"emits": [{"event_type": "generated.loot_roll", "broadcast": true}]},
                    "rng": {"allowed": false, "max_calls_per_entity": 0},
                    "errors": {"policy": "halt_and_rollback"},
                    "rollback": {
                        "mutation_hook": "mutation_gate_deferred",
                        "event_hook": "event_bus_phase_buffered",
                        "rng_hook": "rng_windowed"
                    }
                }
            }),
        )
        .expect_err("mismatched RNG ABI must fail");

        assert!(err.to_string().contains("abi.rng"));
    }

    #[test]
    fn signed_compile_artifact_is_validated() {
        let executor = signed_increment_executor();
        let spec = spec_from_runtime_executor(
            "GeneratedCounterSystem",
            "Simulation",
            &[300],
            &[300],
            &executor,
        )
        .unwrap()
        .unwrap();

        assert_eq!(
            spec.kind,
            GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND.to_string()
        );
    }

    #[test]
    fn signed_compile_artifact_rejects_executor_tampering() {
        let mut executor = signed_increment_executor();
        executor["amount"] = json!(2);

        let err = spec_from_runtime_executor(
            "GeneratedCounterSystem",
            "Simulation",
            &[300],
            &[300],
            &executor,
        )
        .expect_err("tampered signed executor must fail runtime validation");

        assert!(err.to_string().contains("runtime_executor_hash"));
    }

    #[test]
    fn signed_compile_artifact_rejects_policy_tampering() {
        let mut executor = signed_increment_executor();
        executor["compile_artifact"]["unsupported_policy_hash"] =
            json!("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee");
        let signature =
            compile_artifact_signature(executor["compile_artifact"].as_object().unwrap()).unwrap();
        executor["compile_artifact"]["signature"] = Value::String(signature);

        let err = spec_from_runtime_executor(
            "GeneratedCounterSystem",
            "Simulation",
            &[300],
            &[300],
            &executor,
        )
        .expect_err("tampered unsupported policy hash must fail runtime validation");

        assert!(err.to_string().contains("unsupported_policy_hash"));
    }

    fn signed_increment_executor() -> Value {
        let mut executor = json!({
            "kind": GENERATED_INCREMENT_NUMERIC_FIELD_EXECUTOR_KIND,
            "component_type_id": 300,
            "field": "count",
            "amount": 1,
            "abi": {
                "schema": GENERATED_SYSTEM_ABI_SCHEMA,
                "version": GENERATED_SYSTEM_ABI_VERSION,
                "inputs": {
                    "query_components": [300],
                    "component_reads": [300],
                    "current_tick": false
                },
                "events": {"emits": []},
                "rng": {"allowed": false, "max_calls_per_entity": 0},
                "errors": {"policy": "halt_and_rollback"},
                "rollback": {
                    "mutation_hook": "mutation_gate_deferred",
                    "event_hook": "event_bus_phase_buffered",
                    "rng_hook": "rng_windowed"
                }
            }
        });
        let artifact = compile_artifact_for_test(&executor);
        executor["compile_artifact"] = artifact;
        executor
    }

    fn compile_artifact_for_test(executor: &Value) -> Value {
        let executor_map = executor.as_object().unwrap();
        let mut artifact = json!({
            "schema": GENERATED_SYSTEM_COMPILE_ARTIFACT_SCHEMA,
            "system_id": "GeneratedCounterSystem",
            "cgs_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "source_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "runtime_executor_hash": runtime_executor_hash_without_artifact(executor_map).unwrap(),
            "abi_hash": stable_json_hash(executor.get("abi").unwrap()).unwrap(),
            "sgc_plan_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "unsupported_policy_hash": GENERATED_SYSTEM_UNSUPPORTED_POLICY_HASH,
            "sandbox_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            "validation_steps": GENERATED_SYSTEM_COMPILE_ARTIFACT_STEPS,
            "cargo": {
                "sandbox": "temp_cargo_project_no_workspace_writes",
                "duration_ms": 1,
                "warnings": 0
            },
            "signing_key_id": GENERATED_SYSTEM_COMPILE_ARTIFACT_SIGNING_KEY_ID
        });
        let signature = compile_artifact_signature(artifact.as_object().unwrap()).unwrap();
        artifact["signature"] = Value::String(signature);
        artifact
    }
}
