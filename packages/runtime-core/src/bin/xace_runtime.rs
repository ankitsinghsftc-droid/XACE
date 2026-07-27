//! Standalone XACE runtime with optional live engine bridge.

use std::fs;
use std::path::{Path, PathBuf};
use std::process;
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

use clap::Parser;

use xace_runtime_core::cgs_loader;
use xace_runtime_core::component_tables::component_table_store::ComponentTableStore;
use xace_runtime_core::control_protocol::{
    RuntimeControlAck, RuntimeControlAction, RuntimeControlCommand, RuntimeControlEngineConnection,
    RuntimeControlHashRecord, RuntimeControlInbound, RuntimeControlStatus, RuntimeEngineEditAck,
    RuntimeEngineEditCommand, RuntimeEngineEditKind,
};
use xace_runtime_core::control_server::{
    start_runtime_control_server, RuntimeControlRequest, RuntimeControlServerConfig,
};
use xace_runtime_core::entity_store::entity_store::EntityStore;
use xace_runtime_core::runtime_orchestrator::{RuntimeConfig, RuntimeOrchestrator};
use xace_runtime_core::state_printer::PrinterOpts;
use xace_runtime_core::tcp_server::{EngineConnection, TcpEngineServer, TcpServerConfig};

#[derive(Parser, Debug)]
#[command(
    name = "xace_runtime",
    version = "0.1.0-phase15",
    about = "XACE deterministic runtime with live engine bridge"
)]
struct Cli {
    #[arg(long)]
    cgs: PathBuf,

    #[arg(long)]
    require_sgc_plan: bool,

    #[arg(long)]
    sgc_plan: Option<PathBuf>,

    #[arg(
        long,
        help = "Development/test only: derive a runtime schedule from CGS when no persisted SGC plan is available"
    )]
    derive_cgs_plan: bool,

    #[arg(long, default_value_t = 7777)]
    port: u16,

    #[arg(long, default_value_t = 1)]
    engine_clients: usize,

    #[arg(long, default_value_t = 7778)]
    control_port: u16,

    #[arg(long)]
    no_control: bool,

    #[arg(long)]
    start_paused: bool,

    #[arg(long)]
    no_wait: bool,

    #[arg(long)]
    live_engine_accept: bool,

    #[arg(long, default_value_t = 0)]
    wait_secs: u64,

    #[arg(long, default_value_t = 0)]
    ticks: u64,

    #[arg(long, default_value_t = 60)]
    print_every: u64,

    #[arg(long, default_value_t = 60)]
    tick_rate: u32,

    #[arg(long, default_value_t = 42)]
    world_seed: u64,

    #[arg(long)]
    verbose: bool,

    #[arg(long)]
    quiet: bool,

    #[arg(long)]
    schedule_snapshot_out: Option<PathBuf>,

    #[arg(long, default_value = "info")]
    log: String,
}

fn main() {
    let cli = Cli::parse();
    init_logger(&cli.log);
    if let Err(err) = run(cli) {
        eprintln!("[error] {err}");
        process::exit(1);
    }
}

