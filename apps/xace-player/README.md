# XACE Player (XP-008)

Windows local Player for a pre-admitted XP-007 package. It mirrors canonical Rust
snapshots, renders typed transform/collider primitives, follows the locally owned
entity, and sends versioned, timed keyboard actions. No gameplay physics runs here.

The source folder is a template: `tools/xp008_player_build.py::prepare_player`
verifies a package with trusted RuntimeSupport, copies shared adapter modules, and
creates the distribution-owned admission receipt. `export_player` uses an official
Godot Windows release template. Changing a game requires new package data/admission,
not new Player or XACE core code. The current exported receipt admits one package;
installer/catalog management is XP-010 work.

A generated distribution contains `xace-player.exe`, `xace-player.pck` and `package/`.
Launch the executable directly; package resolution is relative to the executable,
not the working directory. No Python, Rust toolchain or Godot editor is needed to
play. The reference controls are W/A/S/D and Space, declared in package presentation
settings. Required executors must be registered in the packaged native host.

Reproduce the native proof after building the reference host:

```powershell
cargo build -p xace-reference-mechanic --bin xace_reference_host --offline
python tools/xp008_player_proof.py --template tmp/xp008-export/windows_release_x86_64.exe
```

The template argument must point to an existing official Godot 4.6.3 Windows export
runtime. Proof output defaults to `tmp/xp008-final/`. Tests inject Godot key events;
the production Player does not contain the reference input script. Slow input/render
delivery can stall local lockstep; fixed simulation timestep remains 1/60 second.
Richer semantic asset/effect presentation is XP-009, not a box restriction in the
World Contract. Unknown geometry is not promoted into an authoritative solver.
