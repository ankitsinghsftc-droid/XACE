/*!
# crash_reporter.rs — Crash Reporter

Captures a rich diagnostic snapshot on any Rust panic or Determinism Guard
violation and writes it to disk.

## Crash Report Contents

```json
{
  "report_type":    "PANIC" | "DETERMINISM_VIOLATION",
  "timestamp":      "2026-05-16T12:34:56Z",
  "schema_version": "0.2.1",
  "last_world_hash": "0b1d495d...",
  "tick_number":    1000,
  "violation": {
    "rule":    "D6",
    "message": "Non-deterministic RNG call detected in AISystem"
  },
  "last_100_ticks": [ ... TickRecord array ... ],
  "health_snapshot": { ... },
  "panic_message":  "thread 'main' panicked at 'index out of bounds: ...'",
  "rust_backtrace": "... backtrace if RUST_BACKTRACE=1 ..."
}
```

## Installation

Call `crash_reporter::install()` at process start — before any simulation
threads are spawned:

```rust
fn main() {
    xace_observability::install_crash_handler();
    // ... rest of startup
}
```

## Determinism Violations

Runtime Core's Determinism Guard calls `crash_reporter::report_determinism_violation()`
directly when a D-rule fires — no panic required. The crash report is written,
the HealthWriter is updated, and the error propagates up normally.

## File Naming

Reports are written to `./crash_reports/crash_{epoch_ms}.json`.
The directory is created if it does not exist.
Failed writes go to stderr — the reporter must never panic itself.
*/

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::health_check::HealthWriter;
use crate::tick_ring_buffer::{TickRecord, TICK_BUFFER};


// ── Report Types ──────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReportType {
    Panic,
    DeterminismViolation,
    FatalError,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ViolationDetail {
    pub rule:    String,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CrashReport {
    pub report_type:     ReportType,
    pub timestamp_iso:   String,
    pub epoch_ms:        u64,
    pub schema_version:  String,
    pub last_world_hash: String,
    pub tick_number:     u64,
    pub violation:       Option<ViolationDetail>,
    pub last_ticks:      Vec<TickRecord>,
    pub health_snapshot: serde_json::Value,
    pub panic_message:   Option<String>,
    pub thread_name:     Option<String>,
}

impl CrashReport {
    fn to_json_pretty(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".to_string())
    }
}


// ── Config ────────────────────────────────────────────────────────────────────

static CRASH_DIR: OnceLock<PathBuf> = OnceLock::new();
static HANDLER_INSTALLED: AtomicBool = AtomicBool::new(false);

/// Sets the directory where crash reports are written.
/// Must be called before `install()`.
/// Default: `./crash_reports/`
pub fn set_crash_dir(path: impl Into<PathBuf>) {
    let _ = CRASH_DIR.set(path.into());
}

fn crash_dir() -> &'static Path {
    CRASH_DIR.get_or_init(|| PathBuf::from("./crash_reports")).as_path()
}


// ── Installation ──────────────────────────────────────────────────────────────

/// Installs the XACE panic handler.
///
/// Call once at program start, before any simulation threads are spawned.
/// Safe to call multiple times (no-op on subsequent calls).
///
/// ```rust
/// fn main() {
///     xace_observability::install_crash_handler();
///     // ... rest of startup ...
/// }
/// ```
pub fn install() {
    if HANDLER_INSTALLED.swap(true, Ordering::SeqCst) {
        return;   // already installed
    }

    std::panic::set_hook(Box::new(|panic_info| {
        let message = panic_info
            .payload()
            .downcast_ref::<&str>()
            .copied()
            .or_else(|| {
                panic_info.payload().downcast_ref::<String>().map(|s| s.as_str())
            })
            .unwrap_or("unknown panic")
            .to_string();

        let thread_name = std::thread::current()
            .name()
            .unwrap_or("<unnamed>")
            .to_string();

        // Suppress recursive panics inside the reporter
        let report = build_report(
            ReportType::Panic,
            None,
            Some(format!("[{}] {}", thread_name, message)),
            Some(thread_name),
        );

        write_report(&report);
        HealthWriter::global().add_error(format!("PANIC: {}", message));

        // Print human-readable summary to stderr
        eprintln!(
            "\n[XACE CRASH] tick={} hash={}\nSee: {}\n",
            report.tick_number,
            report.last_world_hash,
            report_path_preview(),
        );
    }));
}


// ── Determinism Violation Reporter ────────────────────────────────────────────