fn run(cli: Cli) -> anyhow::Result<()> {
    if cli.tick_rate == 0 {
        anyhow::bail!("--tick-rate must be greater than zero");
    }
    if cli.engine_clients == 0 {
        anyhow::bail!("--engine-clients must be greater than zero");
    }
    if cli.live_engine_accept && !cli.no_wait {
        anyhow::bail!("--live-engine-accept requires --no-wait");
    }
    if cli.derive_cgs_plan && (cli.require_sgc_plan || cli.sgc_plan.is_some()) {
        anyhow::bail!("--derive-cgs-plan cannot be combined with --require-sgc-plan or --sgc-plan");
    }
    if !cli.cgs.exists() {
        anyhow::bail!("CGS file does not exist: {}", cli.cgs.display());
    }

    let mut config = RuntimeConfig::default();
    config.bridge.tick_rate = cli.tick_rate;
    config.world_seed = cli.world_seed;
    if cli.derive_cgs_plan {
        config.sgc_plan_policy = cgs_loader::SgcPlanPolicy::DeriveFromCgs;
    } else if cli.require_sgc_plan || cli.sgc_plan.is_some() {
        config.sgc_plan_policy = cgs_loader::SgcPlanPolicy::RequirePersisted;
    }
    config.sgc_plan_path = cli.sgc_plan.clone();
    let mut runtime = RuntimeOrchestrator::initialise_with_config(&cli.cgs, config.clone())?;
    print_startup(&cli, &runtime);
    let (control_rx, _control_handle) = start_control_socket(&cli)?;
    let (engine_rx, _engine_accept_handle) = start_live_engine_acceptor(&cli)?;

    let engine_requested = !cli.no_wait;
    let connected = if cli.no_wait {
        0
    } else if cli.wait_secs == 0 {
        runtime.connect_engines(cli.port, cli.engine_clients)?;
        cli.engine_clients
    } else {
        runtime.try_connect_engines(cli.port, cli.engine_clients, cli.wait_secs)?
    };
    if !cli.quiet {
        if connected > 0 {
            println!("[ready] engine clients connected: {}", connected);
        } else {
            println!("[ready] headless");
        }
    }

    let printer_opts = PrinterOpts {
        verbose: cli.verbose,
        max_entities: if cli.verbose { 32 } else { 12 },
    };
    let tick_dt = Duration::from_secs_f64(1.0 / f64::from(cli.tick_rate));
    let start = Instant::now();
    let mut next_tick_at = Instant::now();
    let mut tick_count = 0_u64;
    let mut total_changes = 0_u64;
    let mut total_engine_inputs = 0_u64;
    let mut paused = cli.start_paused;
    let mut step_budget = 0_u64;
    let mut shutdown_requested = false;

    loop {
        accept_live_engine_connections(&engine_rx, &mut runtime)?;
        let runtime_config = runtime.config().clone();
        process_control_requests(
            &control_rx,
            &mut runtime,
            &mut paused,
            &mut step_budget,
            &mut shutdown_requested,
            &cli.cgs,
            runtime_config,
        )?;
        if shutdown_requested {
            break;
        }
        if cli.ticks > 0 && tick_count >= cli.ticks {
            break;
        }
        if paused && step_budget == 0 {
            std::thread::sleep(Duration::from_millis(8));
            continue;
        }
        if step_budget > 0 {
            step_budget -= 1;
        }

        let result = runtime
            .tick()
            .map_err(|err| anyhow::anyhow!("tick {} failed: {:?}", tick_count, err))?;
        total_changes = total_changes.saturating_add(result.state_delta.change_count() as u64);
        if let Some(summary) = runtime.last_tick_result() {
            total_engine_inputs =
                total_engine_inputs.saturating_add(summary.engine_inputs_applied as u64);
        }

        if !cli.quiet && cli.print_every > 0 && tick_count % cli.print_every == 0 {
            runtime.print_state(result.tick, &result.state_delta, &printer_opts);
        }

        tick_count = tick_count.saturating_add(1);
        if runtime.engine_connected() {
            next_tick_at += tick_dt;
            if let Some(sleep) = next_tick_at.checked_duration_since(Instant::now()) {
                std::thread::sleep(sleep);
            }
        }
        if cli.ticks == 0 && engine_requested && tick_count > 1 && !runtime.engine_connected() {
            if !cli.quiet {
                println!("[stopped] engine disconnected after {} ticks", tick_count);
            }
            break;
        }
    }

    if let Some(path) = &cli.schedule_snapshot_out {
        write_schedule_snapshot_report(path, &runtime, tick_count)?;
    }
    runtime.disconnect_engine("runtime_shutdown");
    print_done(
        &runtime,
        start,
        tick_count,
        total_changes,
        total_engine_inputs,
        cli.quiet,
    );
    Ok(())
}

