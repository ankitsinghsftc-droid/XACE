# Diff Details

Date : 2026-05-16 20:23:08

Directory c:\\Users\\ankit\\Downloads\\xace

Total : 73 files,  7528 codes, 2804 comments, 1757 blanks, all 12089 lines

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [adapters/unity/Xace\_embedded.cs](/adapters/unity/Xace_embedded.cs) | C# | 223 | 85 | 63 | 371 |
| [packages/asset-runtime/src/cdn/cdn\_adapter.rs](/packages/asset-runtime/src/cdn/cdn_adapter.rs) | Rust | 50 | 38 | 18 | 106 |
| [packages/asset-runtime/src/cdn/cloudfront\_adapter.rs](/packages/asset-runtime/src/cdn/cloudfront_adapter.rs) | Rust | 85 | 34 | 22 | 141 |
| [packages/asset-runtime/src/cdn/local\_cdn\_adapter.rs](/packages/asset-runtime/src/cdn/local_cdn_adapter.rs) | Rust | 73 | 26 | 19 | 118 |
| [packages/asset-runtime/src/cdn/mod.rs](/packages/asset-runtime/src/cdn/mod.rs) | Rust | 6 | 3 | 2 | 11 |
| [packages/asset-runtime/src/cdn/range\_request.rs](/packages/asset-runtime/src/cdn/range_request.rs) | Rust | 22 | 33 | 4 | 59 |
| [packages/asset-runtime/src/cdn/s3\_adapter.rs](/packages/asset-runtime/src/cdn/s3_adapter.rs) | Rust | 96 | 38 | 20 | 154 |
| [packages/asset-runtime/src/hot\_reload/file\_watcher.rs](/packages/asset-runtime/src/hot_reload/file_watcher.rs) | Rust | 94 | 42 | 21 | 157 |
| [packages/asset-runtime/src/hot\_reload/mod.rs](/packages/asset-runtime/src/hot_reload/mod.rs) | Rust | 7 | 3 | 2 | 12 |
| [packages/asset-runtime/src/hot\_reload/reload\_coordinator.rs](/packages/asset-runtime/src/hot_reload/reload_coordinator.rs) | Rust | 133 | 49 | 27 | 209 |
| [packages/asset-runtime/src/hot\_reload/tick\_boundary\_gate.rs](/packages/asset-runtime/src/hot_reload/tick_boundary_gate.rs) | Rust | 62 | 56 | 15 | 133 |
| [packages/asset-runtime/src/hot\_reload/version\_hasher.rs](/packages/asset-runtime/src/hot_reload/version_hasher.rs) | Rust | 25 | 27 | 8 | 60 |
| [packages/asset-runtime/src/lib.rs](/packages/asset-runtime/src/lib.rs) | Rust | 59 | 54 | 22 | 135 |
| [packages/asset-runtime/src/streaming/asset\_streamer.rs](/packages/asset-runtime/src/streaming/asset_streamer.rs) | Rust | 219 | 82 | 41 | 342 |
| [packages/asset-runtime/src/streaming/load\_request.rs](/packages/asset-runtime/src/streaming/load_request.rs) | Rust | 89 | 34 | 28 | 151 |
| [packages/asset-runtime/src/streaming/load\_result.rs](/packages/asset-runtime/src/streaming/load_result.rs) | Rust | 68 | 25 | 14 | 107 |
| [packages/asset-runtime/src/streaming/mod.rs](/packages/asset-runtime/src/streaming/mod.rs) | Rust | 0 | 0 | 1 | 1 |
| [packages/asset-runtime/src/streaming/priority\_queue.rs](/packages/asset-runtime/src/streaming/priority_queue.rs) | Rust | 49 | 25 | 13 | 87 |
| [packages/asset-runtime/tests/test\_cdn\_adapter.rs](/packages/asset-runtime/tests/test_cdn_adapter.rs) | Rust | 106 | 16 | 25 | 147 |
| [packages/asset-runtime/tests/test\_hot\_reload\_determinism.rs](/packages/asset-runtime/tests/test_hot_reload_determinism.rs) | Rust | 138 | 35 | 37 | 210 |
| [packages/asset-runtime/tests/test\_streaming.rs](/packages/asset-runtime/tests/test_streaming.rs) | Rust | 180 | 14 | 39 | 233 |
| [packages/cli/src/commands/build.rs](/packages/cli/src/commands/build.rs) | Rust | 155 | 44 | 31 | 230 |
| [packages/cli/src/commands/deploy.rs](/packages/cli/src/commands/deploy.rs) | Rust | 20 | 8 | 7 | 35 |
| [packages/cli/src/commands/doctor.rs](/packages/cli/src/commands/doctor.rs) | Rust | 357 | 69 | 59 | 485 |
| [packages/cli/src/commands/mod.rs](/packages/cli/src/commands/mod.rs) | Rust | 64 | 8 | 11 | 83 |
| [packages/cli/src/commands/run.rs](/packages/cli/src/commands/run.rs) | Rust | 60 | 9 | 12 | 81 |
| [packages/cli/src/commands/test.rs](/packages/cli/src/commands/test.rs) | Rust | 161 | 13 | 30 | 204 |
| [packages/cli/src/config.rs](/packages/cli/src/config.rs) | Rust | 190 | 56 | 34 | 280 |
| [packages/cli/src/error.rs](/packages/cli/src/error.rs) | Rust | 184 | 34 | 42 | 260 |
| [packages/cli/src/main.rs](/packages/cli/src/main.rs) | Rust | 74 | 44 | 23 | 141 |
| [packages/cli/src/python\_bridge.rs](/packages/cli/src/python_bridge.rs) | Rust | 233 | 85 | 43 | 361 |
| [packages/cli/tests/test\_build.rs](/packages/cli/tests/test_build.rs) | Rust | 85 | 14 | 7 | 106 |
| [packages/cli/tests/test\_doctor.rs](/packages/cli/tests/test_doctor.rs) | Rust | 84 | 14 | 10 | 108 |
| [packages/engine-adapter/build.rs](/packages/engine-adapter/build.rs) | Rust | 27 | 31 | 5 | 63 |
| [packages/engine-adapter/src/ffi/error\_codes.rs](/packages/engine-adapter/src/ffi/error_codes.rs) | Rust | 20 | 52 | 3 | 75 |
| [packages/engine-adapter/src/ffi/ffi\_transport.rs](/packages/engine-adapter/src/ffi/ffi_transport.rs) | Rust | 137 | 69 | 33 | 239 |
| [packages/engine-adapter/src/ffi/handle\_type.rs](/packages/engine-adapter/src/ffi/handle_type.rs) | Rust | 68 | 62 | 23 | 153 |
| [packages/engine-adapter/src/ffi/mod.rs](/packages/engine-adapter/src/ffi/mod.rs) | Rust | 9 | 29 | 2 | 40 |
| [packages/engine-adapter/src/ffi/shared\_buffer.rs](/packages/engine-adapter/src/ffi/shared_buffer.rs) | Rust | 84 | 61 | 23 | 168 |
| [packages/engine-adapter/src/ffi/tests/test\_ffi\_determinism.rs](/packages/engine-adapter/src/ffi/tests/test_ffi_determinism.rs) | Rust | 94 | 56 | 23 | 173 |
| [packages/engine-adapter/src/ffi/tests/test\_ffi\_memory.rs](/packages/engine-adapter/src/ffi/tests/test_ffi_memory.rs) | Rust | 126 | 14 | 22 | 162 |
| [packages/engine-adapter/src/ffi/xace\_ffi.rs](/packages/engine-adapter/src/ffi/xace_ffi.rs) | Rust | 199 | 65 | 37 | 301 |
| [packages/engine-adapter/src/transport\_mode.rs](/packages/engine-adapter/src/transport_mode.rs) | Rust | 33 | 22 | 10 | 65 |
| [packages/engine-adapter/src/transport\_selector.rs](/packages/engine-adapter/src/transport_selector.rs) | Rust | 85 | 26 | 18 | 129 |
| [packages/inference/src/credit\_system.py](/packages/inference/src/credit_system.py) | Python | 182 | 136 | 43 | 361 |
| [packages/inference/src/local\_model\_manager.py](/packages/inference/src/local_model_manager.py) | Python | 303 | 120 | 62 | 485 |
| [packages/inference/src/model\_router.py](/packages/inference/src/model_router.py) | Python | 22 | -106 | 1 | -83 |
| [packages/inference/src/telemetry\_pipeline.py](/packages/inference/src/telemetry_pipeline.py) | Python | 4 | 0 | 0 | 4 |
| [packages/inference/tests/test\_credit\_system.py](/packages/inference/tests/test_credit_system.py) | Python | 130 | 8 | 40 | 178 |
| [packages/inference/tests/test\_hybrid\_routing.py](/packages/inference/tests/test_hybrid_routing.py) | Python | 156 | 21 | 56 | 233 |
| [packages/inference/tests/test\_local\_model\_manager.py](/packages/inference/tests/test_local_model_manager.py) | Python | 92 | 17 | 29 | 138 |
| [packages/observability/src/crash\_reporter.rs](/packages/observability/src/crash_reporter.rs) | Rust | 186 | 85 | 46 | 317 |
| [packages/observability/src/health\_check.rs](/packages/observability/src/health_check.rs) | Rust | 108 | 47 | 23 | 178 |
| [packages/observability/src/http\_server.rs](/packages/observability/src/http_server.rs) | Rust | 107 | 44 | 19 | 170 |
| [packages/observability/src/lib.rs](/packages/observability/src/lib.rs) | Rust | 15 | 39 | 3 | 57 |
| [packages/observability/src/metrics.rs](/packages/observability/src/metrics.rs) | Rust | 176 | 58 | 46 | 280 |
| [packages/observability/src/metrics\_registry.rs](/packages/observability/src/metrics_registry.rs) | Rust | 104 | 28 | 28 | 160 |
| [packages/observability/src/observable.rs](/packages/observability/src/observable.rs) | Rust | 96 | 76 | 41 | 213 |
| [packages/observability/src/tick\_ring\_buffer.rs](/packages/observability/src/tick_ring_buffer.rs) | Rust | 114 | 48 | 28 | 190 |
| [packages/observability/src/trace.rs](/packages/observability/src/trace.rs) | Rust | 144 | 52 | 43 | 239 |
| [packages/observability/src/tracer.rs](/packages/observability/src/tracer.rs) | Rust | 167 | 66 | 53 | 286 |
| [packages/observability/tests/test\_crash\_reporter.rs](/packages/observability/tests/test_crash_reporter.rs) | Rust | 102 | 10 | 18 | 130 |
| [packages/observability/tests/test\_metrics.rs](/packages/observability/tests/test_metrics.rs) | Rust | 139 | 7 | 23 | 169 |
| [packages/observability/tests/test\_trace.rs](/packages/observability/tests/test_trace.rs) | Rust | 97 | 8 | 13 | 118 |
| [packages/runtime-core/src/component\_tables/archetype.rs](/packages/runtime-core/src/component_tables/archetype.rs) | Rust | 169 | 86 | 39 | 294 |
| [packages/runtime-core/src/component\_tables/archetype\_index.rs](/packages/runtime-core/src/component_tables/archetype_index.rs) | Rust | 86 | 46 | 28 | 160 |
| [packages/runtime-core/src/component\_tables/archetype\_storage.rs](/packages/runtime-core/src/component_tables/archetype_storage.rs) | Rust | 230 | 104 | 55 | 389 |
| [packages/runtime-core/src/component\_tables/mod.rs](/packages/runtime-core/src/component_tables/mod.rs) | Rust | 8 | 9 | 0 | 17 |
| [packages/runtime-core/src/component\_tables/storage\_router.rs](/packages/runtime-core/src/component_tables/storage_router.rs) | Rust | 59 | 35 | 12 | 106 |
| [packages/runtime-core/src/component\_tables/storage\_strategy.rs](/packages/runtime-core/src/component_tables/storage_strategy.rs) | Rust | 43 | 59 | 18 | 120 |
| [packages/runtime-core/src/query\_engine/mod.rs](/packages/runtime-core/src/query_engine/mod.rs) | Rust | 4 | 0 | 0 | 4 |
| [packages/runtime-core/src/query\_engine/sorted\_merge\_iterator.rs](/packages/runtime-core/src/query_engine/sorted_merge_iterator.rs) | Rust | 89 | 63 | 22 | 174 |
| [packages/runtime-core/src/query\_engine/vectorized\_query.rs](/packages/runtime-core/src/query_engine/vectorized_query.rs) | Rust | 63 | 34 | 19 | 116 |

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details