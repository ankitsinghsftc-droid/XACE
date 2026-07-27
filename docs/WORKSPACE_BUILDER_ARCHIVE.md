# Workspace Builder Archive

`workspace/builder` was the original placeholder Builder package. It has been
archived in favor of the canonical Builder at `packages/builder-workspace`.

Diff result before archive:

- `workspace/builder/package.json` was a standalone React/Vite package.
- `workspace/builder/tsconfig.json` was a basic TSX config.
- `workspace/builder/src/main.tsx` contained only an app-entry comment.
- `workspace/builder/src/canvas/index.tsx` contained only a Builder canvas comment.
- `workspace/builder/src/sidebar/index.tsx` contained only a CGS sidebar comment.
- `workspace/builder/src/bottom_bar/index.tsx` contained only a bottom-bar comment.
- `workspace/builder/src/preview/index.tsx` contained only a preview-panel comment.
- `workspace/builder/src/command_palette/index.tsx` contained only a command-palette comment.
- `workspace/builder/src/graph_view/index.tsx` contained only a graph-view comment.

No unique implementation remained in `workspace/builder`; root npm scripts now
target `packages/builder-workspace`.
