/*!
# python_bridge.rs — Python Subprocess Bridge

Invokes XACE Python packages via subprocess with a JSON I/O protocol.

## Why Subprocess?

PyO3 ties the Rust binary to a specific Python ABI and breaks on minor version
upgrades. Subprocess with JSON is the UNIX way: languages stay independent,
the boundary is explicit, and either side can be tested in isolation.

50ms subprocess spawn cost is invisible to a developer running `xace build`.

## Protocol

XACE Python packages expose a `--xace-cli` mode that:
1. Reads JSON from stdin (or command-line args)
2. Performs the requested operation
3. Writes a JSON result to stdout
4. Writes human-readable logs to stderr
5. Exits 0 on success, non-zero on failure

## Result Format

All Python commands return JSON with this envelope:
```json
{
  "ok":       true,
  "data":     { ... command-specific output ... },
  "errors":   [],
  "warnings": []
}
```

## Python Candidates

`PythonBridge::new()` auto-detects the Python binary in priority order:
1. `XACE_PYTHON` environment variable
2. `python3` in PATH
3. `python` in PATH (if version ≥ 3.11)

## XACE Python Package Invocation

Packages are invoked as modules:
    python3 -m xace_gde <subcommand> [--args]

If `xace_gde` is not installed, the bridge returns a `PythonError` with
a clear install instruction. Run `pip install -e packages/gde` from the
XACE root to install in development mode.
*/

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use serde::Deserialize;
use serde_json::Value;

use crate::error::CliError;


// ── Python Result Envelope ────────────────────────────────────────────────────

/// JSON envelope returned by all XACE Python package CLI commands.
#[derive(Debug, Deserialize)]
pub struct PythonResult {
    pub ok:       bool,
    #[serde(default)]
    pub data:     Option<Value>,
    #[serde(default)]
    pub errors:   Vec<String>,
    #[serde(default)]
    pub warnings: Vec<String>,
}

impl PythonResult {
    pub fn into_result(self) -> Result<Value, CliError> {
        if self.ok {
            Ok(self.data.unwrap_or(Value::Null))
        } else {
            Err(CliError::ValidationError {
                errors:   self.errors,
                warnings: self.warnings,
            })
        }
    }
}


// ── Python Bridge ─────────────────────────────────────────────────────────────

pub struct PythonBridge {
    /// Path to the Python binary.
    python_bin:   PathBuf,
    /// Root directory of the XACE Python packages (for sys.path injection).
    packages_dir: PathBuf,
    verbose:      bool,
}

impl PythonBridge {
    /// Creates a new bridge, auto-detecting the Python binary.
    ///
    /// Searches in order: XACE_PYTHON env var → python3 → python.
    /// Returns an error if no Python 3.11+ interpreter is found.
    pub fn new(packages_dir: impl AsRef<Path>, verbose: bool) -> Result<Self, CliError> {
        let python_bin = Self::detect_python()?;
        if verbose {
            eprintln!("[xace] Python binary: {}", python_bin.display());
            eprintln!("[xace] Packages dir:  {}", packages_dir.as_ref().display());
        }
        Ok(Self {
            python_bin,
            packages_dir: packages_dir.as_ref().to_path_buf(),
            verbose,
        })
    }

    // ── Module Invocation ─────────────────────────────────────────────────────

    /// Invokes a Python module command and returns its JSON result.
    ///
    /// ```
    /// let result = bridge.invoke_module("xace_gde", "validate", &[
    ///     "--game-dir", "./my_game",
    /// ])?;
    /// ```
    pub fn invoke_module(
        &self,
        module:  &str,
        command: &str,
        args:    &[&str],
    ) -> Result<Value, CliError> {
        let mut cmd_args = vec!["-m", module, command, "--xace-cli"];
        cmd_args.extend_from_slice(args);

        let output = self.run(&cmd_args)?;
        self.parse_output(output, &format!("{} {}", module, command))
    }

    /// Invokes a Python module command with JSON input on stdin.
    pub fn invoke_module_with_stdin(
        &self,
        module:     &str,
        command:    &str,
        args:       &[&str],
        stdin_json: &Value,
    ) -> Result<Value, CliError> {
        let stdin_text = serde_json::to_string(stdin_json)?;

        let mut cmd = self.base_command();
        cmd.args(["-m", module, command, "--xace-cli"]);
        cmd.args(args);
        cmd.stdin(Stdio::piped());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| CliError::PythonError {
            command:   format!("python3 -m {} {}", module, command),
            stderr:    e.to_string(),
            exit_code: None,
        })?;

        // Write stdin
        if let Some(stdin) = child.stdin.take() {
            use std::io::Write;
            let mut s = stdin;
            let _ = s.write_all(stdin_text.as_bytes());
        }

        let output = child.wait_with_output().map_err(|e| CliError::Io {
            path: None, source: e,
        })?;

