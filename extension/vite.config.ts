import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig(({ mode }) => {
  const isServiceWorker = process.env.ENTRY === 'sw';

  if (isServiceWorker) {
    return {
      build: {
        outDir: 'dist',
        emptyOutDir: false,
        lib: {
          entry: resolve(__dirname, 'background/service_worker.ts'),
          name: 'ServiceWorker',
          formats: ['iife'],
          fileName: () => 'background/service_worker.js',
        },
        rollupOptions: {
          output: { inlineDynamicImports: true },
        },
      },
      resolve: {
        alias: { '@background': resolve(__dirname, 'background') },
      },
    };
  }

  return {
    plugins: [react()],
    build: {
      outDir: 'dist/sidepanel',
      emptyOutDir: false,
      rollupOptions: {
        input: resolve(__dirname, 'sidepanel/index.html'),
      },
    },
    resolve: {
      alias: { '@sidepanel': resolve(__dirname, 'sidepanel/src') },
    },
  };
});
