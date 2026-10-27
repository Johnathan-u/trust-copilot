import path from 'path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/unit/**/*.test.ts', 'lib/**/*.test.ts'],
    // TC-02-006: an empty suite must fail the gate, never pass silently.
    passWithNoTests: false,
    restoreMocks: true,
    unstubEnvs: true,
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, '.') },
  },
})
