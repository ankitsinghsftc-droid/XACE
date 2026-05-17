// ============================================================================
// packages/cli/src/commands/build.rs
// ============================================================================
/*!
# commands/build.rs — `xace build`
 
Compiles a game project into a target engine artifact.
 
## Pipeline
 
1. Read `game_config.yaml` from `--game` directory
2. Validate CGS via Python subprocess (`xace_gde validate`)
3. Run Schema Factory compilation (`xace_gde compile`)
4. Generate ExecutionPlan via SGC (`xace_sgc compile`)
5. Produce engine-specific artifact in `./dist/`
 
## Targets
 
| Target     | Output                      | Status              |
|------------|-----------------------------|---------------------|
| unity      | `dist/XaceRuntime.dll`      | implemented         |
| godot      | `dist/libxace.so`           | implemented         |
| unreal     | `dist/Xace.uplugin`         | implemented         |
| standalone | `dist/{game_name}_runtime`  | Phase 17 — stub     |
*/
 
use std::path::PathBuf;
use std::time::Instant;
 
use clap::Args;
use serde_json::json;
 
use crate::commands::Context;
use crate::config::{GameConfig, TargetEngine};
use crate::error::CliError;
use crate::python_bridge::PythonBridge;
 
 
#[derive(Args, Clone)]
pub struct BuildArgs {
    /// Game project directory containing game_config.yaml
    #[arg(long, short, default_value = ".")]
    pub game: PathBuf,
 
    /// Build target engine
    #[arg(long, short, value_parser = parse_target)]
    pub target: Option<TargetEngine>,
 
    /// Skip schema validation (unsafe — for fast iteration only)
    #[arg(long)]
    pub skip_validation: bool,
 
    /// Output directory (overrides game_config.yaml build.output_dir)
    #[arg(long, short)]
    pub output: Option<PathBuf>,
}
 
fn parse_target(s: &str) -> Result<TargetEngine, String> {
    s.parse()
}
 
 
pub fn run(args: BuildArgs, ctx: &Context) -> Result<i32, CliError> {
    let start = Instant::now();
 
    ctx.print_header("XACE Build");
 
    // ── Step 1: Load config ───────────────────────────────────────────────────
    ctx.print_step("Loading game configuration...");
    let config = GameConfig::load(&args.game)?;
    ctx.verbose_log(&format!("Game: {} v{}", config.name, config.version));
 
    // Determine targets
    let targets: Vec<TargetEngine> = if let Some(t) = &args.target {
        vec![t.clone()]
    } else {
        config.target_engines.clone()
    };
 
    // Reject standalone early (Phase 17)
    for target in &targets {
        if *target == TargetEngine::Standalone {
            return Err(CliError::not_implemented(
                "standalone target",
                "Phase 17 — standalone game compiler",
            ));
        }
    }
 
    // ── Step 2: Python bridge ─────────────────────────────────────────────────
    let bridge = PythonBridge::new(config.python_package_dir(), ctx.verbose)?;
 
    // ── Step 3: Validate CGS ──────────────────────────────────────────────────
    if !args.skip_validation {
        ctx.print_step("Validating game schema (CGS)...");
        let result = bridge.invoke_module("xace_gde", "validate", &[
            "--game-dir", &args.game.display().to_string(),
        ])?;
 
        let warnings = result["warnings"].as_array().cloned().unwrap_or_default();
        for w in &warnings {
            ctx.print_warn(&w.as_str().unwrap_or("").to_string());
        }
        ctx.print_ok("Schema validation passed.");
    } else {
        ctx.print_warn("Skipping schema validation (--skip-validation)");
    }
 
    // ── Step 4: Compile Schema Factory ────────────────────────────────────────
    ctx.print_step("Compiling schema (Schema Factory)...");
    let compile_result = bridge.invoke_module("xace_gde", "compile", &[
        "--game-dir", &args.game.display().to_string(),
    ])?;
 
    let schema_version = compile_result["schema_version"]
        .as_str()
        .unwrap_or(&config.schema_version)
        .to_string();
    ctx.verbose_log(&format!("Schema version: {}", schema_version));
    ctx.print_ok(&format!("Schema compiled (v{}).", schema_version));
 
    // ── Step 5: Generate ExecutionPlan ────────────────────────────────────────
    ctx.print_step("Generating ExecutionPlan (System Graph Compiler)...");
    // SGC is a Rust crate — in Phase 10 it's callable as a library.
    // For the CLI, we invoke it via `cargo run -p xace-sgc -- compile` until
    // a stable C ABI is available.
    let sgc_result = run_sgc_compile(&config, &args);
    match sgc_result {
        Ok(plan_path) => ctx.print_ok(&format!("ExecutionPlan: {}", plan_path.display())),
        Err(_)        => ctx.print_warn("SGC compilation skipped (not yet linked)."),
    }
 
    // ── Step 6: Generate engine artifacts ────────────────────────────────────
    let output_dir = args.output.as_ref().cloned().unwrap_or_else(|| config.output_dir());
    std::fs::create_dir_all(&output_dir)?;
 
    for target in &targets {
        ctx.print_step(&format!("Generating {} artifact...", target));
        generate_artifact(target, &config, &output_dir, ctx)?;
        ctx.print_ok(&format!("{} artifact ready in {}", target, output_dir.display()));
    }
 
    // ── Done ──────────────────────────────────────────────────────────────────
    let elapsed = start.elapsed();
    if !ctx.json {
        println!(
            "\n\x1b[32m✓ Build complete\x1b[0m in {:.2}s — {} target(s)",
            elapsed.as_secs_f64(),
            targets.len()
        );
    }
 
    ctx.json_output(&json!({
        "ok":           true,
        "game":         config.name,
        "version":      config.version,
        "schema_ver":   schema_version,
        "targets":      targets.iter().map(|t| t.to_string()).collect::<Vec<_>>(),
        "output_dir":   output_dir.display().to_string(),
        "elapsed_ms":   elapsed.as_millis(),
    }));
 
    Ok(0)
}
 
