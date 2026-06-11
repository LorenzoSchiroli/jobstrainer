import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['**/__tests__/**/*.test.ts', '**/*.test.ts', '**/__tests__/**/*.test.js', '**/*.test.js'],
    globals: true,
    environment: 'node',
  },
});
