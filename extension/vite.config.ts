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
          external: ['chrome'],
          output: {
            inlineDynamicImports: true,
            globals: { chrome: 'chrome' },
          },
        },
      },
      resolve: {
        alias: {
          '@background': resolve(__dirname, 'background'),
          '@puppeteer/browsers': resolve(__dirname, 'stubs/puppeteer-browsers.ts'),
        },
        conditions: ['browser', 'module', 'import', 'default'],
        mainFields: ['browser', 'module', 'main'],
      },
    };
  }

  return {
    root: resolve(__dirname, 'sidepanel'),
    base: './',
    plugins: [react()],
    publicDir: false,
    build: {
      outDir: resolve(__dirname, 'dist/sidepanel'),
      emptyOutDir: false,
    },
    resolve: {
      alias: { '@sidepanel': resolve(__dirname, 'sidepanel/src') },
    },
  };
});
