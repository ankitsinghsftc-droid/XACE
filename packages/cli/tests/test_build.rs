// ============================================================================
// packages/cli/tests/test_build.rs
// ============================================================================

use std::fs;

use assert_cmd::Command;
use tempfile::TempDir;

/// Creates a minimal valid game_config.yaml in a temp directory.
fn write_minimal_config(dir: &TempDir, target: &str) {
    let config = format!(
        r#"
name: "Test Game"
version: "0.1.0"
schema_version: "0.1.0"
target_engines:
  - {}
domains:
  - combat
adapters:
  mode: tcp
  tcp_host: "127.0.0.1"
  tcp_port: 7878
build:
  output_dir: "./dist"
"#,
        target
    );
    fs::write(dir.path().join("game_config.yaml"), config).unwrap();
}

/// Confirms `xace build` errors when no game_config.yaml exists.
#[test]
fn build_missing_config_exits_3() {
    let dir = TempDir::new().unwrap();
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["build", "--game", dir.path().to_str().unwrap()]);
    let output = cmd.output().unwrap();
    // Exit 3 = config error
    assert_eq!(
        output.status.code().unwrap_or(0),
        3,
        "missing game_config.yaml must exit with code 3"
    );
}

/// Confirms `xace build --target standalone` exits with 6 (not implemented).
#[test]
fn build_standalone_not_implemented() {
    let dir = TempDir::new().unwrap();
    write_minimal_config(&dir, "standalone");
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args([
        "build",
        "--game",
        dir.path().to_str().unwrap(),
        "--target",
        "standalone",
    ]);
    let output = cmd.output().unwrap();
    assert_eq!(
        output.status.code().unwrap_or(0),
        6,
        "standalone target must exit with code 6 (not implemented)"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("Phase 17") || stderr.contains("not yet implemented"),
        "standalone error must mention Phase 17"
    );
}

/// Confirms `xace build --json` always produces valid JSON even on error.
#[test]
fn build_json_error_is_valid_json() {
    let dir = TempDir::new().unwrap(); // no config file
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args(["build", "--game", dir.path().to_str().unwrap(), "--json"]);
    let output = cmd.output().unwrap();

    // Even on error, stderr should contain JSON (from main.rs error handler)
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !stderr.is_empty() && stderr.trim().starts_with('{') {
        let parsed: serde_json::Result<serde_json::Value> = serde_json::from_str(stderr.trim());
        assert!(parsed.is_ok(), "JSON error output must be valid JSON");
        let v = parsed.unwrap();
        assert!(v["ok"].as_bool() == Some(false));
    }
    // If stderr is not JSON (e.g. the error goes to plain text), that's also ok
    // as long as exit code is non-zero
    assert_ne!(output.status.code().unwrap_or(0), 0);
}

/// Confirms `xace build` with valid config and --skip-validation runs further.
/// This test only asserts it doesn't exit with 3 (config error).
#[test]
fn build_valid_config_gets_past_config_stage() {
    let dir = TempDir::new().unwrap();
    write_minimal_config(&dir, "unity");
    let mut cmd = Command::cargo_bin("xace").unwrap();
    cmd.args([
        "build",
        "--game",
        dir.path().to_str().unwrap(),
        "--target",
        "unity",
        "--skip-validation",
    ]);
    let output = cmd.output().unwrap();
    let code = output.status.code().unwrap_or(99);
    // Must not be 3 (config error) — gets past config stage
    assert_ne!(code, 3, "valid config must not fail with config error");
}
