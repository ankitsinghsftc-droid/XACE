import { defineConfig } from 'vite';

export default defineConfig(({ mode }) => ({
  root: '.',

  resolve: {
    alias: {
      '@': '/src',
    },
  },

  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/ws': {
        target:       'ws://127.0.0.1:8765',
        ws:           true,
        changeOrigin: true,
      },
      '/api': {
        target:       'http://127.0.0.1:8765',
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