fn write_schedule_snapshot_report(
    path: &Path,
    runtime: &RuntimeOrchestrator,
    tick_count: u64,
) -> anyhow::Result<()> {
    let schedule_identity = runtime.schedule_identity();
    let snapshots = runtime.schedule_snapshots();
    let status = runtime.status();
    let hash_log = status
        .hash_log
        .into_iter()
        .map(|record| {
            serde_json::json!({
                "tick": record.tick,
                "world_hash": record.world_hash,
            })
        })
        .collect::<Vec<_>>();
    let mismatches = snapshots
        .iter()
        .filter(|snapshot| schedule_identity.validate_snapshot(snapshot).is_err())
        .map(|snapshot| snapshot.tick)
        .collect::<Vec<_>>();
    let report = serde_json::json!({
        "schema": "xace.runtime.schedule_snapshot_report.v1",
        "ok": snapshots.len() == tick_count as usize && mismatches.is_empty(),
        "tick_count": tick_count,
        "snapshot_count": snapshots.len(),
        "mismatched_ticks": mismatches,
        "latest_world_hash": status.latest_world_hash,
        "hash_log": hash_log,
        "parallel_group_execution_policy": runtime.parallel_group_execution_policy().as_str(),
        "parallel_group_worker_threads": runtime.parallel_group_execution_policy().uses_worker_threads(),
        "plan_source": runtime.spawn_summary().phase_plan_source,
        "schema_version": &schedule_identity.schema_version,
        "plan_version": schedule_identity.plan_version,
        "world_seed": runtime.config().world_seed,
        "plan_hash": &schedule_identity.plan_hash,
        "cgs_hash": &schedule_identity.cgs_hash,
        "compiled_from_cgs_hash": &schedule_identity.compiled_from_cgs_hash,
        "scheduled_system_ids": &schedule_identity.scheduled_system_ids,
        "groups": &schedule_identity.groups,
        "system_access": &schedule_identity.system_access,
        "system_dependencies": &schedule_identity.system_dependencies,
        "snapshots": snapshots,
    });
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(&report)?)?;
    Ok(())
}

fn start_live_engine_acceptor(
    cli: &Cli,
) -> anyhow::Result<(
    Option<Receiver<EngineConnection>>,
    Option<std::thread::JoinHandle<()>>,
)> {
    if !cli.live_engine_accept {
        return Ok((None, None));
    }

    let port = cli.port;
    let (tx, rx) = mpsc::channel();
    let server = TcpEngineServer::bind(TcpServerConfig::localhost(port))?;
    if !cli.quiet {
        println!(
            "[ready] accepting live engine clients on 127.0.0.1:{}",
            port
        );
    }
    let handle = std::thread::spawn(move || loop {
        match server.accept_timeout(Duration::from_millis(100)) {
            Ok(Some(connection)) => {
                if tx.send(connection).is_err() {
                    break;
                }
            }
            Ok(None) => {}
            Err(err) => {
                log::warn!("Live engine accept failed: {}", err);
                break;
            }
        }
    });
    Ok((Some(rx), Some(handle)))
}

fn accept_live_engine_connections(
    engine_rx: &Option<Receiver<EngineConnection>>,
    runtime: &mut RuntimeOrchestrator,
) -> anyhow::Result<usize> {
    let Some(engine_rx) = engine_rx else {
        return Ok(0);
    };
    let mut accepted = 0_usize;
    while let Ok(connection) = engine_rx.try_recv() {
        runtime.accept_engine_connection(connection)?;
        accepted = accepted.saturating_add(1);
    }
    Ok(accepted)
}

fn start_control_socket(
    cli: &Cli,
) -> anyhow::Result<(
    Receiver<RuntimeControlRequest>,
    Option<std::thread::JoinHandle<()>>,
)> {
    let (tx, rx) = mpsc::channel();
    if cli.no_control {
        return Ok((rx, None));
    }
    let handle =
        start_runtime_control_server(RuntimeControlServerConfig::localhost(cli.control_port), tx)?;
    Ok((rx, Some(handle)))
}

fn process_control_requests(
    control_rx: &Receiver<RuntimeControlRequest>,
    runtime: &mut RuntimeOrchestrator,
    paused: &mut bool,
    step_budget: &mut u64,
    shutdown_requested: &mut bool,
    cgs_path: &std::path::Path,
    config: RuntimeConfig,
) -> anyhow::Result<()> {
    while let Ok(request) = control_rx.try_recv() {
        let response = match &request.message {
            RuntimeControlInbound::Control(command) => {
                serde_json::to_value(apply_control_command(
                    command,
                    runtime,
                    paused,
                    step_budget,
                    shutdown_requested,
                    cgs_path,
                    config.clone(),
                )?)?
            }
            RuntimeControlInbound::EngineEdit(command) => serde_json::to_value(
                apply_engine_edit_command(command, runtime, *paused, *step_budget),
            )?,
        };
        let _ = request.response_tx.send(response);
    }
    Ok(())
}

