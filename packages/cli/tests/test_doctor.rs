// ============================================================================
// packages/cli/tests/test_doctor.rs
// ============================================================================

use assert_cmd::Command;

/// Confirms `xace doctor` exits with 0 or 4 (never panics).
#[test]
fn doctor_runs_without_panic() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.arg("doctor");
    // Exit code is 0 (all ok) or 4 (issues found) — both are valid
    let output = cmd.output().unwrap();
    let code = output.status.code().unwrap_or(1);
    assert!(
        code == 0 || code == 4,
        "doctor must exit 0 or 4, got {}",
        code
    );
}

/// Confirms `xace doctor` produces non-empty output.
#[test]
fn doctor_produces_output() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.arg("doctor");
    let output = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let all = stdout.to_string() + &stderr;
    assert!(!all.is_empty(), "doctor produced no output");
}

/// Confirms `xace doctor --only runtime` works for focused checks.
#[test]
fn doctor_filter_runtime_only() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["doctor", "--only", "runtime"]);
    let output = cmd.output().unwrap();
    let code = output.status.code().unwrap_or(99);
    assert!(code == 0 || code == 4);
}

/// Confirms `xace doctor --json` produces valid JSON.
#[test]
fn doctor_json_mode_valid_json() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["doctor", "--json"]);
    let output = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);

    // Should be parseable as JSON
    let parsed: serde_json::Result<serde_json::Value> = serde_json::from_str(&stdout);
    assert!(
        parsed.is_ok(),
        "doctor --json did not produce valid JSON: {}",
        stdout
    );

    // Must have 'ok' and 'checks' fields
    let v = parsed.unwrap();
    assert!(v["ok"].is_boolean(), "missing 'ok' field");
    assert!(v["checks"].is_array(), "missing 'checks' array");
}

/// Confirms doctor always checks for Rust toolchain.
#[test]
fn doctor_checks_rust_toolchain() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["doctor", "--json"]);
    let output = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let v: serde_json::Value = serde_json::from_str(&stdout).unwrap_or_default();
    let checks = v["checks"].as_array().cloned().unwrap_or_default();
    let has_rust = checks.iter().any(|c| {
        c["name"]
            .as_str()
            .unwrap_or("")
            .to_lowercase()
            .contains("rust")
    });
    assert!(has_rust, "doctor must check for Rust toolchain");
}

/// Confirms doctor checks for API keys.
#[test]
fn doctor_checks_api_keys() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["doctor", "--json"]);
    let output = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    let v: serde_json::Value = serde_json::from_str(&stdout).unwrap_or_default();
    let checks = v["checks"].as_array().cloned().unwrap_or_default();
    let has_key = checks
        .iter()
        .any(|c| c["name"].as_str().unwrap_or("").contains("API_KEY"));
    assert!(has_key, "doctor must check LLM API keys");
}

/// Confirms `xace doctor --no-color` produces clean output without ANSI codes.
#[test]
fn doctor_no_color_no_ansi() {
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["doctor", "--no-color"]);
    let output = cmd.output().unwrap();
    let stdout = String::from_utf8_lossy(&output.stdout);
    // ANSI escape sequences start with \x1b[
    assert!(
        !stdout.contains('\x1b'),
        "doctor --no-color must not emit ANSI escape sequences"
    );
}
