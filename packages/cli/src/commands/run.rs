// ============================================================================
// packages/cli/src/commands/run.rs
// ============================================================================

use std::path::PathBuf;

use crate::commands::Context;
use crate::config::GameConfig;
use crate::error::CliError;

#[derive(clap::Args, Clone)]
pub struct RunArgs {
    /// Engine to connect to
    #[arg(long, short, value_parser = ["unity", "godot", "unreal"],
          default_value = "unity")]
    pub engine: String,

    /// Game project directory
    #[arg(long, default_value = ".")]
    pub game: PathBuf,

    /// Override adapter host
    #[arg(long)]
    pub host: Option<String>,

    /// Override adapter port
    #[arg(long)]
    pub port: Option<u16>,
}

pub fn run(args: RunArgs, ctx: &Context) -> Result<i32, CliError> {
    ctx.print_header("XACE Run — Adapter Connect");

    let config = GameConfig::load(&args.game)?;
    let host = args.host.as_deref().unwrap_or(&config.adapters.tcp_host);
    let port = args.port.unwrap_or(config.adapters.tcp_port);

    ctx.print_step(&format!(
        "Connecting {} adapter to {}:{}...",
        args.engine, host, port
    ));
    ctx.print_step("(Engine must already be running with the XACE plugin active)");

    // Test TCP connectivity before launching the full adapter
    match test_tcp_connection(host, port) {
        Ok(()) => {
            ctx.print_ok(&format!("Engine reachable at {}:{}", host, port));
        }
        Err(_) => {
            return Err(CliError::BuildError {
                stage: "adapter-connect".to_string(),
                message: format!(
                    "Cannot connect to engine at {}:{}. \n\
                     Is the engine running with the XACE plugin active? \n\
                     Check: engine adapter config → host: {}, port: {}",
                    host, port, host, port
                ),
            });
        }
    }

    // Launch the engine adapter process
    ctx.print_step("Starting XACE engine adapter...");
    let status = std::process::Command::new("cargo")
        .args([
            "run",
            "--quiet",
            "--package",
            "xace-engine-adapter",
            "--",
            "--engine",
            &args.engine,
            "--host",
            host,
            "--port",
            &port.to_string(),
        ])
        .status()
        .map_err(|e| CliError::BuildError {
            stage: "engine-adapter".to_string(),
            message: e.to_string(),
        })?;

    Ok(if status.success() { 0 } else { 1 })
}

fn test_tcp_connection(host: &str, port: u16) -> Result<(), std::io::Error> {
    use std::net::TcpStream;
    let addr = format!("{}:{}", host, port);
    TcpStream::connect_timeout(
        &addr
            .parse()
            .map_err(|_| std::io::Error::new(std::io::ErrorKind::AddrNotAvailable, "bad addr"))?,
        std::time::Duration::from_secs(2),
    )
    .map(|_| ())
}
