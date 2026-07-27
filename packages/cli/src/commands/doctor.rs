/*!
# commands/doctor.rs — Environment Diagnostics

`xace doctor` checks every prerequisite for XACE development and tells
the developer exactly what is missing, with a specific fix instruction.

## Sample Output

```
Checking XACE development environment...

Runtime
───────────
✓ Rust toolchain: rustc 1.78.0 (stable-x86_64-apple-darwin)
✓ Cargo: cargo 1.78.0 (stable)
✓ Python: Python 3.12.2

Python Packages
───────────────
✓ xace_gde: 0.1.0
✗ xace_inference: not installed
    → pip install -e packages/inference from the XACE root

LLM API Keys
────────────
✓ ANTHROPIC_API_KEY: configured (sk-ant-...a1b2)
⚠ DEEPSEEK_API_KEY: not set (optional — needed for TIER_L cheap routing)
⚠ OPENAI_API_KEY: not set (optional)

Local Models
────────────
✓ Ollama: running at http://localhost:11434
✓ llama3.1:70b: loaded (TIER_M local routing ready)
⚠ qwen2.5:72b: not loaded (run: ollama pull qwen2.5:72b)

Engine Adapters
───────────────
⚠ Unity adapter: not found
    → Copy adapters/unity/ to your Unity project Assets/XACE/

System
──────
✓ Disk space: 48.2 GB free (minimum 5 GB required)

Status: 1 error, 4 warnings. Run with --verbose for full details.
```
*/

use std::path::PathBuf;

use clap::Args;

use crate::commands::Context;
use crate::error::{print_header, print_issue, CliError, DoctorIssue, Severity};

// ── Args ──────────────────────────────────────────────────────────────────────

#[derive(Args, Clone)]
pub struct DoctorArgs {
    /// Check only a specific category (runtime|python|keys|local|adapters|system)
    #[arg(long)]
    pub only: Option<String>,
}

// ── Entry Point ───────────────────────────────────────────────────────────────

pub fn run(args: DoctorArgs, ctx: &Context) -> Result<i32, CliError> {
    if !ctx.json {
        println!("Checking XACE development environment...");
    }

    let filter = args.only.as_deref();
    let mut all_issues: Vec<DoctorIssue> = Vec::new();

    if filter.is_none() || filter == Some("runtime") {
        if !ctx.json {
            print_header("Runtime", ctx.no_color);
        }
        let issues = check_runtime();
        if !ctx.json {
            for issue in &issues {
                print_issue(issue, ctx.no_color);
            }
        }
        all_issues.extend(issues);
    }

    if filter.is_none() || filter == Some("python") {
        if !ctx.json {
            print_header("Python Packages", ctx.no_color);
        }
        let issues = check_python_packages(ctx.verbose);
        if !ctx.json {
            for issue in &issues {
                print_issue(issue, ctx.no_color);
            }
        }
        all_issues.extend(issues);
    }

    if filter.is_none() || filter == Some("keys") {
        if !ctx.json {
            print_header("LLM API Keys", ctx.no_color);
        }
        let issues = check_api_keys();
        if !ctx.json {
            for issue in &issues {
                print_issue(issue, ctx.no_color);
            }
        }
        all_issues.extend(issues);
    }

    if filter.is_none() || filter == Some("local") {
        if !ctx.json {
            print_header("Local Models", ctx.no_color);
        }
        let issues = check_local_models();
        if !ctx.json {
            for issue in &issues {
                print_issue(issue, ctx.no_color);
            }
        }
        all_issues.extend(issues);
    }

    if filter.is_none() || filter == Some("adapters") {
        if !ctx.json {
            print_header("Engine Adapters", ctx.no_color);
        }
        let issues = check_engine_adapters();
        if !ctx.json {
            for issue in &issues {
                print_issue(issue, ctx.no_color);
            }
        }
        all_issues.extend(issues);
    }

    if filter.is_none() || filter == Some("system") {
        if !ctx.json {
            print_header("System", ctx.no_color);
        }
        let issues = check_system();
        if !ctx.json {
            for issue in &issues {
                print_issue(issue, ctx.no_color);
            }
        }
        all_issues.extend(issues);
    }

    // ── Summary ───────────────────────────────────────────────────────────────
    let errors = all_issues
        .iter()
        .filter(|i| i.severity == Severity::Error)
        .count();
    let warnings = all_issues
        .iter()
        .filter(|i| i.severity == Severity::Warning)
        .count();

    if ctx.json {
        let report = serde_json::json!({
            "ok":       errors == 0,
            "errors":   errors,
            "warnings": warnings,
            "checks":   all_issues.iter().map(|i| serde_json::json!({
                "name":    i.name,
                "status":  format!("{:?}", i.severity).to_lowercase(),
                "message": i.message,
                "fix":     i.fix_hint,
            })).collect::<Vec<_>>(),
        });
        ctx.json_output(&report);
    } else {
        println!();
        if errors == 0 && warnings == 0 {
            println!("Status: \x1b[32mall checks passed\x1b[0m.");
        } else {
            let status = format!("Status: {} error(s), {} warning(s).", errors, warnings);
            if errors > 0 {
                if ctx.no_color {
                    println!("{}", status);
                } else {
                    println!("\x1b[31m{}\x1b[0m", status);
                }
            } else {
                if ctx.no_color {
                    println!("{}", status);
                } else {
                    println!("\x1b[33m{}\x1b[0m", status);
                }
            }
            if errors > 0 {
                println!("Fix errors above before running `xace build`.");
            }
        }
    }

    Ok(if errors > 0 { 4 } else { 0 })
}

