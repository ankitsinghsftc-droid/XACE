# Diff Details

Date : 2026-05-29 17:07:29

Directory c:\\Users\\ankit\\Downloads\\xace

Total : 37 files,  5979 codes, -103 comments, 636 blanks, all 6512 lines

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [packages/network-core/network\_mode.py](/packages/network-core/network_mode.py) | Python | 75 | 13 | 21 | 109 |
| [packages/network-core/network\_orchestrator.py](/packages/network-core/network_orchestrator.py) | Python | 260 | 7 | 40 | 307 |
| [packages/network-core/src/authority/authority\_resolver.rs](/packages/network-core/src/authority/authority_resolver.rs) | Rust | 377 | 0 | 34 | 411 |
| [packages/network-core/src/authority/authority\_transfer.rs](/packages/network-core/src/authority/authority_transfer.rs) | Rust | 224 | 0 | 23 | 247 |
| [packages/network-core/src/authority/cheat\_guard.rs](/packages/network-core/src/authority/cheat_guard.rs) | Rust | 509 | 0 | 33 | 542 |
| [packages/network-core/src/authority/mod.rs](/packages/network-core/src/authority/mod.rs) | Rust | 7 | 0 | 0 | 7 |
| [packages/network-core/src/input/input\_broadcaster.rs](/packages/network-core/src/input/input_broadcaster.rs) | Rust | 216 | 0 | 28 | 244 |
| [packages/network-core/src/input/mod.rs](/packages/network-core/src/input/mod.rs) | Rust | 3 | 0 | 0 | 3 |
| [packages/network-core/src/prediction/client\_predictor.rs](/packages/network-core/src/prediction/client_predictor.rs) | Rust | 212 | 0 | 24 | 236 |
| [packages/network-core/src/prediction/mod.rs](/packages/network-core/src/prediction/mod.rs) | Rust | 7 | 0 | 0 | 7 |
| [packages/network-core/src/prediction/prediction\_buffer.rs](/packages/network-core/src/prediction/prediction_buffer.rs) | Rust | 119 | 0 | 18 | 137 |
| [packages/network-core/src/prediction/reconciliation\_engine.rs](/packages/network-core/src/prediction/reconciliation_engine.rs) | Rust | 121 | 0 | 10 | 131 |
| [packages/network-core/src/prediction/rollback\_manager.rs](/packages/network-core/src/prediction/rollback_manager.rs) | Rust | 193 | 0 | 24 | 217 |
| [packages/network-core/src/replication/interest\_zone\_manager.rs](/packages/network-core/src/replication/interest_zone_manager.rs) | Rust | 352 | 0 | 39 | 391 |
| [packages/network-core/src/replication/mod.rs](/packages/network-core/src/replication/mod.rs) | Rust | 8 | 0 | 0 | 8 |
| [packages/network-core/src/replication/relevance\_filter.rs](/packages/network-core/src/replication/relevance_filter.rs) | Rust | 254 | 0 | 27 | 281 |
| [packages/network-core/src/replication/replication\_manager.rs](/packages/network-core/src/replication/replication_manager.rs) | Rust | 387 | 0 | 40 | 427 |
| [packages/network-core/src/session/connection\_state.rs](/packages/network-core/src/session/connection_state.rs) | Rust | 26 | 0 | 1 | 27 |
| [packages/network-core/src/session/mod.rs](/packages/network-core/src/session/mod.rs) | Rust | 2 | 0 | 0 | 2 |
| [packages/network-core/src/session/peer.rs](/packages/network-core/src/session/peer.rs) | Rust | 100 | 0 | 12 | 112 |
| [packages/network-core/src/session/peer\_manager.rs](/packages/network-core/src/session/peer_manager.rs) | Rust | 115 | 0 | 16 | 131 |
| [packages/network-core/src/session/session\_manager.rs](/packages/network-core/src/session/session_manager.rs) | Rust | 374 | 0 | 42 | 416 |
| [packages/network-core/src/synchronisation/desync\_detector.rs](/packages/network-core/src/synchronisation/desync_detector.rs) | Rust | 174 | 0 | 21 | 195 |
| [packages/network-core/src/synchronisation/late\_join\_handler.rs](/packages/network-core/src/synchronisation/late_join_handler.rs) | Rust | 177 | 0 | 22 | 199 |
| [packages/network-core/src/synchronisation/mod.rs](/packages/network-core/src/synchronisation/mod.rs) | Rust | 6 | 0 | 0 | 6 |
| [packages/network-core/src/synchronisation/resync\_engine.rs](/packages/network-core/src/synchronisation/resync_engine.rs) | Rust | 249 | 0 | 24 | 273 |
| [packages/network-core/src/synchronisation/tick\_barrier.rs](/packages/network-core/src/synchronisation/tick_barrier.rs) | Rust | 115 | 0 | 16 | 131 |
| [packages/network-core/tests/test\_broadcaster\_and\_peers.rs](/packages/network-core/tests/test_broadcaster_and_peers.rs) | Rust | 78 | 0 | 15 | 93 |
| [packages/network-core/tests/test\_cheat\_guard.rs](/packages/network-core/tests/test_cheat_guard.rs) | Rust | 119 | 0 | 12 | 131 |
| [packages/network-core/tests/test\_client\_prediction.rs](/packages/network-core/tests/test_client_prediction.rs) | Rust | 105 | 0 | 10 | 115 |
| [packages/network-core/tests/test\_desync\_detection.rs](/packages/network-core/tests/test_desync_detection.rs) | Rust | 98 | 0 | 14 | 112 |
| [packages/network-core/tests/test\_replication.rs](/packages/network-core/tests/test_replication.rs) | Rust | 149 | 0 | 21 | 170 |
| [packages/network-core/tests/test\_session\_authority.rs](/packages/network-core/tests/test_session_authority.rs) | Rust | 134 | 0 | 23 | 157 |
| [packages/runtime-core/src/cgs\_loader.rs](/packages/runtime-core/src/cgs_loader.rs) | Rust | 285 | -15 | 18 | 288 |
| [packages/runtime-core/src/engine\_bridge.rs](/packages/runtime-core/src/engine_bridge.rs) | Rust | 62 | -32 | -1 | 29 |
| [packages/runtime-core/src/engine\_protocol.rs](/packages/runtime-core/src/engine_protocol.rs) | Rust | 233 | -59 | 8 | 182 |
| [packages/runtime-core/src/tcp\_server.rs](/packages/runtime-core/src/tcp_server.rs) | Rust | 54 | -17 | 1 | 38 |

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details