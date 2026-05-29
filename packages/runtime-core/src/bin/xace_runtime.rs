//! Standalone XACE runtime with optional live engine bridge.

use std::path::PathBuf;
use std::process;
use std::time::{Duration, Instant};

use clap::Parser;

use xace_runtime_core::runtime_orchestrator::{RuntimeConfig, RuntimeOrchestrator};
use xace_runtime_core::state_printer::PrinterOpts;

#[derive(Parser, Debug)]
#[command(
    name = "xace_runtime",
    version = "0.1.0-phase15",
    about = "XACE deterministic runtime with live engine bridge"
)]
struct Cli {
    #[arg(long)]
    cgs: PathBuf,

    #[arg(long, default_value_t = 7777)]
    port: u16,

    #[arg(long)]
    no_wait: bool,

    #[arg(long, default_value_t = 0)]
    wait_secs: u64,

    #[arg(long, default_value_t = 0)]
    ticks: u64,

    #[arg(long, default_value_t = 60)]
    print_every: u64,

    #[arg(long, default_value_t = 60)]
    tick_rate: u32,

    #[arg(long)]
    verbose: bool,

    #[arg(long)]
    quiet: bool,

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
    if !cli.cgs.exists() {
        anyhow::bail!("CGS file does not exist: {}", cli.cgs.display());
    }

    let mut config = RuntimeConfig::default();
    config.bridge.tick_rate = cli.tick_rate;
    let mut runtime = RuntimeOrchestrator::initialise_with_config(&cli.cgs, config)?;
    print_startup(&cli, &runtime);

    let engine_requested = !cli.no_wait;
    let connected = if cli.no_wait {
        false
    } else if cli.wait_secs == 0 {
        runtime.connect_engine(cli.port)?;
        true
    } else {
        runtime.try_connect_engine(cli.port, cli.wait_secs)?
    };
    if !cli.quiet {
        if connected {
            println!("[ready] engine connected");
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

    loop {
        if cli.ticks > 0 && tick_count >= cli.ticks {
            break;
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

fn print_startup(cli: &Cli, runtime: &RuntimeOrchestrator) {
    if cli.quiet {
        return;
    }
    let summary = runtime.spawn_summary();
    println!("XACE Runtime");
    println!("  cgs: {}", cli.cgs.display());
    println!("  port: {}", cli.port);
    println!("  tick_rate: {}", cli.tick_rate);
    println!("  mode: {}", summary.mode_id);
    println!("  schema: {}", summary.schema_version);
    println!("  cgs_hash: {}", summary.cgs_hash);
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
