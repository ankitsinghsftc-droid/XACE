use std::error::Error;
use std::fs;
use std::path::PathBuf;

use xace_network_core::chaos::{run_network_chaos_matrix, NetworkChaosMatrixConfig};

fn main() -> Result<(), Box<dyn Error>> {
    let args = Args::parse(std::env::args().skip(1))?;
    let mut config = if args.quick {
        NetworkChaosMatrixConfig::quick()
    } else {
        NetworkChaosMatrixConfig::certification_60_minutes()
    };
    if let Some(ticks) = args.duration_ticks {
        config.duration_ticks = ticks;
    } else if let Some(minutes) = args.duration_minutes {
        config.duration_ticks = minutes
            .saturating_mul(60)
            .saturating_mul(config.tick_rate_hz as u64);
    }
    if let Some(client_counts) = args.client_counts {
        config.client_counts = client_counts;
    }
    if let Some(tick_rate_hz) = args.tick_rate_hz {
        config.tick_rate_hz = tick_rate_hz;
        if args.duration_ticks.is_none() {
            if let Some(minutes) = args.duration_minutes {
                config.duration_ticks = minutes
                    .saturating_mul(60)
                    .saturating_mul(config.tick_rate_hz as u64);
            }
        }
    }
    if let Some(seed) = args.seed {
        config.seed = seed;
    }

    let started = std::time::Instant::now();
    let report = run_network_chaos_matrix(config)?;
    let elapsed_ms = started.elapsed().as_millis();
    let output = args.output.unwrap_or_else(default_output_path);
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&output, serde_json::to_vec_pretty(&report)?)?;
    eprintln!(
        "network chaos proof wrote {} in {} ms",
        output.display(),
        elapsed_ms
    );
    println!("{}", serde_json::to_string(&report)?);
    if args.require_certification && !report.certification_complete {
        return Err("network chaos report did not satisfy X10-043 certification criteria".into());
    }
    if !report.ok {
        return Err("network chaos report failed required event/desync checks".into());
    }
    Ok(())
}

#[derive(Debug, Default)]
struct Args {
    output: Option<PathBuf>,
    duration_minutes: Option<u64>,
    duration_ticks: Option<u64>,
    client_counts: Option<Vec<usize>>,
    tick_rate_hz: Option<u32>,
    seed: Option<u64>,
    quick: bool,
    require_certification: bool,
}

impl Args {
    fn parse<I>(mut raw: I) -> Result<Self, Box<dyn Error>>
    where
        I: Iterator<Item = String>,
    {
        let mut args = Args::default();
        while let Some(arg) = raw.next() {
            match arg.as_str() {
                "--output" => {
                    args.output = Some(PathBuf::from(require_value(&mut raw, "--output")?))
                }
                "--duration-minutes" => {
                    args.duration_minutes =
                        Some(require_value(&mut raw, "--duration-minutes")?.parse()?)
                }
                "--duration-ticks" => {
                    args.duration_ticks =
                        Some(require_value(&mut raw, "--duration-ticks")?.parse()?)
                }
                "--client-counts" => {
                    let value = require_value(&mut raw, "--client-counts")?;
                    let counts = value
                        .split(',')
                        .map(|part| part.trim().parse::<usize>())
                        .collect::<Result<Vec<_>, _>>()?;
                    args.client_counts = Some(counts);
                }
                "--tick-rate-hz" => {
                    args.tick_rate_hz = Some(require_value(&mut raw, "--tick-rate-hz")?.parse()?)
                }
                "--seed" => args.seed = Some(require_value(&mut raw, "--seed")?.parse()?),
                "--quick" => args.quick = true,
                "--require-certification" => args.require_certification = true,
                "--help" | "-h" => {
                    print_help();
                    std::process::exit(0);
                }
                other => return Err(format!("unknown argument: {other}").into()),
            }
        }
        Ok(args)
    }
}

fn require_value<I>(raw: &mut I, flag: &str) -> Result<String, Box<dyn Error>>
where
    I: Iterator<Item = String>,
{
    raw.next()
        .ok_or_else(|| format!("{flag} requires a value").into())
}

fn default_output_path() -> PathBuf {
    let run_id = format!(
        "run-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .unwrap_or_default()
    );
    PathBuf::from(".xace")
        .join("proof")
        .join("network-chaos")
        .join(run_id)
        .join("network_chaos_report.json")
}

fn print_help() {
    println!(
        "network_chaos_proof --output <path> [--quick|--duration-minutes 60|--duration-ticks N] [--tick-rate-hz 60] [--client-counts 4,8,16] [--seed N] [--require-certification]"
    );
}
