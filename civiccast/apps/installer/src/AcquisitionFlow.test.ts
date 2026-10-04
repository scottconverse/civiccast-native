// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// BLOCKER #54 fix regression test: before this fix, nothing on the frontend
// ever called the backend's component-download driver (`start_acquisition`),
// so the downloading screen's rows sat on "Waiting" forever
// (audit-lite FINDING-001). This proves `DownloadingScreen` calls it exactly
// ONCE on mount -- not once per poll tick, which fires every 500ms-2s for
// the whole (potentially multi-minute) download.
//
// No JSX here (kept a plain `.ts` file, not `.tsx`) because vitest.config.ts
// only globs `src/**/*.test.ts` -- see that file's comment. `createElement`
// stands in for JSX without needing to widen that glob.
// No `@testing-library/react` dependency exists in this project (see
// package.json); this drives `react-dom/client` + `react-dom/test-utils`
// directly, the same primitives that library itself wraps.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadingScreen } from "./AcquisitionFlow";

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

function installTauriBridge(invoke: Bridge["invoke"]): void {
  (window as unknown as { __TAURI__: Bridge }).__TAURI__ = { invoke };
}

function removeTauriBridge(): void {
  delete (window as unknown as { __TAURI__?: Bridge }).__TAURI__;
}

function startAcquisitionCallCount(invokeMock: ReturnType<typeof vi.fn<Bridge["invoke"]>>): number {
  return invokeMock.mock.calls.filter(
    ([command]) => command === "start_acquisition" || command === "startAcquisition"
  ).length;
}

describe("DownloadingScreen entry calls start_acquisition exactly once", () => {
  let container: HTMLDivElement;
  let root: Root;
  let invokeMock: ReturnType<typeof vi.fn<Bridge["invoke"]>>;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    invokeMock = vi.fn(async (command: string) => {
      if (command === "start_acquisition" || command === "startAcquisition") {
        return "CivicCast started downloading its components.";
      }
      if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
        return "null";
      }
      throw new Error(`unexpected command in test: ${command}`);
    });
    installTauriBridge(invokeMock);
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    removeTauriBridge();
    vi.useRealTimers();
  });

  it("calls start_acquisition once on mount and not again across several poll ticks", async () => {
    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds: ["app_runtime", "server_binaries"],
          onAllComplete: () => {}
        })
      );
      // Flush the effect's synchronous `void startAcquisition()` call and
      // its microtask.
      await Promise.resolve();
    });

    expect(startAcquisitionCallCount(invokeMock)).toBe(1);

    // Advance well past several poll intervals (500ms while any component
    // is "downloading"/"verifying", 2s otherwise -- see pollIntervalMs).
    for (let tick = 0; tick < 6; tick += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500);
      });
    }

    expect(startAcquisitionCallCount(invokeMock)).toBe(1);
    // Sanity: the poll loop itself really did run more than once (otherwise
    // this test would trivially pass by never ticking at all).
    const pollCalls = invokeMock.mock.calls.filter(
      ([command]) => command === "read_local_installer_state" || command === "readLocalInstallerState"
    ).length;
    expect(pollCalls).toBeGreaterThan(1);
  });

  it("calls start_acquisition again on a fresh mount (a new screen instance), still once per mount", async () => {
    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds: ["captions_medium"],
          onAllComplete: () => {}
        })
      );
      await Promise.resolve();
    });
    expect(startAcquisitionCallCount(invokeMock)).toBe(1);

    act(() => {
      root.unmount();
    });

    const secondRoot = createRoot(container);
    await act(async () => {
      secondRoot.render(
        createElement(DownloadingScreen, {
          selectedIds: ["captions_medium"],
          onAllComplete: () => {}
        })
      );
      await Promise.resolve();
    });

    // The Rust command is independently idempotent (a second call while
    // already running is a documented no-op) -- this only proves the
    // FRONTEND's call-once-per-mount discipline, not backend behavior.
    expect(startAcquisitionCallCount(invokeMock)).toBe(2);

    act(() => {
      secondRoot.unmount();
    });
  });

  it.each([false, true])("passes the actual download plan, with optional components selected=%s", async (optional) => {
    const selectedIds = ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"] as const;
    const plan = optional ? [...selectedIds, "captions_large", "cuda_runtime"] as const : selectedIds;
    await act(async () => {
      root.render(createElement(DownloadingScreen, { selectedIds: plan, onAllComplete: () => {} }));
      await Promise.resolve();
    });
    const calls = invokeMock.mock.calls.filter(([command]) => command === "start_acquisition");
    expect(calls).toHaveLength(1);
    expect(calls[0][1]).toEqual({ selectedIds: [...plan] });
  });
});

