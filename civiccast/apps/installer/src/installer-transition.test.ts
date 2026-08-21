// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { describe, expect, it } from "vitest";

import { firstActionableLane } from "./installer-transition";
import type { InstallerLane, InstallerState } from "./types";

describe("firstActionableLane", () => {
  const lane = (overrides: Partial<InstallerLane> & { id: string }): InstallerLane => ({
    label: overrides.id,
    status: "blocked",
    ready: false,
    detail: "",
    nextStep: "",
    ...overrides
  });
  const state = (lanes: InstallerLane[]): InstallerState => ({
    ready: false,
    platform: "windows-native",
    lanes
  });

  it("skips an unavailable optional capability in favor of a step that still needs setup", () => {
    const installer = state([
      lane({ id: "platform", status: "success", ready: true }),
      lane({ id: "ffmpeg", status: "unavailable" }),
      lane({ id: "storage", status: "blocked" })
    ]);

    expect(firstActionableLane(installer)?.id).toBe("storage");
  });

  it("still opens on the unavailable lane when nothing else is outstanding", () => {
    const installer = state([
      lane({ id: "platform", status: "success", ready: true }),
      lane({ id: "ffmpeg", status: "unavailable" })
    ]);

    expect(firstActionableLane(installer)?.id).toBe("ffmpeg");
  });

  it("keeps returning the first unready lane when no lane is unavailable", () => {
    const installer = state([
      lane({ id: "platform", status: "success", ready: true }),
      lane({ id: "runtime", status: "blocked" }),
      lane({ id: "storage", status: "blocked" })
    ]);

    expect(firstActionableLane(installer)?.id).toBe("runtime");
  });

  it("falls back to the first lane when every lane is ready", () => {
    const installer = state([
      lane({ id: "platform", status: "success", ready: true }),
      lane({ id: "storage", status: "success", ready: true })
    ]);

    expect(firstActionableLane(installer)?.id).toBe("platform");
  });
});
