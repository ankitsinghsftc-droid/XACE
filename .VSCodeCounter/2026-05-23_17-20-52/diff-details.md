# Diff Details

Date : 2026-05-23 17:20:52

Directory c:\\Users\\ankit\\Downloads\\xace

Total : 76 files,  6420 codes, 766 comments, 761 blanks, all 7947 lines

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [XACE\_File\_Manifest\_v2.md](/XACE_File_Manifest_v2.md) | Markdown | -291 | 0 | -1 | -292 |
| [game.cgs.json](/game.cgs.json) | JSON | 197 | 0 | 1 | 198 |
| [packages/builder-workspace/api/builder\_client.ts](/packages/builder-workspace/api/builder_client.ts) | TypeScript | -221 | -49 | -56 | -326 |
| [packages/builder-workspace/api/message\_types.ts](/packages/builder-workspace/api/message_types.ts) | TypeScript | -170 | -53 | -33 | -256 |
| [packages/builder-workspace/canvas/clarification\_cards.ts](/packages/builder-workspace/canvas/clarification_cards.ts) | TypeScript | -384 | -23 | -29 | -436 |
| [packages/builder-workspace/canvas/diff\_viewer.ts](/packages/builder-workspace/canvas/diff_viewer.ts) | TypeScript | -255 | -22 | -33 | -310 |
| [packages/builder-workspace/canvas/prompt\_input.ts](/packages/builder-workspace/canvas/prompt_input.ts) | TypeScript | -303 | -33 | -37 | -373 |
| [packages/builder-workspace/graph/schema\_graph\_view.ts](/packages/builder-workspace/graph/schema_graph_view.ts) | TypeScript | -523 | -58 | -93 | -674 |
| [packages/builder-workspace/graph/system\_node\_graph.ts](/packages/builder-workspace/graph/system_node_graph.ts) | TypeScript | -315 | -18 | -40 | -373 |
| [packages/builder-workspace/layout/bottom\_bar.ts](/packages/builder-workspace/layout/bottom_bar.ts) | TypeScript | -430 | -21 | -35 | -486 |
| [packages/builder-workspace/ollama\_adapter.py](/packages/builder-workspace/ollama_adapter.py) | Python | 177 | 70 | 34 | 281 |
| [packages/builder-workspace/package-lock.json](/packages/builder-workspace/package-lock.json) | JSON | 1,041 | 0 | 1 | 1,042 |
| [packages/builder-workspace/package.json](/packages/builder-workspace/package.json) | JSON | -2 | 0 | 0 | -2 |
| [packages/builder-workspace/server/builder\_server.py](/packages/builder-workspace/server/builder_server.py) | Python | 97 | 14 | 0 | 111 |
| [packages/builder-workspace/server/cgs\_persistence.py](/packages/builder-workspace/server/cgs_persistence.py) | Python | 29 | 22 | 6 | 57 |
| [packages/builder-workspace/server/session\_manager.py](/packages/builder-workspace/server/session_manager.py) | Python | 490 | 47 | 89 | 626 |
| [packages/builder-workspace/server/ws\_message\_router.py](/packages/builder-workspace/server/ws_message_router.py) | Python | 71 | -6 | 10 | 75 |
| [packages/builder-workspace/sidebar/cgs\_explorer.ts](/packages/builder-workspace/sidebar/cgs_explorer.ts) | TypeScript | 0 | 0 | -1 | -1 |
| [packages/builder-workspace/sidebar/component\_inspector.ts](/packages/builder-workspace/sidebar/component_inspector.ts) | TypeScript | -229 | -23 | -26 | -278 |
| [packages/builder-workspace/sidebar/entity\_tree.ts](/packages/builder-workspace/sidebar/entity_tree.ts) | TypeScript | -349 | -24 | -40 | -413 |
| [packages/builder-workspace/sidebar/system\_list.ts](/packages/builder-workspace/sidebar/system_list.ts) | TypeScript | -239 | -12 | -35 | -286 |
| [packages/builder-workspace/src/api/builder\_client.ts](/packages/builder-workspace/src/api/builder_client.ts) | TypeScript | 221 | 49 | 56 | 326 |
| [packages/builder-workspace/src/api/message\_types.ts](/packages/builder-workspace/src/api/message_types.ts) | TypeScript | 177 | 54 | 34 | 265 |
| [packages/builder-workspace/src/app.ts](/packages/builder-workspace/src/app.ts) | TypeScript | 41 | -4 | -6 | 31 |
| [packages/builder-workspace/src/canvas/builder\_canvas.ts](/packages/builder-workspace/src/canvas/builder_canvas.ts) | TypeScript | 271 | 53 | 55 | 379 |
| [packages/builder-workspace/src/canvas/clarification\_cards.ts](/packages/builder-workspace/src/canvas/clarification_cards.ts) | TypeScript | 384 | 23 | 29 | 436 |
| [packages/builder-workspace/src/canvas/diff\_viewer.ts](/packages/builder-workspace/src/canvas/diff_viewer.ts) | TypeScript | 255 | 22 | 33 | 310 |
| [packages/builder-workspace/src/canvas/model\_selector.ts](/packages/builder-workspace/src/canvas/model_selector.ts) | TypeScript | 308 | 20 | 29 | 357 |
| [packages/builder-workspace/src/canvas/prompt\_input.ts](/packages/builder-workspace/src/canvas/prompt_input.ts) | TypeScript | 306 | 34 | 38 | 378 |
| [packages/builder-workspace/src/command\_palette/command\_palette.ts](/packages/builder-workspace/src/command_palette/command_palette.ts) | TypeScript | 249 | 20 | 28 | 297 |
| [packages/builder-workspace/src/command\_palette/search\_engine.ts](/packages/builder-workspace/src/command_palette/search_engine.ts) | TypeScript | 175 | 32 | 25 | 232 |
| [packages/builder-workspace/src/console/decision\_bar.ts](/packages/builder-workspace/src/console/decision_bar.ts) | TypeScript | 249 | 20 | 28 | 297 |
| [packages/builder-workspace/src/console/ingame\_console.ts](/packages/builder-workspace/src/console/ingame_console.ts) | TypeScript | 1 | 7 | 1 | 9 |
| [packages/builder-workspace/src/console/xace\_terminal.ts](/packages/builder-workspace/src/console/xace_terminal.ts) | TypeScript | 361 | 37 | 49 | 447 |
| [packages/builder-workspace/src/graph/schema\_graph\_view.ts](/packages/builder-workspace/src/graph/schema_graph_view.ts) | TypeScript | 523 | 58 | 93 | 674 |
| [packages/builder-workspace/src/graph/system\_node\_graph.ts](/packages/builder-workspace/src/graph/system_node_graph.ts) | TypeScript | 315 | 18 | 40 | 373 |
| [packages/builder-workspace/src/layout/bottom\_bar.ts](/packages/builder-workspace/src/layout/bottom_bar.ts) | TypeScript | 430 | 21 | 35 | 486 |
| [packages/builder-workspace/src/layout/main\_layout.ts](/packages/builder-workspace/src/layout/main_layout.ts) | TypeScript | 486 | 47 | 49 | 582 |
| [packages/builder-workspace/src/panels/asset\_link\_dialog.ts](/packages/builder-workspace/src/panels/asset_link_dialog.ts) | TypeScript | 1 | 6 | 0 | 7 |
| [packages/builder-workspace/src/panels/asset\_status\_panel.ts](/packages/builder-workspace/src/panels/asset_status_panel.ts) | TypeScript | 277 | 29 | 40 | 346 |
| [packages/builder-workspace/src/preview/engine\_viewport.ts](/packages/builder-workspace/src/preview/engine_viewport.ts) | TypeScript | 253 | 39 | 29 | 321 |
| [packages/builder-workspace/src/preview/entity\_inspector.ts](/packages/builder-workspace/src/preview/entity_inspector.ts) | TypeScript | 384 | 27 | 44 | 455 |
| [packages/builder-workspace/src/preview/runtime\_stats.ts](/packages/builder-workspace/src/preview/runtime_stats.ts) | TypeScript | 168 | 15 | 26 | 209 |
| [packages/builder-workspace/src/preview/tick\_debugger.ts](/packages/builder-workspace/src/preview/tick_debugger.ts) | TypeScript | 165 | 19 | 18 | 202 |
| [packages/builder-workspace/src/sidebar/cgs\_explorer.ts](/packages/builder-workspace/src/sidebar/cgs_explorer.ts) | TypeScript | 367 | 22 | 43 | 432 |
| [packages/builder-workspace/src/sidebar/component\_inspector.ts](/packages/builder-workspace/src/sidebar/component_inspector.ts) | TypeScript | 229 | 23 | 26 | 278 |
| [packages/builder-workspace/src/sidebar/entity\_tree.ts](/packages/builder-workspace/src/sidebar/entity_tree.ts) | TypeScript | 349 | 24 | 40 | 413 |
| [packages/builder-workspace/src/sidebar/system\_list.ts](/packages/builder-workspace/src/sidebar/system_list.ts) | TypeScript | 240 | 12 | 35 | 287 |
| [packages/builder-workspace/src/state/cgs\_store.ts](/packages/builder-workspace/src/state/cgs_store.ts) | TypeScript | 162 | 62 | 35 | 259 |
| [packages/builder-workspace/src/state/console\_state\_machine.ts](/packages/builder-workspace/src/state/console_state_machine.ts) | TypeScript | 252 | 84 | 50 | 386 |
| [packages/builder-workspace/src/state/ui\_store.ts](/packages/builder-workspace/src/state/ui_store.ts) | TypeScript | 157 | 36 | 48 | 241 |
| [packages/builder-workspace/src/telemetry/cost\_chart.ts](/packages/builder-workspace/src/telemetry/cost_chart.ts) | TypeScript | 223 | 21 | 28 | 272 |
| [packages/builder-workspace/src/telemetry/inference\_telemetry\_panel.ts](/packages/builder-workspace/src/telemetry/inference_telemetry_panel.ts) | TypeScript | 1 | 5 | 0 | 6 |
| [packages/builder-workspace/src/types/cgs.ts](/packages/builder-workspace/src/types/cgs.ts) | TypeScript | 260 | 38 | 49 | 347 |
| [packages/builder-workspace/src/types/pil.ts](/packages/builder-workspace/src/types/pil.ts) | TypeScript | 235 | 25 | 44 | 304 |
| [packages/builder-workspace/src/views/processing\_view.ts](/packages/builder-workspace/src/views/processing_view.ts) | TypeScript | 315 | 28 | 59 | 402 |
| [packages/builder-workspace/state/cgs\_store.ts](/packages/builder-workspace/state/cgs_store.ts) | TypeScript | -162 | -62 | -35 | -259 |
| [packages/builder-workspace/state/console\_state\_machine.ts](/packages/builder-workspace/state/console_state_machine.ts) | TypeScript | -252 | -84 | -50 | -386 |
| [packages/builder-workspace/state/ui\_store.ts](/packages/builder-workspace/state/ui_store.ts) | TypeScript | -158 | -36 | -48 | -242 |
| [packages/builder-workspace/tsconfig.json](/packages/builder-workspace/tsconfig.json) | JSON with Comments | -1 | 0 | -6 | -7 |
| [packages/builder-workspace/tsconfig.node.json](/packages/builder-workspace/tsconfig.node.json) | JSON | 11 | 0 | 0 | 11 |
| [packages/builder-workspace/types/cgs.ts](/packages/builder-workspace/types/cgs.ts) | TypeScript | -260 | -38 | -49 | -347 |
| [packages/builder-workspace/types/pil.ts](/packages/builder-workspace/types/pil.ts) | TypeScript | -235 | -25 | -44 | -304 |
| [packages/builder-workspace/view/processing\_view.ts](/packages/builder-workspace/view/processing_view.ts) | TypeScript | -316 | -28 | -59 | -403 |
| [packages/builder-workspace/vite.config.ts](/packages/builder-workspace/vite.config.ts) | TypeScript | -7 | -4 | 0 | -11 |
| [packages/prompt-intelligence/src/memory/memory\_store.py](/packages/prompt-intelligence/src/memory/memory_store.py) | Python | 89 | 4 | 22 | 115 |
| [packages/prompt-intelligence/src/pil\_pipeline.py](/packages/prompt-intelligence/src/pil_pipeline.py) | Python | 0 | 0 | 1 | 1 |
| [packages/runtime-core/src/bin/xace\_runtime.rs](/packages/runtime-core/src/bin/xace_runtime.rs) | Rust | 119 | 37 | 25 | 181 |
| [packages/runtime-core/src/builtin\_systems.rs](/packages/runtime-core/src/builtin_systems.rs) | Rust | 54 | 35 | 20 | 109 |
| [packages/runtime-core/src/cgs\_loader.rs](/packages/runtime-core/src/cgs_loader.rs) | Rust | 126 | 13 | 30 | 169 |
| [packages/runtime-core/src/lib.rs](/packages/runtime-core/src/lib.rs) | Rust | 4 | 3 | 1 | 8 |
| [packages/runtime-core/src/query\_engine/mod.rs](/packages/runtime-core/src/query_engine/mod.rs) | Rust | -1 | 3 | 0 | 2 |
| [packages/runtime-core/src/runtime\_orchestrator.rs](/packages/runtime-core/src/runtime_orchestrator.rs) | Rust | 77 | 26 | 17 | 120 |
| [packages/runtime-core/src/state\_printer.rs](/packages/runtime-core/src/state_printer.rs) | Rust | 74 | 19 | 14 | 107 |
| [packages/system-graph-compiler/src/main.rs](/packages/system-graph-compiler/src/main.rs) | Rust | 76 | 66 | 11 | 153 |
| [tsconfig.json](/tsconfig.json) | JSON with Comments | 1 | 0 | -1 | 0 |

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details