        self.parse_output(output, &format!("{} {}", module, command))
    }

    /// Simple check: can we `import` the named module without error?
    pub fn module_importable(&self, module: &str) -> bool {
        self.run(&["-c", &format!("import {}; print('ok')", module)])
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    /// Returns the Python version string, e.g. "Python 3.12.2".
    pub fn version_string(&self) -> Option<String> {
        let output = self.run(&["--version"]).ok()?;
        let text   = String::from_utf8_lossy(&output.stdout).to_string()
            + &String::from_utf8_lossy(&output.stderr);
        // Python --version outputs "Python X.Y.Z" to stderr on some versions
        for line in text.lines() {
            if line.starts_with("Python ") {
                return Some(line.trim().to_string());
            }
        }
        None
    }

    /// Returns the version string of an installed XACE Python package.
    pub fn package_version(&self, module: &str) -> Option<String> {
        let code = format!(
            "import {m}; v = getattr({m}, '__version__', None); print(v or 'unknown')",
            m = module
        );
        let output = self.run(&["-c", &code]).ok()?;
        if output.status.success() {
            Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
        } else {
            None
        }
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    fn base_command(&self) -> Command {
        let mut cmd = Command::new(&self.python_bin);
        // Inject the packages directory into sys.path so XACE modules are importable
        // even without `pip install -e .` (useful in CI and fresh checkouts)
        let path_str = self.packages_dir.display().to_string();
        cmd.env("PYTHONPATH", format!("{}:{}", path_str,
            std::env::var("PYTHONPATH").unwrap_or_default()));
        cmd
    }

    fn run(&self, args: &[&str]) -> Result<std::process::Output, CliError> {
        let mut cmd = self.base_command();
        cmd.args(args);
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        if self.verbose {
            let display = format!("{} {}", self.python_bin.display(), args.join(" "));
            eprintln!("[xace] Running: {}", display);
        }

        cmd.output().map_err(|e| CliError::PythonError {
            command:   args.join(" "),
            stderr:    e.to_string(),
            exit_code: None,
        })
    }

    fn parse_output(
        &self,
        output:  std::process::Output,
        command: &str,
    ) -> Result<Value, CliError> {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();

        if self.verbose && !stderr.is_empty() {
            for line in stderr.lines() {
                eprintln!("[xace-py] {}", line);
            }
        }

        if !output.status.success() {
            return Err(CliError::PythonError {
                command:   command.to_string(),
                stderr:    stderr.trim().to_string(),
                exit_code: output.status.code(),
            });
        }

        // Try to parse as XACE JSON envelope
        let trimmed = stdout.trim();
        if trimmed.is_empty() {
            return Ok(Value::Null);
        }

        match serde_json::from_str::<PythonResult>(trimmed) {
            Ok(result) => result.into_result(),
            Err(_) => {
                // Not an XACE envelope — return raw JSON or string
                serde_json::from_str(trimmed)
                    .unwrap_or_else(|_| Value::String(trimmed.to_string()))
                    .pipe(Ok)
            }
        }
    }

    fn detect_python() -> Result<PathBuf, CliError> {
        // 1. XACE_PYTHON env var
        if let Ok(p) = std::env::var("XACE_PYTHON") {
            let path = PathBuf::from(&p);
            if path.exists() {
                return Ok(path);
            }
        }

        // 2. python3 in PATH
        if let Ok(p) = which::which("python3") {
            if Self::check_version(&p) {
                return Ok(p);
            }
        }

        // 3. python in PATH (only if it's actually Python 3)
        if let Ok(p) = which::which("python") {
            if Self::check_version(&p) {
                return Ok(p);
            }
        }

        Err(CliError::PythonNotFound {
            searched: vec![
                "XACE_PYTHON env var".to_string(),
                "python3 in PATH".to_string(),
                "python in PATH".to_string(),
            ],
        })
    }

    fn check_version(path: &Path) -> bool {
        // Returns true if this binary is Python 3.11+
        let output = Command::new(path)
            .args(["--version"])
            .output()
            .unwrap_or_else(|_| return_empty_output());
        let text = String::from_utf8_lossy(&output.stdout).to_string()
            + &String::from_utf8_lossy(&output.stderr);
        // Parse "Python 3.12.2" → major=3, minor=12
        for line in text.lines() {
            if let Some(ver) = line.strip_prefix("Python ") {
                let parts: Vec<&str> = ver.split('.').collect();
                if parts.len() >= 2 {
                    let major: u32 = parts[0].parse().unwrap_or(0);
                    let minor: u32 = parts[1].parse().unwrap_or(0);
                    return major == 3 && minor >= 11;
                }
            }
        }
        false
    }
}

fn return_empty_output() -> std::process::Output {
    std::process::Output {
        status: {
            #[cfg(unix)]
            { use std::os::unix::process::ExitStatusExt; std::process::ExitStatus::from_raw(1) }
            #[cfg(not(unix))]
            { std::process::Command::new("false").status().unwrap_or_else(|_| {
                // Last resort
                panic!("cannot create empty ExitStatus on this platform")
            })}
        },
        stdout: Vec::new(),
        stderr: Vec::new(),
    }
}


// ── Pipe helper ───────────────────────────────────────────────────────────────

trait PipeExt: Sized {
    fn pipe<F, R>(self, f: F) -> R where F: FnOnce(Self) -> R;
}

impl<T> PipeExt for T {
    fn pipe<F, R>(self, f: F) -> R where F: FnOnce(Self) -> R { f(self) }
}