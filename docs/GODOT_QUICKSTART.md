# XACE Godot Quickstart

This is the first official live-engine path for XACE.

## Start

From the repo root:

```powershell
python tools/xace_godot_dev.py
```

That command creates `projects/zombie_chase/game.cgs.json` if it does not
exist, starts the XACE runtime, starts the builder server, starts the builder
UI, and opens the Godot adapter project.

Open the builder at:

```text
http://localhost:5173
```

## Controls In Godot

- Move: `WASD` or arrow keys
- Attack: `Space`
- Interact: `E`
- Dash: `Shift`

## What Should Happen

Godot connects to the runtime on port `7777`, receives the Player and Zombie
entities, and renders simple capsule placeholders. The builder connects to the
runtime control port `7778` and can request live snapshots.

## If Godot Does Not Open

Pass the Godot executable path:

```powershell
python tools/xace_godot_dev.py --godot-bin "C:\Path\To\Godot.exe"
```

Or set:

```powershell
$env:GODOT_BIN = "C:\Path\To\Godot.exe"
python tools/xace_godot_dev.py
```

## Run Without Godot

```powershell
python tools/xace_godot_dev.py --no-godot
```

This runs runtime + builder only. The builder viewport can still poll runtime
snapshots, but no real engine window is opened.
