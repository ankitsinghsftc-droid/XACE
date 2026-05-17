/*!
# error.rs — CLI Error Types

Structured error enum with semantic exit codes.
All errors implement `Display` with actionable messages.

## Exit Code Contract
```
0  — success
1  — internal / IO error (something unexpected went wrong)
2  — validation error (game schema is invalid — user must fix game files)
3  — config error (game_config.yaml is missing or malformed)
4  — doctor issue (environment is not set up correctly)
5  — build error (compilation failed — check build output)
6  — not implemented (feature exists in the plan but is not yet built)
```
*/

use std::fmt;
use std::path::PathBuf;


// ── CliError ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum CliError {
    /// Filesystem I/O error.
    Io { path: Option<PathBuf>, source: std::io::Error },

    /// Python subprocess failed.
    PythonError { command: String, stderr: String, exit_code: Option<i32> },

    /// Python not found in PATH.
    PythonNotFound { searched: Vec<String> },

    /// game_config.yaml missing, malformed, or invalid.
    ConfigError { path: PathBuf, reason: String },

    /// CGS schema validation failed.
    ValidationError { errors: Vec<String>, warnings: Vec<String> },

    /// Build/compilation step failed.
    BuildError { stage: String, message: String },

    /// Doctor found missing or misconfigured requirements.
    DoctorIssues { issues: Vec<DoctorIssue> },

    /// Feature is planned but not yet implemented.
    NotImplemented { feature: String, phase: String },

    /// Generic error with message.
    Other(String),
}

impl CliError {
    /// Returns the exit code for this error.
    pub fn exit_code(&self) -> i32 {
        match self {
            Self::Io { .. }          => 1,
            Self::PythonError { .. } => 1,
            Self::PythonNotFound { .. } => 1,
            Self::ConfigError { .. }   => 3,
            Self::ValidationError { .. } => 2,
            Self::BuildError { .. }    => 5,
            Self::DoctorIssues { .. }  => 4,
            Self::NotImplemented { .. } => 6,
            Self::Other(_)             => 1,
        }
    }

    /// True if the error is recoverable by the user (vs an XACE bug).
    pub fn is_user_error(&self) -> bool {
        matches!(self,
            Self::ConfigError { .. }
            | Self::ValidationError { .. }
            | Self::DoctorIssues { .. }
            | Self::NotImplemented { .. }
        )
    }

    pub fn not_implemented(feature: impl Into<String>, phase: impl Into<String>) -> Self {
        Self::NotImplemented { feature: feature.into(), phase: phase.into() }
    }
}