// A rejected `start_acquisition` is the EXACT runtime shape of the Tauri ACL
// blocker (`installer-actions.toml` did not allow the command, so every
// invoke was denied). Before this fix `AcquisitionFlow` called
// `void startAcquisition()` and threw the failure away, so the screen sat on
// "Waiting" rows with nothing on screen ever saying why.
describe("DownloadingScreen surfaces a failed start_acquisition", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    removeTauriBridge();
    vi.useRealTimers();
  });

  function alertText(): string {
    return Array.from(container.querySelectorAll('[role="alert"]'))
      .map((node) => node.textContent ?? "")
      .join(" ");
  }

  it("renders a role=alert region naming the failure when the native command is rejected", async () => {
    installTauriBridge(
      vi.fn(async (command: string) => {
        if (command === "start_acquisition" || command === "startAcquisition") {
          throw new Error("installer.start_acquisition not allowed. Permissions associated");
        }
        if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
          return "null";
        }
        throw new Error(`unexpected command in test: ${command}`);
      })
    );

    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds: ["app_runtime"],
          onAllComplete: () => {}
        })
      );
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(alertText()).not.toBe("");
    expect(alertText().toLowerCase()).toContain("could not start");
  });

  it("renders no alert region while the native command succeeds", async () => {
    installTauriBridge(
      vi.fn(async (command: string) => {
        if (command === "start_acquisition" || command === "startAcquisition") {
          return "CivicCast started downloading its components.";
        }
        if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
          return "null";
        }
        throw new Error(`unexpected command in test: ${command}`);
      })
    );

    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds: ["app_runtime"],
          onAllComplete: () => {}
        })
      );
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(alertText()).toBe("");
  });

  it("does not complete a refused plan using old completed progress", async () => {
    const onAllComplete = vi.fn();
    const selectedIds = ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"] as const;
    installTauriBridge(vi.fn(async (command: string) => {
      if (command === "start_acquisition" || command === "startAcquisition") {
        throw new Error("A different download plan is already active.");
      }
      return JSON.stringify({
        schema_version: 1, current_lane_id: "runtime", status: "running", message: "",
        reboot_required: false, updated_at_unix: 1,
        acquisition: { components: selectedIds.map((id) => ({
          id, state: "found_locally", bytes_done: 1, bytes_total: 1, elapsed_seconds: 0
        })) }
      });
    }));
    await act(async () => {
      root.render(createElement(DownloadingScreen, { selectedIds, onAllComplete }));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(alertText()).toContain("could not start");
    expect(alertText()).not.toContain("Nothing is being downloaded");
    expect(alertText()).toContain("earlier plan may still be running");
    expect(alertText()).toContain("Close and reopen");
    expect(onAllComplete).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("civiccast.acquisitionFlowComplete")).toBeNull();
  });
});
it("never completes a newly admitted plan from a read begun before admission", async () => {
  vi.useFakeTimers();
  window.localStorage.clear();
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const selectedIds = ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"] as const;
  let admit: (value: string) => void = () => {};
  let progressReads = 0;
  let admitted = false;
  const admission = new Promise<string>(resolve => { admit = resolve });
  const invoke = vi.fn(async (command: string) => {
    if (command === "start_acquisition" || command === "startAcquisition") return admission;
    progressReads++;
    return JSON.stringify({schema_version:1, status:"running", current_lane_id:"runtime", message:"", reboot_required:false, updated_at_unix:1,
      acquisition:{components:selectedIds.map(id => ({id, state:admitted ? "pending" : "found_locally", bytes_done:1, bytes_total:1, elapsed_seconds:0}))}});
  });
  (window as unknown as {__TAURI__: {invoke: typeof invoke}}).__TAURI__ = {invoke};
  const complete = vi.fn();
  try {
    await act(async () => { root.render(createElement(DownloadingScreen, {selectedIds,onAllComplete:complete})); await Promise.resolve() });
    expect(complete).not.toHaveBeenCalled();
    await act(async () => { admitted = true; admit("Started"); await Promise.resolve() });
    expect(complete).not.toHaveBeenCalled();
    expect(window.localStorage.getItem("civiccast.acquisitionFlowComplete")).toBeNull();
  } finally {
    act(() => root.unmount());
    container.remove();
    delete (window as unknown as {__TAURI__?: unknown}).__TAURI__;
    vi.useRealTimers();
  }
});

it("never completes fresh native admission from browser fallback progress when native read fails", async () => {
  vi.useFakeTimers();
  const selectedIds = ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"] as const;
  window.localStorage.setItem("civiccast.installerProgress", JSON.stringify({schema_version:1,status:"running",current_lane_id:"runtime",message:"",reboot_required:false,updated_at_unix:1,
    acquisition:{components:selectedIds.map(id => ({id,state:"complete",bytes_done:1,bytes_total:1,elapsed_seconds:0}))}}));
  window.localStorage.removeItem("civiccast.acquisitionFlowComplete");
  const invoke = vi.fn(async (command: string) => {
    if(command === "start_acquisition" || command === "startAcquisition") return "Started";
    throw new Error("Cannot read progress");
  });
  (window as unknown as {__TAURI__: {invoke: typeof invoke}}).__TAURI__ = {invoke};
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const complete = vi.fn();
  try {
    await act(async () => {root.render(createElement(DownloadingScreen,{selectedIds,onAllComplete:complete}));await Promise.resolve()});
    expect(complete).not.toHaveBeenCalled();
  } finally {
    act(() => root.unmount());container.remove();
    delete (window as unknown as {__TAURI__?: unknown}).__TAURI__;
    window.localStorage.clear();vi.useRealTimers();
  }
});
