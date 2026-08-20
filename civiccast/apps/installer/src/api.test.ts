// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  loadInstallerProgress,
  loadInstallerState,
  openInstallerLog,
  openOperatorConsole,
  stateFromLocalProgress
} from "./api";
import type { InstallerProgress } from "./types";

function progress(overrides: Partial<InstallerProgress>): InstallerProgress {
  return {
    schema_version: 1,
    current_lane_id: "wsl2",
    status: "blocked",
    message: "default message",
    reboot_required: false,
    updated_at_unix: 1,
    ...overrides
  };
}

describe("stateFromLocalProgress", () => {
  it("returns null when there is no saved progress", () => {
    expect(stateFromLocalProgress(null)).toBeNull();
  });

  it("shows a restart-required card as a blocked WSL-bootstrap lane (UX-1: not a clickable generic Continue)", () => {
    const state = stateFromLocalProgress(
      progress({ current_lane_id: "wsl2", reboot_required: true, message: "Windows needs a restart." })
    );
    expect(state?.ready).toBe(false);
    expect(state?.platform).toBe("windows-wsl2");
    expect(state?.lanes).toHaveLength(1);
    // "blocked" + platform windows-wsl2 + a wsl2/platform lane id is precisely what
    // isWslBootstrapLane() keys on, so the primary button reads "Set up Windows
    // helper" (enabled) and its click shows the WSL "several minutes" warning —
    // instead of the old "progress" mapping that rendered a generic "Continue"
    // that skipped the warning during the post-reboot stale window.
    expect(state?.lanes[0]).toMatchObject({
      id: "wsl2",
      status: "blocked",
      detail: "Windows needs a restart."
    });
  });

  it("splits into a ready platform lane plus a partial runtime lane once WSL reports ready", () => {
    const state = stateFromLocalProgress(progress({ current_lane_id: "platform", status: "ready" }));
    expect(state?.ready).toBe(false);
    expect(state?.lanes.map((lane) => [lane.id, lane.status, lane.ready])).toEqual([
      ["platform", "success", true],
      ["runtime", "partial", false]
    ]);
  });

  it("marks the runtime lane in progress while it is running", () => {
    const state = stateFromLocalProgress(
      progress({ current_lane_id: "runtime", status: "running", message: "Starting up." })
    );
    const runtimeLane = state?.lanes.find((lane) => lane.id === "runtime");
    expect(runtimeLane).toMatchObject({ status: "progress", ready: false, detail: "Starting up." });
  });

  it("marks the installer ready once the runtime lane reports ready", () => {
    const state = stateFromLocalProgress(progress({ current_lane_id: "runtime", status: "ready" }));
    expect(state?.ready).toBe(true);
  });

  it("maps a failed WSL bootstrap to an error lane, not blocked", () => {
    const state = stateFromLocalProgress(progress({ current_lane_id: "wsl2", status: "failed" }));
    expect(state?.lanes[0]).toMatchObject({
      status: "error",
      nextStep: "Use Open installer log below, then retry. If the failure repeats, send that log to support."
    });
  });

  it("shows automatic post-reboot WSL resume as active progress", () => {
    const state = stateFromLocalProgress(
      progress({
        current_lane_id: "wsl2",
        status: "wsl_resume_requested",
        reboot_required: false,
        message: "Windows restarted successfully. CivicCast is resuming Windows helper setup for this user."
      })
    );
    expect(state?.lanes[0]).toMatchObject({
      id: "wsl2",
      status: "progress",
      ready: false
    });
  });

  it("maps a failed runtime lane to an error lane", () => {
    const state = stateFromLocalProgress(progress({ current_lane_id: "runtime", status: "error" }));
    const runtimeLane = state?.lanes.find((lane) => lane.id === "runtime");
    expect(runtimeLane).toMatchObject({
      status: "error",
      nextStep: "Use Open installer log below, then retry. If the failure repeats, send that log to support."
    });
  });

  it("shows a temporarily unavailable runtime as automatic recovery, not a setup error", () => {
    const state = stateFromLocalProgress(
      progress({
        current_lane_id: "runtime",
        status: "unavailable",
        message: "CivicCast is restarting its background service."
      })
    );
    const runtimeLane = state?.lanes.find((lane) => lane.id === "runtime");
    expect(runtimeLane).toMatchObject({
      status: "progress",
      ready: false,
      detail: "CivicCast is restarting its background service.",
      nextStep: "Keep this window open while CivicCast recovers automatically."
    });
  });

  it("returns null for a lane id it does not recognize", () => {
    expect(stateFromLocalProgress(progress({ current_lane_id: "something-unknown" }))).toBeNull();
  });
});

