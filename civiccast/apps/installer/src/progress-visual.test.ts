// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { describe, expect, it } from "vitest";

import { installerActivityElapsedSeconds, isRuntimeBootstrapProgress } from "./progress-visual";
import type { InstallerProgress } from "./types";

function progress(overrides: Partial<InstallerProgress> = {}): InstallerProgress {
  return {
    schema_version: 1,
    current_lane_id: "platform",
    status: "running",
    message: "Preparing CivicCast components",
    reboot_required: false,
    updated_at_unix: 1,
    activity_current: 1,
    activity_total: 2,
    ...overrides
  };
}

describe("progress-visual", () => {
  it("recognizes long-running runtime setup so the UI can show a live heartbeat", () => {
    expect(isRuntimeBootstrapProgress(progress({ current_lane_id: "runtime" }))).toBe(true);
    expect(isRuntimeBootstrapProgress(progress({ current_lane_id: "runtime", status: "ready" }))).toBe(false);
  });

  it("keeps elapsed activity moving even when the native phase message is unchanged", () => {
    expect(
      installerActivityElapsedSeconds(
        progress({ updated_at_unix: 100, started_at_unix: undefined, elapsed_seconds: undefined }),
        137
      )
    ).toBe(37);
    expect(
      installerActivityElapsedSeconds(
        progress({ updated_at_unix: 130, started_at_unix: 100, elapsed_seconds: 45 }),
        137
      )
    ).toBe(45);
  });
});
