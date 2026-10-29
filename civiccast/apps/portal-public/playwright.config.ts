import { defineConfig, devices } from '@playwright/test'

const browserExecutable = process.env.CIVICCAST_PLAYWRIGHT_EXECUTABLE

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://localhost:4173',
    launchOptions: browserExecutable ? { executablePath: browserExecutable } : undefined,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'webkit',
      // Hosted Linux WebKit native-HLS startup stalled in alternating media
      // tests when two workers decoded concurrently (CI40817664341 attempts1/2).
      // Keep every playback assertion, with one native-media worker in CI.
      workers: process.env.CI ? 1 : undefined,
      use: { ...devices['Desktop Safari'] },
    },
  ],
  webServer: {
    command: 'npm run preview -- --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
