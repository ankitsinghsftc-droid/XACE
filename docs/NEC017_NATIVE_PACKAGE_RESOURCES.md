# Native package resource catalog v1

A native-engine presentation variant may carry `presentation/<engine>/native-resources.json` with schema `xace.native_package_resources.v1`, engine `godot|unity|unreal`, and sorted asset records containing exactly `id`, `asset_type`, `source`, `path`, and `sha256`.

Each record binds an existing LINKED CGS asset's project-relative `source` to the exact archived bytes at `presentation/<engine>/<source>`. Both paths obey existing portable package path rules. The asset ID/type/source must match CGS; the payload digest must match the archive. Missing, foreign, duplicate or inconsistent records fail admission. Existing direct `presentation/` references keep their current validation.

The catalog is itself included in the existing package file table and presentation-variant identity. It does not change CGS, gameplay hashes, executor admission, or the playable-package manifest schema. Source locations never become filesystem read permissions. Catalog preparation takes explicitly supplied resource bytes and performs no filesystem access.

This is byte-preserving native resource packaging, not conversion to another engine, generic Player rendering, or dependency/cook certification. Actual native dependency closure, source approval, build/cook, playback and continuing-use licensing remain separate required checks. Unsupported names/path forms are refused, not silently renamed.
