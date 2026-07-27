# XACE CGS Schema Export Format

Status: canonical design contract for portable CGS export files.

Task: 156 - Design open, readable, shareable CGS schema export format.

## Purpose

A Canonical Game Schema export is a single JSON file that describes the gameplay-core schema of a XACE project in a form that is:

- human-readable in any text editor;
- portable across filesystems and operating systems;
- shareable without a `.xace/` workspace, engine project, runtime cache, or XACE installation;
- independently validatable with ordinary JSON tooling plus the rules in this document.

The canonical export file extension is:

```text
.cgs.json
```

The recommended filename for a project root remains:

```text
game.cgs.json
```

## File Contract

A CGS export file is UTF-8 JSON. The top-level value must be a JSON object.

The export must not require any sibling file to be understood. Engine-native assets, build outputs, execution plans, runtime snapshots, provider settings, caches, and `.xace/` internals are outside the CGS export format.

The file is allowed to contain game-specific component defaults and IDs, but all values must be standard JSON values: object, array, string, number, boolean, or null. Do not store comments, trailing commas, NaN, Infinity, binary blobs, absolute local-only paths as required fields, or host-specific path separators in required references.

## Required Top-Level Fields

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `format` | string | recommended for new exports | Must be `xace.cgs.export` for CGS Export Format 1 files. Legacy project files without this field may be accepted as pre-export CGS JSON, but new shareable exports should include it. |
| `format_version` | string | recommended for new exports | Version of this export file contract. Current value: `1.0.0`. Legacy files without this field are interpreted as `0.1.0` project CGS shape. |
| `metadata` | object | yes | Human identity, schema version, content hash, and optional descriptive data. |
| `global_systems` | array | yes | Systems available across all modes. Empty array is valid. |
| `component_schemas` | array | optional | Component table declarations that are not necessarily attached to initial actors. Used for generated, plugin, and schema-only components. |
| `modes` | array | yes | Game modes. Must contain at least one mode. Exactly one mode must have `is_default: true`. |
| `semantic_bindings` | object | optional | Portable semantic playback bindings for animation/audio/VFX/UI. Must not require engine-native project files to parse. |

## Metadata Fields

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `name` | string | yes | Human-readable game/schema name. Must not be empty. |
| `version` | string | yes | Content version of this schema, formatted as `MAJOR.MINOR.PATCH`. |
| `schema_version` | string | yes | Schema compatibility version, formatted as `MAJOR.MINOR.PATCH`. Runtime/editor handshakes compare this value. |
| `cgs_hash` | string | yes for committed exports | Canonical lowercase 64-character SHA-256 hash of the CGS content with `metadata.cgs_hash` removed before hashing. Short hashes are non-authoritative labels only. |
| `description` | string | optional | Human-readable description. |
| `game_id` | string | optional | Stable project identifier. Use a UUID string when present. |
| `created_with` | string | optional | Tool name/version that produced the export. |

Draft files may temporarily set `metadata.cgs_hash` to `""`, `"unresolved"`, or 64 zeroes only when clearly marked as drafts and not used for runtime loading, execution-plan matching, or proof artifacts. Committed shareable exports must carry a valid matching 64-character hash.

## Component Schema Fields

Each entry in optional top-level `component_schemas` must be an object.

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `type_id` | integer | yes | Positive component type ID. `0` is reserved and invalid. A top-level schema table may appear once per `type_id`. |
| `name` | string | yes | Human-readable component name, normally `COMP_<NAME>_V<NUMBER>`. The same `type_id` must always use the same `name` across schemas, actor defaults, and system access metadata. |
| `defaults` | object | yes | JSON object containing default field values for schema validation and table creation. |
| `source` | string | optional | Provenance label such as `generated`, `plugin`, or `cgs`. Validators require a non-empty string when present. |

Top-level component schemas are authoritative table declarations. Runtimes must register them before tick zero even when no initial actor instance owns that component.

## Mode Fields

Each entry in `modes` must be an object.

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `id` | string | yes | Stable mode ID. Must be unique within `modes`. |
| `schema_version` | string | yes | Mode compatibility version, normally matching `metadata.schema_version` unless the mode intentionally carries migration metadata. |
| `is_default` | boolean | yes | Exactly one mode in the file must be `true`. |
| `actors` | array | yes | Actor definitions for this mode. Empty array is valid for menu-only modes. |
| `systems` | array | yes | Mode-local systems. Empty array is valid. |
| `rules` | array | yes | Mode-local declarative rules. Empty array is valid. |

## Actor Fields

Each actor entry must be an object.

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `id` | string | yes | Stable actor ID. Actor IDs must be unique across the whole file. |
| `actor_type` | string | recommended | Human-readable gameplay category such as `PlayerCharacter`, `Enemy`, `Collectible`, or a project-specific string. |
| `control_type` | string | recommended | One of `Human`, `AiProxy`, `NetworkAuthority`, `Replay`, or a documented project-specific string. |
| `spawn_count` | integer | optional | Number of initial instances. Defaults to `1` when omitted. Must be greater than zero when present. |
| `components` | array | yes | Component defaults attached to this actor. Empty array is valid only for abstract/template actors. |

## Component Fields

Each component entry must be an object.

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `type_id` | integer | yes | Positive component type ID. `0` is reserved and invalid. |
| `name` | string | yes | Human-readable component name, normally `COMP_<NAME>_V<NUMBER>`. |
| `defaults` | object | yes | JSON object containing default field values. |

Within one actor, the same `type_id` must not appear twice. Across actors, the same `type_id` should use the same `name` unless a migration note explains the difference.

## System Fields

