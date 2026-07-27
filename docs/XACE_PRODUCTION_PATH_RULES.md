# XACE Production Path Rules

Inventory date: 2026-06-18

This file satisfies Task 4 of `XACE_COMMERCIAL_READINESS_MASTER_TASKLIST.md`.
The machine-readable rules live in `docs/production_path_rules.json`, and
`tools/production_path_check.py` enforces them.

## Production Means

Production paths are active source paths that can participate in product
runtime, Builder, adapter, compiler, provider, package, launcher, or release
workflows. Test, demo, smoke, proof, archived, generated, and external paths are
not production paths.

The source inventory remains the broad ownership map. These rules are narrower:
they define what production code may import, call, or silently tolerate.

## Rules

1. Production code must not import test, smoke, proof, fake, or archived helpers.
2. Production code must not satisfy provider readiness with mock providers, fake keys, fake SGC, fake adapters, or mock success.
3. Production CGS mutation code must not persist naive JSON edits. Mutation apply must use GDE/state authority or fail visibly.
4. Production checks must not silently skip required work. A skipped dependency must be explicit, user-visible, and represented in proof/certification output.
5. Unsupported fallbacks must block, be test-only, or be tied to a named follow-up task. They cannot be presented as product behavior.
6. Existing violations are allowed only when they are pinned in `docs/production_path_rules.json` and mapped to `docs/fake_skip_register.json`.
7. New production violations fail the gate immediately.

## Known Pinned Debt

Current pinned debt is not accepted product behavior. It exists so later tasks
can remove it without allowing the problem to spread.

| Area | Current status | Register |
| --- | --- | --- |
| Fake SGC prompt helper | Isolated to Builder server tests; production prompt proof uses the real SGC binary. | FSR-001 |
| Builder prompt fallback and mock adapter | Removed from production; missing PIL now blocks with `PIL_UNAVAILABLE` and production rules keep the old helpers unallowlisted. | FSR-002 |
| Optional/skipped SGC execution | Existing production-path debt. Must become real SGC authority or explicit unsupported state. | FSR-003 |
| Quick certification and installed-engine skips | Useful local certification, not installed-engine proof. | FSR-004 |
| Direct CGS mutation helpers | Removed from Builder production apply; GDE-unavailable applies now block visibly and production rules keep the old helpers unallowlisted. | FSR-010 |
| Engine-adapter generated-header skip | Local build tolerance only. Release/package gates must require shipped headers. | FSR-013 |

## CI Contract

CI must run:

```powershell
python tools/commercial_scope_check.py
python tools/source_inventory_check.py
python tools/fake_skip_register_check.py
python tools/production_path_check.py
python tools/forbidden_claims_check.py
```

`tools/certify_launch.py --quick` also runs the production-path check.
