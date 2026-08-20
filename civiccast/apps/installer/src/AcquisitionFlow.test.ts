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
});
