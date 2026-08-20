// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// F-04 (rewalk-dd7f835f, CRITICAL): the wizard dead-ended. "Caption engine —
// Large" sat byte-identical at "0 KB of 3.1 GB / Not started yet" for twelve
// minutes while a later component finished; the overall bar froze at "8.5 GB
// of 11.6 GB — In progress"; and ten Tab presses found NO focusable control
// anywhere on the screen. No Retry, no Cancel, no Skip, no Back. The
// operator's only options were to wait forever or kill the window.
//
// G011.3 wired Cancel and G011 added the stall watchdog after that build, so
// the headline case is expected to be closed. This suite exists to PROVE that
// rather than assume it, and to sweep for what a "Cancel while something is
// in flight" control does not cover.
//
// The invariant it pins is the one the finding is actually about: while the
// download has not finished, this screen ALWAYS offers at least one enabled,
// focusable control, and that control is outside the scroll region (F-08) so
// it is on screen without scrolling.
//
// jsdom cannot press Tab, so "focusable" is asserted as: an enabled <button>
// in the document, not removed from the tab order, that takes focus when
// focused. That is what Tab traverses.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadingScreen } from "./AcquisitionFlow";
import type { AcquisitionComponentProgress, InstallerProgress } from "./types";
import type { ComponentId } from "./components-catalog";

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

const GB = 1024 * 1024 * 1024;

function progressJson(components: AcquisitionComponentProgress[]): string {
  const progress: InstallerProgress = {
    schema_version: 1,
    current_lane_id: "runtime",
    status: "running",
    message: "",
    reboot_required: false,
    updated_at_unix: 1,
    acquisition: { components }
  };
  return JSON.stringify(progress);
}

function done(id: ComponentId, bytes: number): AcquisitionComponentProgress {
  return { id, state: "complete", bytes_done: bytes, bytes_total: bytes, elapsed_seconds: 30 };
}

describe("F-04: a download screen that has not finished always offers a way out", () => {
  let container: HTMLDivElement;
  let root: Root;
  let payload: string;
  let completed: number;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
    completed = 0;
    payload = progressJson([]);
    (window as unknown as { __TAURI__: Bridge }).__TAURI__ = {
      invoke: async (command: string) => {
        if (command === "start_acquisition" || command === "startAcquisition") {
          return "started";
        }
        if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
          return payload;
        }
        return "ok";
      }
    };
    vi.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    delete (window as unknown as { __TAURI__?: Bridge }).__TAURI__;
    vi.useRealTimers();
  });

  async function show(
    selectedIds: readonly ComponentId[],
    components: AcquisitionComponentProgress[],
    holdSeconds = 1
  ): Promise<void> {
    payload = progressJson(components);
    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds,
          onAllComplete: () => {
            completed += 1;
          }
        })
      );
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(holdSeconds * 1000);
    });
  }

  /** Every control Tab could land on: an enabled button still in the tab order. */
  function focusableControls(): HTMLButtonElement[] {
    return Array.from(container.querySelectorAll("button")).filter(
      (button) => !button.disabled && Number(button.getAttribute("tabindex") ?? "0") >= 0
    );
  }

  function assertReachableEscape(): HTMLButtonElement {
    const controls = focusableControls();
    expect(controls.length, `no focusable control on screen: ${container.textContent}`).toBeGreaterThan(0);
    const control = controls[0];
    control.focus();
    expect(document.activeElement).toBe(control);
    // F-08: on screen without scrolling.
    const scrollRegion = container.querySelector("[data-scroll-region]");
    expect(scrollRegion).not.toBeNull();
    expect(controls.some((candidate) => !scrollRegion?.contains(candidate))).toBe(true);
    return control;
  }

  it("offers an escape on the exact screen the walkthrough dead-ended on", async () => {
    // Verbatim from VERDICT-rewalk-dd7f835f §6: the large caption engine
    // permanently "Waiting / 0 KB of 3.1 GB / Not started yet" while a LATER
    // component has already finished.
    await show(
      ["app_runtime", "captions_medium", "captions_large", "local_ai_model"],
      [
        done("app_runtime", 482 * 1024 * 1024),
        done("captions_medium", Math.round(1.4 * GB)),
        {
          id: "captions_large",
          state: "pending",
          bytes_done: 0,
          bytes_total: Math.round(3.1 * GB),
          elapsed_seconds: 0
        },
        done("local_ai_model", Math.round(7.6 * GB))
      ]
    );

    expect(container.textContent).toContain("Not started yet");
    expect(completed).toBe(0);
    expect(assertReachableEscape().textContent).toContain("Stop downloading");
  });

  it("offers an escape on a row that has stalled mid-transfer", async () => {
    await show(
      ["app_runtime", "local_ai_model"],
      [
        {
          id: "app_runtime",
          state: "downloading",
          bytes_done: 12_345_678,
          bytes_total: 482 * 1024 * 1024,
          elapsed_seconds: 40
        },
        done("local_ai_model", Math.round(7.6 * GB))
      ],
      20
    );

    expect(container.textContent).toContain("Stalled — retrying");
    assertReachableEscape();
  });

  it("offers an escape when a component stopped and the engine gave no reason", async () => {
    // The gap a "cancel while something is in flight" control cannot cover:
    // `state: "error"` with no `error` payload. Nothing is in flight, so no
    // Stop control; the row's own Retry was gated on `progress.error` being
    // present; and the fall-through row rendered a progress bar reading
    // "Downloading" for a component that had stopped. That is F-04's shape
    // exactly -- a frozen row with no control anywhere -- and the flow never
    // completes, because allDone is false forever.
    await show(
      ["app_runtime", "local_ai_model"],
      [
        {
          id: "app_runtime",
          state: "error",
          bytes_done: 3_000_000,
          bytes_total: 482 * 1024 * 1024,
          elapsed_seconds: 12
        },
        done("local_ai_model", Math.round(7.6 * GB))
      ]
    );

    expect(completed).toBe(0);
    // It must not claim to be downloading something that stopped.
    expect(container.querySelector(".download-row")?.textContent).not.toContain("Downloading");
    assertReachableEscape();
  });

  it("offers an escape when the engine reports a state this build does not know", async () => {
    // Version skew: the Rust side gains a state before the frontend does.
    // Falling through to the "still going" row shape turns that into a
    // permanent dead end, which is the failure mode this suite exists for.
    await show(
      ["app_runtime", "local_ai_model"],
      [
        {
          id: "app_runtime",
          state: "quarantined" as never,
          bytes_done: 3_000_000,
          bytes_total: 482 * 1024 * 1024,
          elapsed_seconds: 12
        },
        done("local_ai_model", Math.round(7.6 * GB))
      ]
    );

    expect(completed).toBe(0);
    assertReachableEscape();
  });

  it("offers an escape when an error kind this build does not know arrives", async () => {
    await show(
      ["app_runtime"],
      [
        {
          id: "app_runtime",
          state: "error",
          bytes_done: 0,
          bytes_total: 482 * 1024 * 1024,
          elapsed_seconds: 12,
          error: { kind: "solar_flare" as never, detail: "unmapped" }
        }
      ]
    );

    expect(completed).toBe(0);
    assertReachableEscape();
  });

  it("stops offering one once the run has genuinely finished", async () => {
    await show(["app_runtime"], [done("app_runtime", 482 * 1024 * 1024)]);
    expect(completed).toBeGreaterThan(0);
    expect(focusableControls()).toHaveLength(0);
  });
});