fn apply_control_command(
    command: &RuntimeControlCommand,
    runtime: &mut RuntimeOrchestrator,
    paused: &mut bool,
    step_budget: &mut u64,
    shutdown_requested: &mut bool,
    cgs_path: &std::path::Path,
    config: RuntimeConfig,
) -> anyhow::Result<RuntimeControlAck> {
    if command.action == RuntimeControlAction::ReplayRecord {
        return Ok(match runtime.record_replay_hash_log() {
            Ok(count) => RuntimeControlAck::accepted(
                command,
                format!("recorded replay hash log with {} tick(s)", count),
                make_control_status(runtime, *paused, *step_budget),
            ),
            Err(err) => RuntimeControlAck::rejected(
                command,
                err.to_string(),
                make_control_status(runtime, *paused, *step_budget),
            ),
        });
    }

    if command.action == RuntimeControlAction::ReplayValidate {
        return Ok(
            match runtime.validate_recorded_replay_from_cgs(cgs_path, config) {
                Ok(report) if report.passed => RuntimeControlAck::accepted(
                    command,
                    format!(
                        "replay validation passed for {} tick(s)",
                        report.compared_ticks
                    ),
                    make_control_status(runtime, *paused, *step_budget),
                ),
                Ok(report) => {
                    let reason = match report.first_mismatch {
                        Some(mismatch) => format!(
                            "replay validation failed at tick {}: expected '{}', got '{}'",
                            mismatch.tick, mismatch.expected_hash, mismatch.actual_hash
                        ),
                        None => "replay validation failed".to_string(),
                    };
                    RuntimeControlAck::rejected(
                        command,
                        reason,
                        make_control_status(runtime, *paused, *step_budget),
                    )
                }
                Err(err) => RuntimeControlAck::rejected(
                    command,
                    err.to_string(),
                    make_control_status(runtime, *paused, *step_budget),
                ),
            },
        );
    }

    let reason = match command.action {
        RuntimeControlAction::Play => {
            *paused = false;
            "runtime resumed".to_string()
        }
        RuntimeControlAction::Pause => {
            *paused = true;
            "runtime paused".to_string()
        }
        RuntimeControlAction::Step => {
            *paused = true;
            *step_budget = step_budget.saturating_add(1);
            "queued one deterministic tick".to_string()
        }
        RuntimeControlAction::Reset => {
            runtime.disconnect_engine("runtime_control_reset");
            *runtime = RuntimeOrchestrator::initialise_with_config(cgs_path, config)?;
            *paused = true;
            *step_budget = 0;
            "runtime reset and paused at tick 0".to_string()
        }
        RuntimeControlAction::ReloadCgs => {
            if let Some(reason) = reload_version_mismatch(command, runtime, cgs_path, &config)? {
                return Ok(RuntimeControlAck::rejected(
                    command,
                    reason,
                    make_control_status(runtime, *paused, *step_budget),
                ));
            }
            let report = runtime.hot_swap_cgs_at_tick_boundary(cgs_path, config)?;
            format!(
                "runtime hot-swapped CGS at tick {}; new systems active on tick {}",
                report.applied_tick, report.applied_tick
            )
        }
        RuntimeControlAction::Status => "runtime status".to_string(),
        RuntimeControlAction::Snapshot => "runtime snapshot".to_string(),
        RuntimeControlAction::ReplayRecord | RuntimeControlAction::ReplayValidate => {
            unreachable!("replay control actions are handled before lifecycle commands")
        }
        RuntimeControlAction::Shutdown => {
            *shutdown_requested = true;
            "runtime shutdown requested".to_string()
        }
    };
    let status = make_control_status(runtime, *paused, *step_budget);
    let mut ack = RuntimeControlAck::accepted(command, reason, status);
    if command.action == RuntimeControlAction::Snapshot {
        ack = ack.with_snapshot(runtime.control_snapshot());
    }
    Ok(ack)
}

fn apply_engine_edit_command(
    command: &RuntimeEngineEditCommand,
    runtime: &mut RuntimeOrchestrator,
    paused: bool,
    step_budget: u64,
) -> RuntimeEngineEditAck {
    match command.kind {
        RuntimeEngineEditKind::SelectEntity | RuntimeEngineEditKind::FocusEntity => {
            if runtime.entity_is_alive(command.entity_id) {
                RuntimeEngineEditAck::accepted(
                    command,
                    "entity verified",
                    vec![command.entity_id],
                    make_control_status(runtime, paused, step_budget),
                )
            } else {
                RuntimeEngineEditAck::rejected(
                    command,
                    format!("entity {} is not alive", command.entity_id),
                    make_control_status(runtime, paused, step_budget),
                )
            }
        }
        RuntimeEngineEditKind::SetComponentField => {
            let Some(component_type_id) = command.component_type_id else {
                return RuntimeEngineEditAck::rejected(
                    command,
                    "component_type_id is required",
                    make_control_status(runtime, paused, step_budget),
                );
            };
            match runtime.set_preview_component_field(
                command.entity_id,
                component_type_id,
                &command.field_path,
                command.value.clone(),
            ) {
                Ok(()) => RuntimeEngineEditAck::accepted(
                    command,
                    "preview component field updated",
                    vec![command.entity_id],
                    make_control_status(runtime, paused, step_budget),
                ),
                Err(err) => RuntimeEngineEditAck::rejected(
                    command,
                    err.to_string(),
                    make_control_status(runtime, paused, step_budget),
                ),
            }
        }
    }
}

