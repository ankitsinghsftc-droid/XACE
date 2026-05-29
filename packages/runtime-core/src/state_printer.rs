//! # State Printer (M1)
//!
//! Pretty-prints the runtime state to stdout for M1 debugging.
//! Replaced in M2 by TCP transport that sends WireMessage payloads
//! to a connected engine adapter.
//!
//! ## Output Format
//!     [tick 60] entities=11 mutations=10 events=0
//!       player#1            T=(0.00, 0.00, 0.00)  health=100/100
//!       zombie#2            T=(-12.34, 0.00, 8.56)
//!       zombie#3            T=(15.20, 0.00, -3.40)
//!       ...
//!
//! With `--quiet`, prints only one line per print interval.

use crate::cgs_loader::type_ids;
use crate::component_tables::component_table_store::ComponentTableStore;
use crate::entity_store::entity_store::EntityStore;
use xace_core::runtime::state_delta::StateDelta;

pub struct PrinterOpts {
    pub verbose: bool,
    pub max_entities: usize,
}

impl Default for PrinterOpts {
    fn default() -> Self {
        Self {
            verbose: false,
            max_entities: 12,
        }
    }
}

/// Prints the current world state. Called every N ticks from runtime_orchestrator.
pub fn print_state(
    tick: u64,
    delta: &StateDelta,
    entity_store: &EntityStore,
    table_store: &ComponentTableStore,
    opts: &PrinterOpts,
) {
    let alive = entity_store.get_all_alive();
    println!(
        "[tick {:>6}]  entities={:<4}  delta_changes={:<3}  ",
        tick,
        alive.len(),
        delta.change_count(),
    );

    if !opts.verbose {
        return;
    }

    let mut shown = 0;
    for &eid in &alive {
        if shown >= opts.max_entities {
            println!("  ... ({} more entities)", alive.len() - shown);
            break;
        }

        // Identity for display name
        let name = table_store
            .get_component(eid, type_ids::IDENTITY)
            .and_then(parse_identity_name)
            .unwrap_or_else(|| format!("entity#{}", eid));

        // Transform position
        let pos = table_store
            .get_component(eid, type_ids::TRANSFORM)
            .and_then(parse_xyz)
            .map(|(x, y, z)| format!("T=({:>6.2},{:>6.2},{:>6.2})", x, y, z))
            .unwrap_or_else(|| "T=(no transform)".to_string());

        // Health (optional)
        let health = table_store
            .get_component(eid, type_ids::HEALTH)
            .and_then(parse_health)
            .map(|(cur, max)| format!("  hp={:.0}/{:.0}", cur, max))
            .unwrap_or_default();

        println!("  #{:<3} {:<20} {}{}", eid, name, pos, health);
        shown += 1;
    }
}

// ── JSON helpers ──────────────────────────────────────────────────────────────

fn parse_xyz(json: &str) -> Option<(f32, f32, f32)> {
    let v: serde_json::Value = serde_json::from_str(json).ok()?;
    // CGS uses position_x/y/z — fall back to x/y/z for other formats
    let x = v.get("position_x").or_else(|| v.get("x"))?.as_f64()? as f32;
    let y = v.get("position_y").or_else(|| v.get("y"))?.as_f64()? as f32;
    let z = v.get("position_z").or_else(|| v.get("z"))?.as_f64()? as f32;
    Some((x, y, z))
}

fn parse_health(json: &str) -> Option<(f32, f32)> {
    let v: serde_json::Value = serde_json::from_str(json).ok()?;
    let cur = v.get("current")?.as_f64()? as f32;
    let max = v.get("max")?.as_f64()? as f32;
    Some((cur, max))
}

fn parse_identity_name(json: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(json).ok()?;
    v.get("display_name")
        .and_then(|x| x.as_str())
        .or_else(|| v.get("name").and_then(|x| x.as_str()))
        .or_else(|| v.get("actor_id").and_then(|x| x.as_str()))
        .map(|s| s.to_string())
}
