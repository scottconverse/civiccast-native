// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// F-15 (rewalk-dd7f835f): the downloading screen's denominator SHRANK while
// the download ran -- "12.8 GB", then "12.1 GB", then "11.6 GB". A total that
// moves under an operator destroys the one number they are using to decide
// whether to keep waiting, and it moves in the direction that looks most like
// the product quietly dropping things it promised.
//
// The cause is arithmetic, not mischief: the screen summed `bytes_total`
// across the rows every render, seeding each row with the CATALOG PLACEHOLDER
// size and overwriting it with the engine's measured size as each component
// was picked up. Every replacement moved the headline.
//
// The rule pinned here: the denominator the run was announced with holds for
// the whole run, and changes at most ONCE -- when every file's real size is
// known -- and when it changes it SAYS SO, with both figures. No silent drift.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadingScreen } from "./AcquisitionFlow";
import { downloadTotalDenominator, formatBytes } from "./acquisition-progress";
import { catalogComponent, type ComponentId } from "./components-catalog";
import type { AcquisitionComponentProgress, InstallerProgress } from "./types";

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

const SELECTED: ComponentId[] = ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"];

const ANNOUNCED = SELECTED.reduce((sum, id) => sum + catalogComponent(id).placeholderSizeBytes, 0);

/** The measured sizes the engine actually reports -- all smaller than the
 * catalog placeholders, which is the direction the walkthrough observed. */
const MEASURED: Record<string, number> = {
  app_runtime: 470 * 1024 * 1024,
  server_binaries: 90 * 1024 * 1024,
  captions_medium: Math.round(1.4 * 1024 * 1024 * 1024),
  local_ai_model: Math.round(7.2 * 1024 * 1024 * 1024)
};

const MEASURED_TOTAL = SELECTED.reduce((sum, id) => sum + MEASURED[id], 0);

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

/** The engine has picked up `reported` and knows their real sizes; the rest
 * have not been reported at all yet. */
function reportedSoFar(reported: readonly ComponentId[]): AcquisitionComponentProgress[] {
  return reported.map((id) => ({
    id,
    state: "downloading" as const,
    bytes_done: Math.round(MEASURED[id] / 2),
    bytes_total: MEASURED[id],
    elapsed_seconds: 5
  }));
}

function denominator(container: HTMLElement): string {
  const text = container.querySelector(".overall-progress")?.textContent ?? "";
  const match = text.match(/of ([\d.]+ [KMG]B)/);
  if (!match) {
    throw new Error(`no "x of y" figure in the overall progress block: ${JSON.stringify(text)}`);
  }
  return match[1];
}

describe("F-15: the download total does not drift while the download runs", () => {
  let container: HTMLDivElement;
  let root: Root;
  let payload: string;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
    payload = progressJson([]);
    (window as unknown as { __TAURI__: Bridge }).__TAURI__ = {
      invoke: async (command: string) => {
        if (command === "start_acquisition" || command === "startAcquisition") {
          return "started";
        }
        if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
          return payload;
        }
        return "null";
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

  async function poll(components: AcquisitionComponentProgress[]): Promise<void> {
    payload = progressJson(components);
    // Past the 2s idle poll interval as well as the 500ms active one -- the
    // rows are all `pending` until the first payload lands, so the first
    // scheduled tick is the slow one.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
  }

  it("holds the announced total while the engine is still learning the real sizes", async () => {
    await act(async () => {
      root.render(createElement(DownloadingScreen, { selectedIds: SELECTED, onAllComplete: () => {} }));
      await Promise.resolve();
    });

    const announced = formatBytes(ANNOUNCED);
    expect(denominator(container)).toBe(announced);

    // The walkthrough's exact shape: components resolve one at a time, each
    // one replacing a placeholder with a smaller measured size.
    await poll(reportedSoFar(["app_runtime"]));
    expect(denominator(container)).toBe(announced);

    await poll(reportedSoFar(["app_runtime", "server_binaries"]));
    expect(denominator(container)).toBe(announced);

    await poll(reportedSoFar(["app_runtime", "server_binaries", "captions_medium"]));
    expect(denominator(container)).toBe(announced);
  });

  it("re-baselines exactly once, visibly, and says both figures", async () => {
    await act(async () => {
      root.render(createElement(DownloadingScreen, { selectedIds: SELECTED, onAllComplete: () => {} }));
      await Promise.resolve();
    });
    await poll(reportedSoFar(["app_runtime"]));
    expect(container.textContent).not.toContain("Total updated");

    await poll(reportedSoFar(SELECTED));
    expect(denominator(container)).toBe(formatBytes(MEASURED_TOTAL));
    const note = container.textContent ?? "";
    expect(note).toContain("Total updated");
    // Both figures, so the change is explained rather than merely performed.
    expect(note).toContain(formatBytes(MEASURED_TOTAL));
    expect(note).toContain(formatBytes(ANNOUNCED));

    // And it stays put afterwards, including when a row later reports a
    // different total (a resumed file re-reporting, a retry).
    await poll([
      ...reportedSoFar(SELECTED.slice(1)),
      { id: "app_runtime", state: "downloading", bytes_done: 1, bytes_total: 1, elapsed_seconds: 9 }
    ]);
    expect(denominator(container)).toBe(formatBytes(MEASURED_TOTAL));
  });
});

describe("downloadTotalDenominator, directly", () => {
  const rows = (ids: readonly ComponentId[]): AcquisitionComponentProgress[] =>
    ids.map((id) => ({ id, state: "downloading", bytes_done: 0, bytes_total: MEASURED[id], elapsed_seconds: 0 }));

  it("does not move until every component has reported a measured size", () => {
    const partial = downloadTotalDenominator(ANNOUNCED, rows(SELECTED), new Set(["app_runtime", "server_binaries"]));
    expect(partial.totalBytes).toBe(ANNOUNCED);
    expect(partial.settled).toBe(false);
    expect(partial.rebaselineNote).toBeNull();
  });

  it("settles on the measured sum once every component has reported", () => {
    const settled = downloadTotalDenominator(ANNOUNCED, rows(SELECTED), new Set(SELECTED));
    expect(settled.totalBytes).toBe(MEASURED_TOTAL);
    expect(settled.settled).toBe(true);
    expect(settled.rebaselineNote).toContain(formatBytes(ANNOUNCED));
  });

  it("says nothing when the measured sum turns out to match what was announced", () => {
    const exact = downloadTotalDenominator(MEASURED_TOTAL, rows(SELECTED), new Set(SELECTED));
    expect(exact.totalBytes).toBe(MEASURED_TOTAL);
    expect(exact.rebaselineNote).toBeNull();
  });
});
