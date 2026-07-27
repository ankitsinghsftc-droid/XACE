// ============================================================================
// packages/cli/src/commands/test.rs
// ============================================================================

use std::path::PathBuf;
use std::time::Instant;

use crate::commands::Context;
use crate::error::CliError;

#[derive(clap::Args, Clone)]
pub struct TestArgs {
    /// Test suite to run
    #[arg(long, short, default_value = "all",
          value_parser = ["all", "determinism", "unit", "integration"])]
    pub suite: String,

    /// Produce a JSON report file at this path
    #[arg(long)]
    pub report: Option<PathBuf>,

    /// Fail fast — stop at first test failure
    #[arg(long)]
    pub fail_fast: bool,
}

pub fn run(args: TestArgs, ctx: &Context) -> Result<i32, CliError> {
    ctx.print_header("XACE Test Suite");
    ctx.print_step(&format!("Running suite: {}", args.suite));

    let start = Instant::now();
    let mut total_passed = 0u32;
    let mut total_failed = 0u32;
    let mut total_ignored = 0u32;

    // ── Rust tests ────────────────────────────────────────────────────────────
    if args.suite == "all" || args.suite == "determinism" || args.suite == "unit" {
        let filter = match args.suite.as_str() {
            "determinism" => Some("determinism"),
            _ => None,
        };

        ctx.print_step("Running Rust tests (cargo test)...");
        let (passed, failed, ignored) = run_cargo_tests(filter, args.fail_fast, ctx)?;
        total_passed += passed;
        total_failed += failed;
        total_ignored += ignored;

        if failed > 0 && args.fail_fast {
            return finish_tests(passed, failed, ignored, start, args.report.as_deref(), ctx);
        }
    }

    // ── Python tests ──────────────────────────────────────────────────────────
    if args.suite == "all" || args.suite == "unit" {
        ctx.print_step("Running Python tests (pytest)...");
        let (passed, failed) = run_pytest(args.fail_fast, ctx);
        total_passed += passed;
        total_failed += failed;
    }

    finish_tests(
        total_passed,
        total_failed,
        total_ignored,
        start,
        args.report.as_deref(),
        ctx,
    )
}

fn run_cargo_tests(
    filter: Option<&str>,
    fail_fast: bool,
    ctx: &Context,
) -> Result<(u32, u32, u32), CliError> {
    let mut cmd = std::process::Command::new("cargo");
    cmd.args(["test", "--workspace"]);
    if let Some(f) = filter {
        cmd.args(["--", f]);
    }
    if fail_fast {
        cmd.args(["--", "--fail-fast"]);
    }

    let output = cmd.output().map_err(|e| CliError::BuildError {
        stage: "cargo test".to_string(),
        message: e.to_string(),
    })?;

    let text = String::from_utf8_lossy(&output.stdout).to_string()
        + &String::from_utf8_lossy(&output.stderr);

    // Parse cargo test summary line: "test result: ok. N passed; M failed; K ignored"
    let (passed, failed, ignored) = parse_cargo_summary(&text);

    if passed > 0 || failed == 0 {
        ctx.print_ok(&format!(
            "{} passed, {} failed, {} ignored",
            passed, failed, ignored
        ));
    } else {
        ctx.print_error(&format!("{} failed (cargo test)", failed));
        if ctx.verbose {
            for line in text.lines().filter(|l| l.contains("FAILED")) {
                ctx.print_error(line);
            }
        }
    }

    Ok((passed, failed, ignored))
}

fn run_pytest(fail_fast: bool, ctx: &Context) -> (u32, u32) {
    let python = if which::which("python3").is_ok() {
        "python3"
    } else {
        "python"
    };
    let mut cmd = std::process::Command::new(python);
    cmd.args(["-m", "pytest", "packages/", "--tb=short", "-q"]);
    if fail_fast {
        cmd.arg("-x");
    }

    let output = match cmd.output() {
        Ok(o) => o,
        Err(_) => return (0, 0),
    };

    let text = String::from_utf8_lossy(&output.stdout).to_string();
    if ctx.verbose {
        for line in text.lines() {
            ctx.verbose_log(line);
        }
    }
    parse_pytest_summary(&text)
}

fn parse_cargo_summary(text: &str) -> (u32, u32, u32) {
    for line in text.lines() {
        if line.starts_with("test result:") {
            // "test result: ok. 127 passed; 0 failed; 2 ignored"
            let passed = extract_number(line, "passed");
            let failed = extract_number(line, "failed");
            let ignored = extract_number(line, "ignored");
            return (passed, failed, ignored);
        }
    }
    (0, 0, 0)
}

fn parse_pytest_summary(text: &str) -> (u32, u32) {
    // "127 passed, 0 failed in 1.23s"
    for line in text.lines().rev() {
        if line.contains("passed") {
            let passed = extract_number(line, "passed");
            let failed = extract_number(line, "failed");
            return (passed, failed);
        }
    }
    (0, 0)
}

fn extract_number(text: &str, keyword: &str) -> u32 {
    if let Some(pos) = text.find(keyword) {
        let before: &str = &text[..pos];
        if let Some(last) = before.split_whitespace().last() {
            return last.parse().unwrap_or(0);
        }
    }
    0
}

fn finish_tests(
    passed: u32,
    failed: u32,
    ignored: u32,
    start: Instant,
    report: Option<&std::path::Path>,
    ctx: &Context,
) -> Result<i32, CliError> {
    let elapsed = start.elapsed();
    let ok = failed == 0;

    if !ctx.json {
        println!();
        if ok {
            println!(
                "\x1b[32m✓ All tests passed\x1b[0m — {} passed, {} ignored in {:.2}s",
                passed,
                ignored,
                elapsed.as_secs_f64()
            );
        } else {
            println!(
                "\x1b[31m✗ {} test(s) failed\x1b[0m — {} passed, {} failed, {} ignored in {:.2}s",
                failed,
                passed,
                failed,
                ignored,
                elapsed.as_secs_f64()
            );
        }
    }

    let report_json = serde_json::json!({
        "ok":         ok,
        "passed":     passed,
        "failed":     failed,
        "ignored":    ignored,
        "elapsed_ms": elapsed.as_millis(),
    });

    if let Some(path) = report {
        std::fs::write(path, serde_json::to_string_pretty(&report_json)?).map_err(|e| {
            CliError::Io {
                path: Some(path.to_path_buf()),
                source: e,
            }
        })?;
        ctx.print_ok(&format!("Test report written to {}", path.display()));
    }

    ctx.json_output(&report_json);
    Ok(if ok { 0 } else { 5 })
}
