/*!
# commands/mod.rs — Shared Command Infrastructure

Declares all command modules and provides the shared `Context` struct
that carries global CLI flags into every command.
*/

pub mod build;
pub mod deploy;
pub mod doctor;
pub mod run;
pub mod test;

// ── Execution Context ─────────────────────────────────────────────────────────

/// Global flags passed to every command. Immutable after CLI parse.
#[derive(Clone)]
pub struct Context {
    pub verbose: bool,
    pub no_color: bool,
    pub json: bool,
}

impl Context {
    pub fn print_step(&self, msg: &str) {
        if !self.json {
            if self.no_color {
                println!("  {}", msg);
            } else {
                println!("  \x1b[36m→\x1b[0m {}", msg);
            }
        }
    }

    pub fn print_ok(&self, msg: &str) {
        if !self.json {
            if self.no_color {
                println!("✓ {}", msg);
            } else {
                println!("\x1b[32m✓\x1b[0m {}", msg);
            }
        }
    }

    pub fn print_warn(&self, msg: &str) {
        if !self.json {
            if self.no_color {
                eprintln!("⚠ {}", msg);
            } else {
                eprintln!("\x1b[33m⚠\x1b[0m {}", msg);
            }
        }
    }

    pub fn print_error(&self, msg: &str) {
        if !self.json {
            if self.no_color {
                eprintln!("✗ {}", msg);
            } else {
                eprintln!("\x1b[31m✗\x1b[0m {}", msg);
            }
        }
    }

    pub fn print_header(&self, title: &str) {
        if !self.json {
            crate::error::print_header(title, self.no_color);
        }
    }

    pub fn verbose_log(&self, msg: &str) {
        if self.verbose && !self.json {
            eprintln!("[xace] {}", msg);
        }
    }

    pub fn json_output(&self, value: &serde_json::Value) {
        if self.json {
            println!(
                "{}",
                serde_json::to_string_pretty(value).unwrap_or_default()
            );
        }
    }
}