// ── Check Functions ───────────────────────────────────────────────────────────

fn check_runtime() -> Vec<DoctorIssue> {
    let mut issues = Vec::new();

    // Rust toolchain
    match run_command("rustc", &["--version"]) {
        Some(version) => {
            issues.push(DoctorIssue::ok("Rust toolchain", version));
        }
        None => {
            issues.push(DoctorIssue::error(
                "Rust toolchain",
                "rustc not found",
                "Install Rust: https://rustup.rs",
            ));
        }
    }

    // Cargo
    match run_command("cargo", &["--version"]) {
        Some(version) => issues.push(DoctorIssue::ok("Cargo", version)),
        None => issues.push(DoctorIssue::error(
            "Cargo",
            "not found",
            "Install via rustup: rustup update",
        )),
    }

    // Python
    let python_bins = &["python3", "python"];
    let mut python_found = false;
    for bin in python_bins {
        if let Some(version) = run_command(bin, &["--version"]) {
            if version.contains("3.1") || version.contains("3.2") {
                issues.push(DoctorIssue::ok("Python", version));
                python_found = true;
                break;
            }
        }
    }
    if !python_found {
        issues.push(DoctorIssue::error(
            "Python",
            "Python 3.11+ not found",
            "Install Python 3.11 or later: https://python.org/downloads",
        ));
    }

    issues
}

fn check_python_packages(_verbose: bool) -> Vec<DoctorIssue> {
    let mut issues = Vec::new();

    // Detect Python binary for checking packages
    let python_bin = find_python_bin();

    let packages: &[(&str, &str)] = &[
        ("xace_gde", "packages/gde"),
        ("xace_inference", "packages/inference"),
    ];

    for (module, source) in packages {
        let importable = python_bin
            .as_ref()
            .map(|py| {
                std::process::Command::new(py)
                    .args(["-c", &format!("import {}", module)])
                    .output()
                    .map(|o| o.status.success())
                    .unwrap_or(false)
            })
            .unwrap_or(false);

        if importable {
            // Try to get version
            let version = python_bin
                .as_ref()
                .and_then(|py| {
                    std::process::Command::new(py)
                        .args([
                            "-c",
                            &format!(
                                "import {m}; print(getattr({m}, '__version__', 'installed'))",
                                m = module
                            ),
                        ])
                        .output()
                        .ok()
                        .filter(|o| o.status.success())
                        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
                })
                .unwrap_or_else(|| "installed".to_string());
            issues.push(DoctorIssue::ok(*module, version));
        } else {
            issues.push(DoctorIssue::error(
                *module,
                "not installed",
                &format!("Run from XACE root: pip install -e {}", source),
            ));
        }
    }

    issues
}

fn check_api_keys() -> Vec<DoctorIssue> {
    let mut issues = Vec::new();

    let keys: &[(&str, &str, bool, &str)] = &[
        // (env_var, display_name, required, purpose)
        (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEY",
            true,
            "Required for TIER_XL (Opus) and TIER_L fallback",
        ),
        (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
            false,
            "Needed for TIER_L cheap routing (DeepSeek V4 Pro)",
        ),
        (
            "OPENAI_API_KEY",
            "OPENAI_API_KEY",
            false,
            "Needed for OpenAI TIER_XL fallback",
        ),
        (
            "XACE_ZAI_API_KEY",
            "XACE_ZAI_API_KEY",
            false,
            "Needed for GLM-5.1 routing (Z.AI)",
        ),
    ];

    for &(var, name, required, purpose) in keys {
        match std::env::var(var) {
            Ok(val) if !val.is_empty() => {
                // Show last 4 chars of key for confirmation without exposing the key
                let preview = if val.len() > 8 {
                    format!("...{}", &val[val.len() - 4..])
                } else {
                    "set".to_string()
                };
                issues.push(DoctorIssue::ok(name, preview));
            }
            _ => {
                if required {
                    issues.push(DoctorIssue::error(
                        name,
                        "not set",
                        &format!("Set in your shell: export {}=sk-... ({})", var, purpose),
                    ));
                } else {
                    issues.push(DoctorIssue::warn(
                        name,
                        &format!("not set (optional — {})", purpose),
                        &format!("export {}=your-api-key", var),
                    ));
                }
            }
        }
    }

    issues
}

