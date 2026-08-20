import { defineConfig } from "vitest/config";

// Standalone so vitest's config typing never leaks into the production vite.config.ts /
// tsc build. Unit tests only: `npm run test:unit`.
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"]
  }
});
