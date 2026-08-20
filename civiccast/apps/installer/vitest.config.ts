import { defineConfig } from "vitest/config";

// Standalone so vitest's config typing never leaks into the production vite.config.ts /
// tsc build. Unit tests only: `npm run test:unit`.
export default defineConfig({
  test: {
    environment: "jsdom",
    // Repairs Web Storage when the host Node ships its own globals and jsdom's
    // Storage never gets installed -- see vitest.setup.ts.
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts"]
  }
});