fn check_local_models() -> Vec<DoctorIssue> {
    let mut issues = Vec::new();

    // Check if Ollama is running
    let ollama_url = "http://localhost:11434";
    let ollama_running = reqwest_or_curl_check(&format!("{}/api/tags", ollama_url));

    if !ollama_running {
        issues.push(DoctorIssue::warn(
            "Ollama",
            "not running at http://localhost:11434",
            "Install Ollama: https://ollama.ai — then run: ollama serve",
        ));
        return issues;
    }

    issues.push(DoctorIssue::ok(
        "Ollama",
        "running at http://localhost:11434",
    ));

    // Check default TIER_M models
    let default_models = &["llama3.1:70b", "qwen2.5:72b"];
    let loaded_models = get_ollama_models();

    for model in default_models {
        if loaded_models.iter().any(|m: &String| m == model) {
            issues.push(DoctorIssue::ok(
                *model,
                "loaded (TIER_M local routing ready)",
            ));
        } else {
            issues.push(DoctorIssue::warn(
                *model,
                "not loaded",
                &format!("Run: ollama pull {}", model),
            ));
        }
    }

    issues
}

fn check_engine_adapters() -> Vec<DoctorIssue> {
    let mut issues = Vec::new();

    // Look for adapter files relative to the XACE root
    // In a real installation, these would be at a configured path
    let adapters: &[(&str, &str)] = &[
        ("Unity adapter", "adapters/unity/XaceEmbedded.cs"),
        ("Godot adapter", "adapters/godot/xace_adapter.gd"),
    ];

    for &(name, path) in adapters {
        // Check relative to CARGO_MANIFEST_DIR/..
        let abs_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap_or_else(|| std::path::Path::new("."))
            .join(path);

        if abs_path.exists() {
            issues.push(DoctorIssue::ok(name, abs_path.display().to_string()));
        } else {
            issues.push(DoctorIssue::warn(
                name,
                "not found in standard location",
                &format!(
                    "Copy {0} to your engine project, or run: xace build --target unity",
                    path
                ),
            ));
        }
    }

    issues
}

fn check_system() -> Vec<DoctorIssue> {
    let mut issues = Vec::new();

    // Disk space — minimum 5 GB for game assets + build artifacts
    let gb_free = available_disk_gb(".");
    match gb_free {
        Some(gb) if gb >= 5.0 => {
            issues.push(DoctorIssue::ok(
                "Disk space",
                format!("{:.1} GB free (minimum 5 GB required)", gb),
            ));
        }
        Some(gb) => {
            issues.push(DoctorIssue::error(
                "Disk space",
                &format!("{:.1} GB free — insufficient (need 5 GB)", gb),
                "Free up disk space before building",
            ));
        }
        None => {
            issues.push(DoctorIssue::warn(
                "Disk space",
                "could not determine available space",
                "Ensure you have at least 5 GB free before building",
            ));
        }
    }

    issues
}

// ── System Helpers ────────────────────────────────────────────────────────────

fn run_command(bin: &str, args: &[&str]) -> Option<String> {
    std::process::Command::new(bin)
        .args(args)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| {
            // Some binaries print version to stderr
            let out = String::from_utf8_lossy(&o.stdout).trim().to_string();
            let err = String::from_utf8_lossy(&o.stderr).trim().to_string();
            if out.is_empty() {
                err
            } else {
                out
            }
        })
}

fn find_python_bin() -> Option<String> {
    if let Ok(p) = std::env::var("XACE_PYTHON") {
        return Some(p);
    }
    if which::which("python3").is_ok() {
        return Some("python3".to_string());
    }
    if which::which("python").is_ok() {
        return Some("python".to_string());
    }
    None
}

fn reqwest_or_curl_check(url: &str) -> bool {
    // Use curl as a portable HTTP check — no reqwest dep in CLI crate
    std::process::Command::new("curl")
        .args(["--silent", "--max-time", "2", "--fail", url])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

fn get_ollama_models() -> Vec<String> {
    let output = std::process::Command::new("curl")
        .args([
            "--silent",
            "--max-time",
            "2",
            "http://localhost:11434/api/tags",
        ])
        .output()
        .ok();

    output
        .and_then(|o| serde_json::from_slice::<serde_json::Value>(&o.stdout).ok())
        .and_then(|v| v["models"].as_array().cloned())
        .unwrap_or_default()
        .iter()
        .filter_map(|m| m["name"].as_str().map(|s| s.to_string()))
        .collect()
}

fn available_disk_gb(_path: &str) -> Option<f64> {
    // Cross-platform via `df`
    #[cfg(unix)]
    {
        let output = std::process::Command::new("df")
            .args(["-k", _path])
            .output()
            .ok()?;
        let text = String::from_utf8_lossy(&output.stdout);
        let line = text.lines().nth(1)?;
        let avail = line.split_whitespace().nth(3)?;
        let kb: f64 = avail.parse().ok()?;
        Some(kb / 1_048_576.0) // KB → GB
    }
    #[cfg(windows)]
    {
        let output = std::process::Command::new("wmic")
            .args(["logicaldisk", "get", "freespace"])
            .output()
            .ok()?;
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines().skip(1) {
            let s = line.trim();
            if !s.is_empty() {
                let bytes: f64 = s.parse().ok()?;
                return Some(bytes / 1_073_741_824.0); // bytes → GB
            }
        }
        None
    }
    #[cfg(not(any(unix, windows)))]
    {
        None
    }
}