Each system entry in `global_systems` or `mode.systems` must be an object.

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `id` | string | yes | Stable system ID. Non-global system IDs must be unique across modes. A mode system may intentionally override a global system with the same ID, but validators should warn. |
| `phase` | string | yes | Execution phase. Canonical phases are `Initialization`, `Input`, `Simulation`, `PostSimulation`, and `Cleanup`. `Render` is allowed only as an adapter-facing semantic phase, not for authoritative gameplay mutation. |
| `reads` | array of integers | yes | Component type IDs read by the system. |
| `writes` | array of integers | yes | Component type IDs written through MutationGate by the system. |
| `depends_on` | array of strings | yes | System IDs that must run before this system. Every dependency must resolve to a system in the same file. |
| `deterministic` | boolean | yes | Must be `true` for systems that participate in deterministic runtime execution. |
| `parallel` | boolean | optional | Whether the compiler may place the system in a parallel group after dependency/write conflict checks. Defaults to `false`. |
| `runtime_executor` | object | optional | Deterministic executor metadata for non-built-in generated, plugin, or external systems. Supported runtimes normalize this through `xace.runtime_executor_abi.v1` or a compatible legacy generated ABI before registration. |

Every `reads` and `writes` component type ID must either be declared by at least one component in the file or be a reserved XACE/UCL component type known to the standalone validator version being used.

## Rule Fields

Rules are portable intent metadata. A standalone validator checks shape and identity, not full expression semantics.

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `id` | string | yes | Stable rule ID. Must be unique within its mode. |
| `condition` | string | yes | Human-readable or DSL condition. |
| `effect` | string | yes | Human-readable or DSL effect. |
| `priority` | integer | yes | Lower numbers run first when rules are evaluated. |
| `is_active` | boolean | yes | Whether this rule is enabled. |

## Hash And Canonicalization

`metadata.cgs_hash` is the committed content hash.

Hash algorithm:

1. Parse the JSON file as UTF-8.
2. Remove `metadata.cgs_hash` from a copy of the parsed object.
3. Recursively round JSON numbers that are represented as floats to six decimal places.
4. Serialize the copied object as canonical JSON:
   - object keys sorted lexicographically at every level;
   - no insignificant whitespace;
   - separators `,` and `:`;
   - ASCII escaping enabled.
5. Compute SHA-256 over the UTF-8 bytes of that canonical JSON.
6. Store the lowercase 64-character hex digest in `metadata.cgs_hash`.

Pretty formatting, indentation, and field order in the human-readable file do not affect the hash. Only parsed JSON content after removing `metadata.cgs_hash` matters.

## Standalone Validation

A schema file is standalone-valid when all of the following pass:

1. The file is valid UTF-8 JSON.
2. The top-level JSON value is an object.
3. Required top-level fields exist: `metadata`, `global_systems`, `modes`.
4. New exports either include `format: "xace.cgs.export"` and `format_version: "1.0.0"` or are explicitly treated as legacy project CGS JSON.
5. `metadata.name`, `metadata.version`, `metadata.schema_version`, and `metadata.cgs_hash` exist.
6. `metadata.version` and `metadata.schema_version` are `MAJOR.MINOR.PATCH` strings.
7. `metadata.cgs_hash` is a lowercase 64-character SHA-256 digest and matches the canonical recomputation for committed exports.
8. `global_systems` and `modes` are arrays.
9. `modes` is non-empty and has exactly one default mode.
10. Mode, actor, system, and rule IDs are non-empty strings and unique in their required scopes.
11. Component `type_id` values are positive integers, are not duplicated within one actor, and have object defaults.
12. System `reads`, `writes`, and `depends_on` are arrays, and every dependency resolves to a system in the same file.
13. System component references resolve to either file-declared component type IDs or reserved XACE/UCL component type IDs.
14. Required object arrays contain objects, not primitive values.
15. The file contains no unresolved required external dependency. Optional asset references may point at missing local files only when their status is explicitly non-linked/non-authoritative.

The repository provides a no-dependency reference validator:

```powershell
python tools/cgs_schema_validate.py path\to\game.cgs.json
```

For old project files that still have a non-authoritative short hash, use:

```powershell
python tools/cgs_schema_validate.py game.cgs.json --allow-legacy-hash
```

`--allow-legacy-hash` is for migration only. It does not make a file a canonical committed export.

## Compatibility Rules

- Readers must ignore unknown optional fields unless the field name starts with `xace_required_`.
- Writers must preserve unknown fields when round-tripping unless a migration explicitly removes them.
- New required fields require a `format_version` major bump.
- Additive optional fields require a minor bump.
- Clarifications that do not change validation behavior require a patch bump.
- Legacy files without `format` or `format_version` may be loaded as project CGS JSON, but export tools should write both fields.

## Non-Goals

A CGS export is not:

- a runtime world snapshot;
- an execution plan;
- a save file;
- an engine-native project;
- a finished-game package;
- a credential or provider settings container;
- proof that engine assets exist on another machine.

## Minimal Shape

```json
{
  "format": "xace.cgs.export",
  "format_version": "1.0.0",
  "metadata": {
    "name": "Example Game",
    "version": "0.1.0",
    "schema_version": "0.1.0",
    "cgs_hash": "unresolved",
    "description": "Draft example; committed exports use a matching 64-character SHA-256 hash."
  },
  "global_systems": [],
  "modes": [
    {
      "id": "mode_gameplay",
      "schema_version": "0.1.0",
      "is_default": true,
      "actors": [],
      "systems": [],
      "rules": []
    }
  ]
}
```

The example above is readable and structurally shaped, but it is a draft because `metadata.cgs_hash` is unresolved.
