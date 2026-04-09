# XACE

**Deterministic, engine-agnostic, schema-driven game definition compiler.**

XACE is not a game engine. It is the system that defines, validates, compiles,
and executes game logic independently of any rendering engine.
Unreal, Unity, and Godot are execution surfaces only.

## Architecture

```
User Intent
  → Prompt Intelligence Layer   [Python]
  → Game Definition Engine       [Python]
  → Schema Factory               [Python]
  → System Graph Compiler        [Rust]
  → Runtime Core                 [Rust]
  → Engine Adapter               [Rust]
  → Game Engine                  [C# / C++ / GDScript]
```

## Tech Stack

| Layer | Language |
|---|---|
| Runtime Core | Rust |
| System Graph Compiler | Rust |
| Engine Adapter Protocol | Rust |
| Shared Core Types | Rust |
| Schema Factory | Python |
| Game Definition Engine | Python |
| Prompt Intelligence Layer | Python |
| Builder Workspace UI | TypeScript + React |
| Unity Adapter | C# |
| Unreal Adapter | C++ |
| Godot Adapter | GDScript |

## Build Order

See MASTER_PLAN.md for the complete phase-by-phase build order.
See XACE_File_Manifest.docx for every file, its responsibility, and target line count.
See CLAUDE.md for full system context used by Claude Code.

## Setup

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install Python dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build Rust packages
cargo build

# Install Claude Code
npm install -g @anthropic-ai/claude-code
```
