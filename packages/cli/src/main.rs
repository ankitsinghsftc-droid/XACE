/*!
# XACE CLI — `xace`

Build, test, run, deploy, and diagnose XACE game backends.

```
xace build --game ./my_game --target unity
xace test  --suite determinism
xace run   --engine unity
xace deploy --target standalone     (stub — Phase 17)
xace doctor
```

## Architecture

The CLI is a thin orchestration layer. It does not duplicate logic:
- Python packages (gde, schema-factory, inference) are called via subprocess
- Rust packages (runtime-core, sgc) are called as library functions
- Determinism tests run via `cargo test` subprocess

## Exit Codes

```
0  — success
1  — internal / IO error
2  — validation error (user must fix game files)
3  — config error (game_config.yaml malformed or missing)
4  — doctor issue (environment not set up)
5  — build error (compilation failed)
6  — not implemented (planned but not yet built)
```
*/

use clap::{Parser, Subcommand};

mod commands;
mod config;
mod error;
mod python_bridge;

use error::CliError;

// ── CLI Definition ────────────────────────────────────────────────────────────

#[derive(Parser)]
#[command(
    name    = "xace",
    version = env!("CARGO_PKG_VERSION"),
    author  = "XACE Team",
    about   = "XACE Game Runtime Compiler — deterministic game backend toolchain",
    long_about = "Build, test, run, and deploy deterministic game simulations.\n\
                  All state changes are schema-driven and replay-guaranteed.\n\n\
                  Documentation: https://docs.xace.dev\n\
                  Source:        https://github.com/xace/xace",
    // Show help on error (not just "run --help")
    arg_required_else_help = true,
)]
struct Cli {
    /// Enable verbose diagnostic output (shows Python subprocess calls, etc.)
    #[arg(short, long, global = true)]
    verbose: bool,

    /// Disable ANSI colour output (useful in CI environments or log files)
    #[arg(long, global = true, env = "NO_COLOR")]
    no_color: bool,

    /// Output machine-readable JSON (for CI/CD pipelines and tooling)
    #[arg(long, global = true)]
    json: bool,

    #[command(subcommand)]
    command: XaceCommand,
}

#[derive(Subcommand)]
enum XaceCommand {
    /// Compile a game project into a target engine artifact
    #[command(alias = "b")]
    Build(commands::build::BuildArgs),

    /// Run the XACE test suite (determinism, unit, or integration)
    #[command(alias = "t")]
    Test(commands::test::TestArgs),

    /// Connect the XACE adapter to a running engine instance
    Run(commands::run::RunArgs),

    /// Deploy a built artifact to a distribution target
    Deploy(commands::deploy::DeployArgs),

    /// Diagnose the XACE development environment
    #[command(alias = "dr")]
    Doctor(commands::doctor::DoctorArgs),
}

// ── Entry Point ───────────────────────────────────────────────────────────────

fn main() {
    let cli = Cli::parse();

    let ctx = commands::Context {
        verbose: cli.verbose,
        no_color: cli.no_color,
        json: cli.json,
    };

    let result: Result<i32, CliError> = match cli.command {
        XaceCommand::Build(args) => commands::build::run(args, &ctx),
        XaceCommand::Test(args) => commands::test::run(args, &ctx),
        XaceCommand::Run(args) => commands::run::run(args, &ctx),
        XaceCommand::Deploy(args) => commands::deploy::run(args, &ctx),
        XaceCommand::Doctor(args) => commands::doctor::run(args, &ctx),
    };

    match result {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            if cli.json {
                let message = e.to_string();
                let code = e.exit_code();
                // Machine-readable error output
                let obj = serde_json::json!({
                    "ok":    false,
                    "error": message,
                    "code":  code,
                });
                eprintln!("{}", serde_json::to_string_pretty(&obj).unwrap_or_default());
            } else {
                eprintln!(
                    "{}{}{}",
                    error_prefix(cli.no_color),
                    e,
                    error_suffix(cli.no_color)
                );
            }
            std::process::exit(e.exit_code());
        }
    }
}

fn error_prefix(no_color: bool) -> &'static str {
    if no_color {
        "error: "
    } else {
        "\x1b[31merror\x1b[0m: "
    }
}

fn error_suffix(_no_color: bool) -> &'static str {
    ""
}