fn make_control_status(
    runtime: &RuntimeOrchestrator,
    paused: bool,
    step_budget: u64,
) -> RuntimeControlStatus {
    let status = runtime.status();
    RuntimeControlStatus {
        tick: status.tick,
        alive_count: status.alive_count,
        engine_connected: status.engine_connected,
        adapter_type: status.adapter_type,
        engine_connections: status
            .engine_connections
            .into_iter()
            .map(|connection| RuntimeControlEngineConnection {
                adapter_type: connection.adapter_type,
                connected: connection.connected,
                snapshots_sent: connection.snapshots_sent,
                input_packets_received: connection.input_packets_received,
                feedback_payloads_received: connection.feedback_payloads_received,
                feedback_messages_received: connection.feedback_messages_received,
                malformed_messages: connection.malformed_messages,
                dropped_inputs: connection.dropped_inputs,
                queued_inputs: connection.queued_inputs,
                queued_feedback: connection.queued_feedback,
            })
            .collect(),
        engine_snapshots_sent: status.engine_snapshots_sent,
        engine_input_packets_received: status.engine_input_packets_received,
        engine_feedback_payloads_received: status.engine_feedback_payloads_received,
        engine_feedback_messages_received: status.engine_feedback_messages_received,
        engine_malformed_messages: status.engine_malformed_messages,
        engine_dropped_inputs: status.engine_dropped_inputs,
        pending_engine_inputs: status.pending_engine_inputs,
        pending_engine_feedback: status.pending_engine_feedback,
        registered_systems: status.registered_systems,
        phase_count: status.phase_count,
        last_engine_feedback_processed: status.last_engine_feedback_processed,
        last_engine_feedback_invalid: status.last_engine_feedback_invalid,
        last_engine_feedback_errors: status.last_engine_feedback_errors,
        latest_world_hash: status.latest_world_hash,
        cgs_hash: status.cgs_hash,
        schema_version: status.schema_version,
        execution_plan_version: status.execution_plan_version,
        parallel_group_execution_policy: status.parallel_group_execution_policy,
        parallel_group_worker_threads: status.parallel_group_worker_threads,
        hash_log: status
            .hash_log
            .into_iter()
            .map(|record| RuntimeControlHashRecord {
                tick: record.tick,
                world_hash: record.world_hash,
            })
            .collect(),
        paused,
        step_budget,
    }
}

fn reload_version_mismatch(
    command: &RuntimeControlCommand,
    runtime: &RuntimeOrchestrator,
    cgs_path: &std::path::Path,
    config: &RuntimeConfig,
) -> anyhow::Result<Option<String>> {
    let disk = cgs_loader::load_cgs(cgs_path)?;
    let disk_hash = metadata_string(&disk.metadata, "cgs_hash").unwrap_or_default();
    let disk_schema = metadata_string(&disk.metadata, "schema_version")
        .or_else(|| metadata_string(&disk.metadata, "version"))
        .unwrap_or_else(|| runtime.spawn_summary().schema_version.clone());
    let requested_plan_version = !command.execution_plan_version.is_empty()
        && command.execution_plan_version != "unresolved";
    let disk_plan = if requested_plan_version {
        let mut scratch_entity_store = EntityStore::new();
        let mut scratch_table_store = ComponentTableStore::new();
        Some(
            cgs_loader::load_and_spawn_with_plan_policy(
                cgs_path,
                &mut scratch_entity_store,
                &mut scratch_table_store,
                config.sgc_plan_policy,
                config.sgc_plan_path.as_deref(),
            )?
            .execution_plan_version
            .to_string(),
        )
    } else {
        None
    };

    if !command.cgs_hash.is_empty() && command.cgs_hash != disk_hash {
        return Ok(Some(format!(
            "reload_cgs refused: requested cgs_hash '{}' but disk CGS is '{}'",
            command.cgs_hash, disk_hash
        )));
    }
    if !command.schema_version.is_empty() && command.schema_version != disk_schema {
        return Ok(Some(format!(
            "reload_cgs refused: requested schema_version '{}' but disk CGS is '{}'",
            command.schema_version, disk_schema
        )));
    }
    if let Some(disk_plan) = disk_plan {
        if command.execution_plan_version == disk_plan {
            return Ok(None);
        }
        return Ok(Some(format!(
            "reload_cgs refused: requested execution_plan_version '{}' but disk runtime plan is '{}'",
            command.execution_plan_version, disk_plan
        )));
    }
    Ok(None)
}