describe("openInstallerLog", () => {
  afterEach(() => {
    delete (window as Window & { __TAURI__?: unknown }).__TAURI__;
  });

  it("uses the native installer command so the error screen's log action is real", async () => {
    const calls: string[] = [];
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async (command: string) => {
          calls.push(command);
          return "Opened the CivicCast installer log.";
        }
      }
    };

    await expect(openInstallerLog()).resolves.toBe("Opened the CivicCast installer log.");
    expect(calls).toEqual(["open_installer_log"]);
  });
});

describe("openOperatorConsole", () => {
  afterEach(() => {
    delete (window as Window & { __TAURI__?: unknown }).__TAURI__;
  });

  it("does not navigate the installer away when a background auto-open has no native bridge", async () => {
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: { invoke: async () => Promise.reject(new Error("native bridge unavailable")) }
    };

    await expect(openOperatorConsole("http://127.0.0.1:8000/operator/", false)).rejects.toThrow(
      "native bridge unavailable"
    );
  });
});

describe("loadInstallerProgress (UX-3 / G-9b: no stale-cache resurrection)", () => {
  afterEach(() => {
    window.localStorage.clear();
    delete (window as Window & { __TAURI__?: unknown }).__TAURI__;
  });

  it("returns the native progress and clears any stale browser cache", async () => {
    window.localStorage.setItem(
      "civiccast.installerProgress",
      JSON.stringify(progress({ current_lane_id: "wsl2", status: "error", message: "stale error" }))
    );
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: {
        invoke: async () =>
          JSON.stringify(progress({ current_lane_id: "runtime", status: "ready", message: "fresh" }))
      }
    };

    const result = await loadInstallerProgress();

    expect(result?.message).toBe("fresh");
    expect(window.localStorage.getItem("civiccast.installerProgress")).toBeNull();
  });

  it("a native read that succeeds with 'null' must not resurrect an older browser-cached error", async () => {
    window.localStorage.setItem(
      "civiccast.installerProgress",
      JSON.stringify(progress({ current_lane_id: "wsl2", status: "error", message: "stale error from a prior attempt" }))
    );
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: { invoke: async () => "null" }
    };

    const result = await loadInstallerProgress();

    expect(result).toBeNull();
    expect(window.localStorage.getItem("civiccast.installerProgress")).toBeNull();
  });

  it("falls back to the browser cache only when there is no native bridge at all", async () => {
    window.localStorage.setItem(
      "civiccast.installerProgress",
      JSON.stringify(progress({ current_lane_id: "wsl2", status: "error", message: "browser-preview fallback" }))
    );
    // No window.__TAURI__ at all: invoke throws, matching a plain browser preview.

    const result = await loadInstallerProgress();

    expect(result?.message).toBe("browser-preview fallback");
  });
});

describe("loadInstallerState unreachable-API fallback (N-07 carried)", () => {
  // N-07: the first-run wizard's "Platform" header read "windows-wsl2" on the
  // NATIVE build. Root cause: `installerFixtures.blocked` -- the catch-all
  // fallback `loadInstallerState` returns when both the native progress read
  // and the `/api/staff/installer/summary` fetch fail (exactly the shape of
  // a fresh launch before the supervisor's control-plane child has bound its
  // port yet) -- hardcodes `platform: "windows-wsl2"` regardless of which
  // build is actually running. A native Tauri station reported itself as the
  // WSL2 deployment during that brief unreachable window.
  afterEach(() => {
    vi.unstubAllGlobals();
    delete (window as Window & { __TAURI__?: unknown }).__TAURI__;
    window.localStorage.clear();
  });

  it("never reports windows-wsl2 for a native station just because the API is not answering yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED: local control plane not listening yet");
      })
    );
    // A native bridge (Tauri) with no local progress file yet is exactly a
    // freshly-launched native station before its first status write.
    (window as Window & { __TAURI__?: unknown }).__TAURI__ = {
      core: { invoke: async () => { throw new Error("no local installer state file yet"); } }
    };

    const state = await loadInstallerState();

    expect(state.platform).not.toBe("windows-wsl2");
    expect(state.platform).toBe("windows-native");
  });

  it("keeps reporting windows-wsl2 for the browser-preview / WSL2 web installer (no native bridge)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      })
    );
    // No window.__TAURI__ at all: matches a plain browser preview or the
    // WSL2-guest web installer, neither of which is the native build.

    const state = await loadInstallerState();

    expect(state.platform).toBe("windows-wsl2");
  });
});
