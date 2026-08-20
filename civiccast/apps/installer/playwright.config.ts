// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { defineConfig, devices } from "@playwright/test";

const browserExecutable = process.env.CIVICCAST_PLAYWRIGHT_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  webServer: {
    command: "npm run dev -- --port 4177",
    url: "http://127.0.0.1:4177",
    reuseExistingServer: !process.env.CI
  },
  use: {
    baseURL: "http://127.0.0.1:4177",
    launchOptions: browserExecutable ? { executablePath: browserExecutable } : undefined,
    trace: "on-first-retry"
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"] }
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"] }
    }
  ]
});