fn metadata_string(metadata: &serde_json::Value, key: &str) -> Option<String> {
    metadata
        .get(key)
        .and_then(serde_json::Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn print_startup(cli: &Cli, runtime: &RuntimeOrchestrator) {
    if cli.quiet {
        return;
    }
    let summary = runtime.spawn_summary();
    println!("XACE Runtime");
    println!("  cgs: {}", cli.cgs.display());
    println!("  port: {}", cli.port);
    println!("  engine_clients: {}", cli.engine_clients);
    if cli.no_control {
        println!("  control: disabled");
    } else {
        println!("  control_port: {}", cli.control_port);
    }
    println!("  start_paused: {}", cli.start_paused);
    println!("  tick_rate: {}", cli.tick_rate);
    println!("  mode: {}", summary.mode_id);
    println!("  schema: {}", summary.schema_version);
    println!("  cgs_hash: {}", summary.cgs_hash);
    println!(
        "  execution_plan: {:?} version={} hash={}",
        summary.phase_plan_source,
        summary.execution_plan_version,
        if summary.execution_plan_hash.is_empty() {
            "unresolved"
        } else {
            summary.execution_plan_hash.as_str()
        }
    );
    if let Some(path) = &summary.execution_plan_path {
        println!("  execution_plan_path: {}", path.display());
    }
    println!(
        "  parallel_group_policy: {} worker_threads={}",
        runtime.parallel_group_execution_policy().as_str(),
        runtime
            .parallel_group_execution_policy()
            .uses_worker_threads()
    );
    println!(
        "  actors: {} entities: {} phases: {}",
        summary.actor_count,
        summary.entity_count,
        runtime.phase_plan().len()
    );
}

fn print_done(
    runtime: &RuntimeOrchestrator,
    start: Instant,
    tick_count: u64,
    total_changes: u64,
    total_engine_inputs: u64,
    quiet: bool,
) {
    if quiet {
        return;
    }
    let elapsed = start.elapsed();
    let ticks_per_sec = if elapsed.is_zero() {
        0.0
    } else {
        tick_count as f64 / elapsed.as_secs_f64()
    };
    println!(
        "[done] ticks={} elapsed={:.3}s rate={:.0}/s alive={} changes={} inputs={}",
        tick_count,
        elapsed.as_secs_f64(),
        ticks_per_sec,
        runtime.alive_count(),
        total_changes,
        total_engine_inputs
    );
    if let Some(stats) = runtime.engine_bridge_stats() {
        println!(
            "[bridge] snapshots={} bytes={} input_packets={} malformed={} dropped={}",
            stats.snapshots_sent,
            stats.bytes_sent,
            stats.input_packets_received,
            stats.malformed_messages,
            stats.dropped_inputs
        );
    }
}

fn init_logger(level: &str) {
    let level_filter = match level {
        "error" => log::LevelFilter::Error,
        "warn" => log::LevelFilter::Warn,
        "debug" => log::LevelFilter::Debug,
        "trace" => log::LevelFilter::Trace,
        "off" => log::LevelFilter::Off,
        _ => log::LevelFilter::Info,
    };

    struct SimpleLogger(log::LevelFilter);
    impl log::Log for SimpleLogger {
        fn enabled(&self, metadata: &log::Metadata) -> bool {
            metadata.level() <= self.0
        }

        fn log(&self, record: &log::Record) {
            if self.enabled(record.metadata()) {
                eprintln!("[{}] {}", record.level(), record.args());
            }
        }

        fn flush(&self) {}
    }

    let _ = log::set_boxed_logger(Box::new(SimpleLogger(level_filter)))
        .map(|()| log::set_max_level(level_filter));
}
