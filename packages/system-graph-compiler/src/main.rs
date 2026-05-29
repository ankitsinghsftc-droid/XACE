//! XACE System Graph Compiler — CLI entry point
//!
//! Reads system definitions JSON from stdin, compiles to an ExecutionPlan,
//! writes the plan JSON to stdout.
//!
//! ## Usage (called from Python builder_server via subprocess)
//!
//!     echo '{"systems": [...], "cgs_hash": "abc123"}' | xace_sgc
//!
//! ## Input (stdin)
//!
//!     {
//!       "systems": [
//!         {
//!           "id": "MovementSystem",
//!           "phase": "Simulation",
//!           "reads": [5, 6],
//!           "writes": [1],
//!           "depends_on": ["InputSystem"],
//!           "deterministic": true,
//!           "version_major": 1,
//!           "version_minor": 0
//!         },
//!         ...
//!       ],
//!       "cgs_hash": "0b1d495d..."  // used for determinism check in ExecutionPlan
//!     }
//!
//! ## Output (stdout, on success)
//!
//!     {
//!       "cgs_hash": "0b1d495d...",
//!       "schema_version": "0.1.0",
//!       "phases": {
//!         "Input": ["InputSystem"],
//!         "Simulation": ["MovementSystem", "AISystem"],
//!         "PostSimulation": ["DamageSystem", "DeathSystem"],
//!         "Render": []
//!       },
//!       "parallel_groups": [...],
//!       "execution_order": ["InputSystem", "MovementSystem", "AISystem", ...],
//!       "conflict_report": {
//!         "has_conflicts": false,
//!         "conflicts": []
//!       }
//!     }
//!
//! ## Exit codes
//!
//!     0 — success, ExecutionPlan written to stdout
//!     1 — JSON parse error or missing required fields
//!     2 — cycle detected in system dependency graph
//!     3 — conflict detected (non-deterministic read/write overlap)
//!     4 — I/O error
//!
//! ## Determinism guarantee (D1, D9, D11)
//!
//!     Identical input systems → identical ExecutionPlan.
//!     Systems are sorted by ID before compilation (D11).
//!     Output JSON uses sorted keys.

use std::collections::BTreeMap;
use std::io::{self, Read, Write};
use std::process;

mod compilation_error;
mod conflict_analyzer;
mod cycle_detection;
mod dependency_resolution;
mod graph_construction;
mod parallelization;
mod phase_segmentation;
mod scheduler;
mod sgc_pipeline;

use compilation_error::CompilationError;
use sgc_pipeline::SgcPipeline;

fn main() {
    // ── Read stdin ────────────────────────────────────────────────────────────
    let mut input = String::new();
    if let Err(e) = io::stdin().read_to_string(&mut input) {
        eprintln!("[SGC] I/O error reading stdin: {}", e);
        process::exit(4);
    }

    if input.trim().is_empty() {
        eprintln!("[SGC] Empty input — no systems to compile.");
        process::exit(1);
    }

    // ── Parse input JSON ──────────────────────────────────────────────────────
    let parsed: serde_json::Value = match serde_json::from_str(&input) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[SGC] JSON parse error: {}", e);
            process::exit(1);
        }
    };

    let systems_val = match parsed.get("systems") {
        Some(s) => s,
        None => {
            eprintln!("[SGC] Input missing required field 'systems'.");
            process::exit(1);
        }
    };

    let cgs_hash = parsed
        .get("cgs_hash")
        .and_then(|h| h.as_str())
        .unwrap_or("")
        .to_string();

    // ── Compile ───────────────────────────────────────────────────────────────
    let pipeline = SgcPipeline::new();

    let result = pipeline.compile(systems_val, &cgs_hash);

    match result {
        Ok(plan) => {
            // Serialise ExecutionPlan to stdout
            match serde_json::to_string_pretty(&plan) {
                Ok(json_out) => {
                    print!("{}", json_out);
                    io::stdout().flush().ok();
                    process::exit(0);
                }
                Err(e) => {
                    eprintln!("[SGC] Failed to serialise ExecutionPlan: {}", e);
                    process::exit(4);
                }
            }
        }
        Err(CompilationError::CycleDetected(cycle)) => {
            eprintln!(
                "[SGC] Cycle detected in system dependency graph: {:?}",
                cycle
            );
            process::exit(2);
        }
        Err(CompilationError::ConflictDetected(conflicts)) => {
            eprintln!("[SGC] Conflicts detected: {:?}", conflicts);
            // Non-fatal: still output the plan with conflict report embedded
            // The builder_server.py will log the conflict and warn the designer
            process::exit(3);
        }
        Err(CompilationError::InvalidInput(msg)) => {
            eprintln!("[SGC] Invalid input: {}", msg);
            process::exit(1);
        }
        Err(e) => {
            eprintln!("[SGC] Compilation error: {:?}", e);
            process::exit(1);
        }
    }
}
