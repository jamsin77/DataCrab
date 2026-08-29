import { defineConfig } from '@playwright/test'
import * as fs from 'fs'

const storageStatePath = 'tests/e2e/storage-state.json'

export default defineConfig({
  testDir: '.',
  timeout: 600000,
  expect: { timeout: 30000 },
  globalSetup: require.resolve('./global-setup.ts'),
  use: {
    baseURL: 'http://localhost:5173',
    headless: false,
    viewport: { width: 1400, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
    storageState: storageStatePath,
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
})