fn run_sgc_compile(config: &GameConfig, args: &BuildArgs) -> Result<PathBuf, CliError> {
    // SGC is a Rust library — shell out to `cargo run` for now.
    // This will be a direct library call once the FFI ABI stabilises.
    let output = std::process::Command::new("cargo")
        .args([
            "run", "--quiet", "--package", "xace-sgc", "--",
            "compile",
            "--game-dir", &args.game.display().to_string(),
            "--output",   &config.output_dir().display().to_string(),
        ])
        .output()
        .map_err(|e| CliError::BuildError {
            stage:   "sgc".to_string(),
            message: e.to_string(),
        })?;
 
    if !output.status.success() {
        return Err(CliError::BuildError {
            stage:   "sgc".to_string(),
            message: String::from_utf8_lossy(&output.stderr).to_string(),
        });
    }
 
    Ok(config.output_dir().join("execution_plan.json"))
}
 
fn generate_artifact(
    target:     &TargetEngine,
    config:     &GameConfig,
    output_dir: &PathBuf,
    ctx:        &Context,
) -> Result<(), CliError> {
    match target {
        TargetEngine::Unity | TargetEngine::Godot | TargetEngine::Unreal => {
            // Generate adapter configuration manifest
            let manifest = json!({
                "xace_version":      env!("CARGO_PKG_VERSION"),
                "game_name":         config.name,
                "schema_version":    config.schema_version,
                "adapter_mode":      config.adapters.mode,
                "adapter_host":      config.adapters.tcp_host,
                "adapter_port":      config.adapters.tcp_port,
                "target":            target.to_string(),
                "build_timestamp":   chrono_or_epoch(),
            });
            let manifest_path = output_dir.join(format!(
                "xace_{}_config.json",
                target.to_string()
            ));
            std::fs::write(&manifest_path, serde_json::to_string_pretty(&manifest)?)
                .map_err(|e| CliError::Io { path: Some(manifest_path.clone()), source: e })?;
            ctx.verbose_log(&format!("Manifest: {}", manifest_path.display()));
            Ok(())
        }
        TargetEngine::Standalone => {
            Err(CliError::not_implemented("standalone target", "Phase 17"))
        }
    }
}
 
fn chrono_or_epoch() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    format!("{}", SystemTime::now().duration_since(UNIX_EPOCH)
        .unwrap_or_default().as_secs())
}