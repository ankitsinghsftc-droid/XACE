# Diff Details

Date : 2026-05-09 11:43:50

Directory c:\\Users\\ankit\\Downloads\\xace

Total : 108 files,  22509 codes, 7432 comments, 4804 blanks, all 34745 lines

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [README.md](/README.md) | Markdown | 101 | 0 | 188 | 289 |
| [adapters/unity/XaceConsoleWidget.cs](/adapters/unity/XaceConsoleWidget.cs) | C# | 346 | 69 | 66 | 481 |
| [adapters/unity/XaceDeltaApplicator.cs](/adapters/unity/XaceDeltaApplicator.cs) | C# | 405 | 84 | 111 | 600 |
| [adapters/unity/XaceInputCollector.cs](/adapters/unity/XaceInputCollector.cs) | C# | 230 | 59 | 46 | 335 |
| [adapters/unity/XaceTransport.cs](/adapters/unity/XaceTransport.cs) | C# | 299 | 81 | 65 | 445 |
| [examples/zombie-chase/src/cgs.rs](/examples/zombie-chase/src/cgs.rs) | Rust | 168 | 62 | 38 | 268 |
| [examples/zombie-chase/src/lib.rs](/examples/zombie-chase/src/lib.rs) | Rust | 6 | 31 | 2 | 39 |
| [examples/zombie-chase/src/runner.rs](/examples/zombie-chase/src/runner.rs) | Rust | 290 | 94 | 62 | 446 |
| [examples/zombie-chase/src/systems/ai\_system.rs](/examples/zombie-chase/src/systems/ai_system.rs) | Rust | 96 | 39 | 31 | 166 |
| [examples/zombie-chase/src/systems/damage\_system.rs](/examples/zombie-chase/src/systems/damage_system.rs) | Rust | 77 | 32 | 21 | 130 |
| [examples/zombie-chase/src/systems/death\_system.rs](/examples/zombie-chase/src/systems/death_system.rs) | Rust | 52 | 26 | 16 | 94 |
| [examples/zombie-chase/src/systems/input\_system.rs](/examples/zombie-chase/src/systems/input_system.rs) | Rust | 53 | 27 | 18 | 98 |
| [examples/zombie-chase/src/systems/mod.rs](/examples/zombie-chase/src/systems/mod.rs) | Rust | 5 | 8 | 1 | 14 |
| [examples/zombie-chase/src/systems/movement\_system.rs](/examples/zombie-chase/src/systems/movement_system.rs) | Rust | 63 | 25 | 20 | 108 |
| [packages/asset registry/animation\_contract.py](/packages/asset%20registry/animation_contract.py) | Python | 206 | 95 | 54 | 355 |
| [packages/asset registry/animation\_contract\_generator.py](/packages/asset%20registry/animation_contract_generator.py) | Python | 222 | 129 | 46 | 397 |
| [packages/asset registry/asset\_cleanup\_manager.py](/packages/asset%20registry/asset_cleanup_manager.py) | Python | 126 | 119 | 41 | 286 |
| [packages/asset registry/asset\_linker.py](/packages/asset%20registry/asset_linker.py) | Python | 171 | 82 | 40 | 293 |
| [packages/asset registry/asset\_manifest.py](/packages/asset%20registry/asset_manifest.py) | Python | 198 | 124 | 52 | 374 |
| [packages/asset registry/asset\_naming\_policy.py](/packages/asset%20registry/asset_naming_policy.py) | Python | 130 | 108 | 28 | 266 |
| [packages/asset registry/asset\_reference.py](/packages/asset%20registry/asset_reference.py) | Python | 111 | 79 | 30 | 220 |
| [packages/asset registry/asset\_registry\_manager.py](/packages/asset%20registry/asset_registry_manager.py) | Python | 203 | 123 | 61 | 387 |
| [packages/asset registry/asset\_report.py](/packages/asset%20registry/asset_report.py) | Python | 231 | 80 | 54 | 365 |
| [packages/asset registry/asset\_status\_enum.py](/packages/asset%20registry/asset_status_enum.py) | Python | 62 | 89 | 17 | 168 |
| [packages/asset registry/asset\_type\_enum.py](/packages/asset%20registry/asset_type_enum.py) | Python | 54 | 91 | 26 | 171 |
| [packages/asset registry/asset\_validator.py](/packages/asset%20registry/asset_validator.py) | Python | 235 | 86 | 39 | 360 |
| [packages/asset registry/audio\_manifest.py](/packages/asset%20registry/audio_manifest.py) | Python | 277 | 99 | 64 | 440 |
| [packages/asset registry/engine\_sync\_receiver.py](/packages/asset%20registry/engine_sync_receiver.py) | Python | 143 | 104 | 39 | 286 |
| [packages/asset registry/game\_config\_loader.py](/packages/asset%20registry/game_config_loader.py) | Python | 214 | 120 | 57 | 391 |
| [packages/asset registry/placeholder\_registry.py](/packages/asset%20registry/placeholder_registry.py) | Python | 136 | 102 | 45 | 283 |
| [packages/asset registry/tests/test\_asset\_manifest.py](/packages/asset%20registry/tests/test_asset_manifest.py) | Python | 685 | 49 | 134 | 868 |
| [packages/asset registry/tests/test\_asset\_validation.py](/packages/asset%20registry/tests/test_asset_validation.py) | Python | 781 | 58 | 150 | 989 |
| [packages/engine-adapter/src/adapter\_contract/adapter\_authority\_enforcer.rs](/packages/engine-adapter/src/adapter_contract/adapter_authority_enforcer.rs) | Rust | 380 | 140 | 83 | 603 |
| [packages/engine-adapter/src/adapter\_contract/engine\_adapter\_interface.rs](/packages/engine-adapter/src/adapter_contract/engine_adapter_interface.rs) | Rust | 583 | 170 | 120 | 873 |
| [packages/engine-adapter/src/adapter\_contract/mod.rs](/packages/engine-adapter/src/adapter_contract/mod.rs) | Rust | 2 | 0 | 1 | 3 |
| [packages/engine-adapter/src/delta\_sync/delta\_builder.rs](/packages/engine-adapter/src/delta_sync/delta_builder.rs) | Rust | 239 | 64 | 43 | 346 |
| [packages/engine-adapter/src/delta\_sync/delta\_compressor.rs](/packages/engine-adapter/src/delta_sync/delta_compressor.rs) | Rust | 333 | 131 | 97 | 561 |
| [packages/engine-adapter/src/delta\_sync/delta\_sync\_engine.rs](/packages/engine-adapter/src/delta_sync/delta_sync_engine.rs) | Rust | 321 | 116 | 89 | 526 |
| [packages/engine-adapter/src/delta\_sync/mod.rs](/packages/engine-adapter/src/delta_sync/mod.rs) | Rust | 7 | 0 | 2 | 9 |
| [packages/engine-adapter/src/delta\_sync/resync\_detector.rs](/packages/engine-adapter/src/delta_sync/resync_detector.rs) | Rust | 380 | 144 | 78 | 602 |
| [packages/engine-adapter/src/delta\_sync/snapshot\_recovery.rs](/packages/engine-adapter/src/delta_sync/snapshot_recovery.rs) | Rust | 274 | 97 | 56 | 427 |
| [packages/engine-adapter/src/lib.rs](/packages/engine-adapter/src/lib.rs) | Rust | 1 | 0 | 0 | 1 |
| [packages/engine-adapter/src/tests/mod.rs](/packages/engine-adapter/src/tests/mod.rs) | Rust | 8 | 0 | 0 | 8 |
| [packages/engine-adapter/src/tests/test\_delta\_sync.rs](/packages/engine-adapter/src/tests/test_delta_sync.rs) | Rust | 461 | 37 | 65 | 563 |
| [packages/engine-adapter/src/tests/test\_delta\_sync\_integration.rs](/packages/engine-adapter/src/tests/test_delta_sync_integration.rs) | Rust | 691 | 110 | 137 | 938 |
| [packages/engine-adapter/src/tests/test\_protocol\_handshake.rs](/packages/engine-adapter/src/tests/test_protocol_handshake.rs) | Rust | 251 | 45 | 49 | 345 |
| [packages/engine-adapter/src/tests/test\_transport.rs](/packages/engine-adapter/src/tests/test_transport.rs) | Rust | 412 | 35 | 64 | 511 |
| [packages/engine-feedback/src/feedback\_buffer.rs](/packages/engine-feedback/src/feedback_buffer.rs) | Rust | 277 | 103 | 63 | 443 |
| [packages/engine-feedback/src/feedback\_log.rs](/packages/engine-feedback/src/feedback_log.rs) | Rust | 267 | 99 | 72 | 438 |
| [packages/engine-feedback/src/feedback\_message.rs](/packages/engine-feedback/src/feedback_message.rs) | Rust | 267 | 52 | 41 | 360 |
| [packages/engine-feedback/src/feedback\_replay\_loader.rs](/packages/engine-feedback/src/feedback_replay_loader.rs) | Rust | 308 | 101 | 74 | 483 |
| [packages/engine-feedback/src/feedback\_router.rs](/packages/engine-feedback/src/feedback_router.rs) | Rust | 272 | 132 | 62 | 466 |
| [packages/engine-feedback/src/feedback\_type\_enum.rs](/packages/engine-feedback/src/feedback_type_enum.rs) | Rust | 169 | 60 | 34 | 263 |
| [packages/engine-feedback/src/feedback\_validator.rs](/packages/engine-feedback/src/feedback_validator.rs) | Rust | 330 | 95 | 69 | 494 |
| [packages/engine-feedback/src/handlers/animation\_feedback\_handler.rs](/packages/engine-feedback/src/handlers/animation_feedback_handler.rs) | Rust | 161 | 54 | 30 | 245 |
| [packages/engine-feedback/src/handlers/audio\_feedback\_handler.rs](/packages/engine-feedback/src/handlers/audio_feedback_handler.rs) | Rust | 184 | 30 | 36 | 250 |
| [packages/engine-feedback/src/handlers/input\_feedback\_handler.rs](/packages/engine-feedback/src/handlers/input_feedback_handler.rs) | Rust | 123 | 40 | 25 | 188 |
| [packages/engine-feedback/src/handlers/mod.rs](/packages/engine-feedback/src/handlers/mod.rs) | Rust | 12 | 0 | 1 | 13 |
| [packages/engine-feedback/src/handlers/performance\_feedback\_handler.rs](/packages/engine-feedback/src/handlers/performance_feedback_handler.rs) | Rust | 209 | 42 | 41 | 292 |
| [packages/engine-feedback/src/handlers/physics\_feedback\_handler.rs](/packages/engine-feedback/src/handlers/physics_feedback_handler.rs) | Rust | 210 | 46 | 33 | 289 |
| [packages/engine-feedback/src/handlers/visibility\_feedback\_handler.rs](/packages/engine-feedback/src/handlers/visibility_feedback_handler.rs) | Rust | 148 | 44 | 28 | 220 |
| [packages/engine-feedback/src/lib.rs](/packages/engine-feedback/src/lib.rs) | Rust | 11 | 0 | 0 | 11 |
| [packages/engine-feedback/src/mod.rs](/packages/engine-feedback/src/mod.rs) | Rust | 6 | 0 | 0 | 6 |
| [packages/engine-feedback/src/tests/mod.rs](/packages/engine-feedback/src/tests/mod.rs) | Rust | 4 | 0 | 0 | 4 |
| [packages/engine-feedback/src/tests/test\_feedback\_buffer.rs](/packages/engine-feedback/src/tests/test_feedback_buffer.rs) | Rust | 359 | 50 | 65 | 474 |
| [packages/engine-feedback/src/tests/test\_visibility\_queries.rs](/packages/engine-feedback/src/tests/test_visibility_queries.rs) | Rust | 286 | 37 | 48 | 371 |
| [packages/engine-feedback/src/visibility\_query/mod.rs](/packages/engine-feedback/src/visibility_query/mod.rs) | Rust | 3 | 0 | 2 | 5 |
| [packages/engine-feedback/src/visibility\_query/visibility\_query.rs](/packages/engine-feedback/src/visibility_query/visibility_query.rs) | Rust | 161 | 66 | 35 | 262 |
| [packages/engine-feedback/src/visibility\_query/visibility\_query\_batcher.rs](/packages/engine-feedback/src/visibility_query/visibility_query_batcher.rs) | Rust | 247 | 84 | 62 | 393 |
| [packages/engine-feedback/src/visibility\_query/visibility\_result\_store.rs](/packages/engine-feedback/src/visibility_query/visibility_result_store.rs) | Rust | 215 | 78 | 48 | 341 |
| [packages/schema-factory/src/component\_registry/component\_definition.py](/packages/schema-factory/src/component_registry/component_definition.py) | Python | 127 | 119 | 30 | 276 |
| [packages/schema-factory/src/component\_registry/component\_definition\_registry.py](/packages/schema-factory/src/component_registry/component_definition_registry.py) | Python | 150 | 112 | 40 | 302 |
| [packages/schema-factory/src/diff\_migration/migration\_rule\_generator.py](/packages/schema-factory/src/diff_migration/migration_rule_generator.py) | Python | 268 | 125 | 47 | 440 |
| [packages/schema-factory/src/diff\_migration/schema\_diff\_engine.py](/packages/schema-factory/src/diff_migration/schema_diff_engine.py) | Python | 247 | 110 | 55 | 412 |
| [packages/schema-factory/src/entity\_blueprint/blueprint\_compiler.py](/packages/schema-factory/src/entity_blueprint/blueprint_compiler.py) | Python | 184 | 120 | 51 | 355 |
| [packages/schema-factory/src/entity\_blueprint/blueprint\_registry.py](/packages/schema-factory/src/entity_blueprint/blueprint_registry.py) | Python | 80 | 82 | 28 | 190 |
| [packages/schema-factory/src/entity\_blueprint/entity\_blueprint.py](/packages/schema-factory/src/entity_blueprint/entity_blueprint.py) | Python | 71 | 105 | 23 | 199 |
| [packages/schema-factory/src/system\_registry/system\_definition\_registry.py](/packages/schema-factory/src/system_registry/system_definition_registry.py) | Python | 151 | 116 | 42 | 309 |
| [packages/schema-factory/src/system\_registry/system\_validator.py](/packages/schema-factory/src/system_registry/system_validator.py) | Python | 173 | 101 | 35 | 309 |
| [packages/schema-factory/src/versioning/schema\_snapshot.py](/packages/schema-factory/src/versioning/schema_snapshot.py) | Python | 112 | 110 | 28 | 250 |
| [packages/schema-factory/src/versioning/schema\_version\_manager.py](/packages/schema-factory/src/versioning/schema_version_manager.py) | Python | 269 | 147 | 44 | 460 |
| [packages/system-graph-compiler/src/compilation\_error.rs](/packages/system-graph-compiler/src/compilation_error.rs) | Rust | 254 | 62 | 44 | 360 |
| [packages/system-graph-compiler/src/conflict\_analyzer/conflict\_analyzer.rs](/packages/system-graph-compiler/src/conflict_analyzer/conflict_analyzer.rs) | Rust | 256 | 84 | 50 | 390 |
| [packages/system-graph-compiler/src/conflict\_analyzer/serialization\_group\_builder.rs](/packages/system-graph-compiler/src/conflict_analyzer/serialization_group_builder.rs) | Rust | 235 | 72 | 37 | 344 |
| [packages/system-graph-compiler/src/cycle\_detection/cycle\_detector.rs](/packages/system-graph-compiler/src/cycle_detection/cycle_detector.rs) | Rust | 378 | 131 | 57 | 566 |
| [packages/system-graph-compiler/src/cycle\_detection/cycle\_diagnostics.rs](/packages/system-graph-compiler/src/cycle_detection/cycle_diagnostics.rs) | Rust | 490 | 128 | 81 | 699 |
| [packages/system-graph-compiler/src/dependency\_resolution/dependency\_resolution\_engine.rs](/packages/system-graph-compiler/src/dependency_resolution/dependency_resolution_engine.rs) | Rust | 281 | 74 | 55 | 410 |
| [packages/system-graph-compiler/src/dependency\_resolution/topological\_sorter.rs](/packages/system-graph-compiler/src/dependency_resolution/topological_sorter.rs) | Rust | 298 | 94 | 53 | 445 |
| [packages/system-graph-compiler/src/graph\_construction/graph\_construction\_layer.rs](/packages/system-graph-compiler/src/graph_construction/graph_construction_layer.rs) | Rust | 317 | 83 | 55 | 455 |
| [packages/system-graph-compiler/src/graph\_construction/hazard\_detector.rs](/packages/system-graph-compiler/src/graph_construction/hazard_detector.rs) | Rust | 229 | 88 | 48 | 365 |
| [packages/system-graph-compiler/src/graph\_construction/mod.rs](/packages/system-graph-compiler/src/graph_construction/mod.rs) | Rust | 0 | 2 | 0 | 2 |
| [packages/system-graph-compiler/src/graph\_construction/system\_edge.rs](/packages/system-graph-compiler/src/graph_construction/system_edge.rs) | Rust | 227 | 63 | 41 | 331 |
| [packages/system-graph-compiler/src/graph\_construction/system\_node.rs](/packages/system-graph-compiler/src/graph_construction/system_node.rs) | Rust | 181 | 56 | 42 | 279 |
| [packages/system-graph-compiler/src/lib.rs](/packages/system-graph-compiler/src/lib.rs) | Rust | 2 | 14 | 0 | 16 |
| [packages/system-graph-compiler/src/parallelization/parallelization\_safety\_model.rs](/packages/system-graph-compiler/src/parallelization/parallelization_safety_model.rs) | Rust | 277 | 53 | 32 | 362 |
| [packages/system-graph-compiler/src/phase\_segmentation/mod.rs](/packages/system-graph-compiler/src/phase_segmentation/mod.rs) | Rust | 0 | 3 | 0 | 3 |
| [packages/system-graph-compiler/src/phase\_segmentation/phase\_segmentation\_layer.rs](/packages/system-graph-compiler/src/phase_segmentation/phase_segmentation_layer.rs) | Rust | 321 | 90 | 50 | 461 |
| [packages/system-graph-compiler/src/phase\_segmentation/phase\_validator.rs](/packages/system-graph-compiler/src/phase_segmentation/phase_validator.rs) | Rust | 211 | 61 | 27 | 299 |
| [packages/system-graph-compiler/src/scheduler/deterministic\_scheduler\_builder.rs](/packages/system-graph-compiler/src/scheduler/deterministic_scheduler_builder.rs) | Rust | 275 | 76 | 39 | 390 |
| [packages/system-graph-compiler/src/scheduler/parallel\_group\_analyzer.rs](/packages/system-graph-compiler/src/scheduler/parallel_group_analyzer.rs) | Rust | 252 | 89 | 42 | 383 |
| [packages/system-graph-compiler/src/sgc\_pipeline.rs](/packages/system-graph-compiler/src/sgc_pipeline.rs) | Rust | 221 | 42 | 43 | 306 |
| [packages/system-graph-compiler/src/tests/mod.rs](/packages/system-graph-compiler/src/tests/mod.rs) | Rust | 5 | 4 | 1 | 10 |
| [packages/system-graph-compiler/src/tests/test\_conflict\_analyzer.rs](/packages/system-graph-compiler/src/tests/test_conflict_analyzer.rs) | Rust | 117 | 13 | 20 | 150 |
| [packages/system-graph-compiler/src/tests/test\_cycle\_detection.rs](/packages/system-graph-compiler/src/tests/test_cycle_detection.rs) | Rust | 304 | 10 | 45 | 359 |
| [packages/system-graph-compiler/src/tests/test\_dependency\_resolution.rs](/packages/system-graph-compiler/src/tests/test_dependency_resolution.rs) | Rust | 165 | 8 | 19 | 192 |
| [packages/system-graph-compiler/src/tests/test\_graph\_construction.rs](/packages/system-graph-compiler/src/tests/test_graph_construction.rs) | Rust | 116 | 8 | 18 | 142 |
| [tests/determinism/mod.rs](/tests/determinism/mod.rs) | Rust | 1 | 0 | 0 | 1 |
| [tests/determinism/test\_vertical\_slice\_determinism.rs](/tests/determinism/test_vertical_slice_determinism.rs) | Rust | 316 | 101 | 67 | 484 |

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details