impl fmt::Display for CliError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io { path, source } => {
                if let Some(p) = path {
                    write!(f, "I/O error on '{}': {}", p.display(), source)
                } else {
                    write!(f, "I/O error: {}", source)
                }
            }

            Self::PythonError { command, stderr, exit_code } => {
                write!(f, "Python command '{}' failed", command)?;
                if let Some(code) = exit_code {
                    write!(f, " (exit {})", code)?;
                }
                if !stderr.is_empty() {
                    write!(f, ":\n{}", stderr.trim())?;
                }
                Ok(())
            }

            Self::PythonNotFound { searched } => {
                write!(f,
                    "Python not found. Tried: {}.\n\
                     Install Python 3.11+ and ensure it is in your PATH.",
                    searched.join(", ")
                )
            }

            Self::ConfigError { path, reason } => {
                write!(f,
                    "game_config.yaml error in '{}':\n  {}\n\n\
                     Run `xace doctor` for a configuration checklist.",
                    path.display(), reason
                )
            }

            Self::ValidationError { errors, warnings } => {
                writeln!(f, "Schema validation failed ({} error(s)):", errors.len())?;
                for e in errors {
                    writeln!(f, "  ✗ {}", e)?;
                }
                if !warnings.is_empty() {
                    writeln!(f, "\nWarnings ({}):", warnings.len())?;
                    for w in warnings {
                        writeln!(f, "  ⚠ {}", w)?;
                    }
                }
                Ok(())
            }

            Self::BuildError { stage, message } => {
                write!(f, "Build failed at stage '{}': {}", stage, message)
            }

            Self::DoctorIssues { issues } => {
                let blocking: Vec<_> = issues.iter().filter(|i| i.severity == Severity::Error).collect();
                write!(f, "Doctor found {} issue(s) requiring attention.", blocking.len())?;
                for issue in issues.iter().filter(|i| i.severity == Severity::Error) {
                    write!(f, "\n  ✗ {}: {}", issue.name, issue.message)?;
                    if let Some(fix) = &issue.fix_hint {
                        write!(f, "\n    → {}", fix)?;
                    }
                }
                Ok(())
            }

            Self::NotImplemented { feature, phase } => {
                write!(f,
                    "'{}' is not yet implemented (planned for {}).\n\
                     Track progress in MASTER_PLAN.md.",
                    feature, phase
                )
            }

            Self::Other(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for CliError {}

impl From<std::io::Error> for CliError {
    fn from(e: std::io::Error) -> Self {
        Self::Io { path: None, source: e }
    }
}

impl From<anyhow::Error> for CliError {
    fn from(e: anyhow::Error) -> Self {
        Self::Other(e.to_string())
    }
}

impl From<serde_json::Error> for CliError {
    fn from(e: serde_json::Error) -> Self {
        Self::Other(format!("JSON error: {}", e))
    }
}

impl From<serde_yaml::Error> for CliError {
    fn from(e: serde_yaml::Error) -> Self {
        Self::Other(format!("YAML error: {}", e))
    }
}


// ── Doctor Issue ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub enum Severity { Error, Warning, Ok }

#[derive(Debug, Clone)]
pub struct DoctorIssue {
    pub name:      String,
    pub severity:  Severity,
    pub message:   String,
    pub fix_hint:  Option<String>,
}

impl DoctorIssue {
    pub fn ok(name: impl Into<String>, detail: impl Into<String>) -> Self {
        Self { name: name.into(), severity: Severity::Ok,      message: detail.into(), fix_hint: None }
    }

    pub fn warn(name: impl Into<String>, detail: impl Into<String>, fix: impl Into<String>) -> Self {
        Self { name: name.into(), severity: Severity::Warning, message: detail.into(), fix_hint: Some(fix.into()) }
    }

    pub fn error(name: impl Into<String>, detail: impl Into<String>, fix: impl Into<String>) -> Self {
        Self { name: name.into(), severity: Severity::Error,   message: detail.into(), fix_hint: Some(fix.into()) }
    }
}


// ── ANSI Output Helpers ───────────────────────────────────────────────────────

/// Prints a coloured doctor check result to stdout.
pub fn print_issue(issue: &DoctorIssue, no_color: bool) {
    let (icon, color_start, color_end) = if no_color {
        match issue.severity {
            Severity::Ok      => ("✓", "", ""),
            Severity::Warning => ("⚠", "", ""),
            Severity::Error   => ("✗", "", ""),
        }
    } else {
        match issue.severity {
            Severity::Ok      => ("✓", "\x1b[32m", "\x1b[0m"),   // green
            Severity::Warning => ("⚠", "\x1b[33m", "\x1b[0m"),   // yellow
            Severity::Error   => ("✗", "\x1b[31m", "\x1b[0m"),   // red
        }
    };

    println!("{}{} {}: {}{}", color_start, icon, issue.name, issue.message, color_end);
    if let Some(fix) = &issue.fix_hint {
        println!("    → {}", fix);
    }
}

/// Prints a section header.
pub fn print_header(title: &str, no_color: bool) {
    if no_color {
        println!("\n{}", title);
        println!("{}", "─".repeat(title.len()));
    } else {
        println!("\n\x1b[1m{}\x1b[0m", title);
        println!("{}", "─".repeat(title.len()));
    }
}

/// Prints an info line with optional bold.
pub fn print_info(msg: &str) {
    println!("  {}", msg);
}