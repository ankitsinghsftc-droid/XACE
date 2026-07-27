import { defineConfig } from 'vite';

const builderPort = Number(process.env.VITE_BUILDER_PORT ?? '8765');
const builderHttpTarget = `http://127.0.0.1:${builderPort}`;
const builderWsTarget = `ws://127.0.0.1:${builderPort}`;

export default defineConfig(({ mode }) => ({
  root: '.',

  resolve: {
    alias: {
      '@': '/src',
    },
  },

  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      '/ws': {
        target:       builderWsTarget,
        ws:           true,
        changeOrigin: true,
      },
      '/api': {
        target:       builderHttpTarget,
        changeOrigin: true,
      },
    },
  },

  build: {
    outDir:                '../builder-server/dist',
    emptyOutDir:           true,
    sourcemap:             mode === 'development',
    target:                'es2022',
    chunkSizeWarningLimit: 600,
  },

  esbuild: {
    target: 'es2022',
  },
}));