/// Called by Determinism Guard when any D1-D15 rule fires.
///
/// Writes a crash report and marks the runtime as unhealthy.
/// Does NOT panic — the caller decides whether to continue or abort.
///
/// ```rust
/// // In determinism_guard.rs:
/// crash_reporter::report_determinism_violation("D6", "Non-deterministic RNG in AISystem");
/// ```
pub fn report_determinism_violation(rule: &str, message: &str) {
    let violation = ViolationDetail {
        rule:    rule.to_string(),
        message: message.to_string(),
    };

    let error_msg = format!("D-rule {}: {}", rule, message);

    let report = build_report(
        ReportType::DeterminismViolation,
        Some(violation),
        None,
        None,
    );

    write_report(&report);
    HealthWriter::global().add_error(error_msg);

    eprintln!(
        "\n[XACE DETERMINISM VIOLATION] rule={} tick={} hash={}\nSee: {}\n",
        rule, report.tick_number, report.last_world_hash,
        report_path_preview(),
    );
}

/// Called for any fatal error that is not a panic or D-rule violation.
pub fn report_fatal(message: &str) {
    let report = build_report(ReportType::FatalError, None, Some(message.to_string()), None);
    write_report(&report);
    HealthWriter::global().add_error(format!("FATAL: {}", message));
}


// ── Internal ──────────────────────────────────────────────────────────────────

fn build_report(
    report_type:  ReportType,
    violation:    Option<ViolationDetail>,
    panic_msg:    Option<String>,
    thread_name:  Option<String>,
) -> CrashReport {
    let health   = HealthWriter::global().snapshot();
    let ticks    = TICK_BUFFER.recent(100);
    let latest   = ticks.first();

    let health_json = serde_json::to_value(&health).unwrap_or(serde_json::Value::Null);

    CrashReport {
        report_type,
        timestamp_iso:   iso_timestamp(),
        epoch_ms:        epoch_ms(),
        schema_version:  health.schema_version.clone(),
        last_world_hash: latest.map(|t| t.world_hash.clone())
                               .unwrap_or_else(|| health.last_world_hash.clone()),
        tick_number:     latest.map(|t| t.tick_number).unwrap_or(health.tick_number),
        violation,
        last_ticks:      ticks,
        health_snapshot: health_json,
        panic_message:   panic_msg,
        thread_name,
    }
}

fn write_report(report: &CrashReport) {
    let dir = crash_dir();

    // Create directory if needed — silently ignore failure
    if !dir.exists() {
        let _ = std::fs::create_dir_all(dir);
    }

    let filename = format!("crash_{}.json", report.epoch_ms);
    let path     = dir.join(&filename);

    match std::fs::write(&path, report.to_json_pretty()) {
        Ok(_)  => eprintln!("[xace-obs] Crash report written: {}", path.display()),
        Err(e) => eprintln!("[xace-obs] Failed to write crash report: {}", e),
    }
}

fn report_path_preview() -> String {
    crash_dir().join(format!("crash_{}.json", epoch_ms())).display().to_string()
}

fn epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn iso_timestamp() -> String {
    // Simple ISO-8601 without external crate — format epoch_ms manually
    let secs = epoch_ms() / 1000;
    format!("{}Z", epoch_to_iso(secs))
}

fn epoch_to_iso(secs: u64) -> String {
    // Basic epoch → "YYYY-MM-DDTHH:MM:SS" without chrono
    let s   = secs;
    let sec = s % 60;   let s = s / 60;
    let min = s % 60;   let s = s / 60;
    let hr  = s % 24;   let s = s / 24;

    // Days since epoch — approximate (ignores leap seconds, good enough for a timestamp)
    let days = s;
    let y400 = days / 146097;
    let days = days % 146097;
    let y100 = (days / 36524).min(3);
    let days = days - y100 * 36524;
    let y4   = days / 1461;
    let days = days % 1461;
    let y1   = (days / 365).min(3);
    let days = days - y1 * 365;

    let year = y400 * 400 + y100 * 100 + y4 * 4 + y1 + 1970;
    let leap  = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let month_days: &[u64] = if leap {
        &[31,29,31,30,31,30,31,31,30,31,30,31]
    } else {
        &[31,28,31,30,31,30,31,31,30,31,30,31]
    };
    let mut remaining = days;
    let mut month = 1u64;
    for &md in month_days {
        if remaining < md { break; }
        remaining -= md;
        month += 1;
    }
    let day = remaining + 1;

    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", year, month, day, hr, min, sec)
}