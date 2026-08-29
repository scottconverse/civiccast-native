// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// G011.2 regression tests: no download ETA anywhere may rest on a rate
// CivicCast did not measure on THIS connection.
//
// The defect. AcquisitionFlow's plan-screen effect landed a hardcoded
// `28 * 1024 * 1024` bytes/second 1400ms after the screen mounted -- described
// in its own comment as a "demo/dev fallback ... a plausible rate". Nothing
// about a real station made it plausible, and nothing on screen distinguished
// it from a measurement: the plan footer printed a duration and the words "at
// this connection's measured speed" underneath it. A city clerk on a 6 Mbit
// DSL line was told a 9.4 GB download would take about six minutes.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AcquisitionFlow, DownloadingScreen } from "./AcquisitionFlow";
import type { AcquisitionComponentProgress, HardwareInventory, InstallerProgress } from "./types";

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

function installTauriBridge(invoke: Bridge["invoke"]): void {
  (window as unknown as { __TAURI__: Bridge }).__TAURI__ = { invoke };
}

function removeTauriBridge(): void {
  delete (window as unknown as { __TAURI__?: Bridge }).__TAURI__;
}

const INVENTORY: HardwareInventory = {
  cpu_model: "AMD Ryzen 9 7950X 16-Core Processor",
  physical_cores: 16,
  logical_cores: 32,
  ram_gb: 63.2,
  gpus: [],
  free_disk_bytes: 900_000_000_000,
  install_target: "C:\\Program Files",
  recommended_caption_tier: "floor",
  hardware_capable_caption_tier: "floor"
};

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

/** Any rendered duration -- "1 min 27 sec", "6 min", "2 hr 10 min", "45 seconds". */
const DURATION = /\d+\s*(seconds?|sec|min|hr)\b/;

describe("the download plan claims no ETA until something has actually been measured", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
    vi.useFakeTimers();
    installTauriBridge(
      vi.fn(async (command: string) => {
        if (command === "native_hardware_inventory" || command === "nativeHardwareInventory") {
          return INVENTORY;
        }
        if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
          return "null";
        }
        // measure_link_speed_bytes_per_second is deliberately NOT answered:
        // no such command is registered in main.rs's generate_handler! list.
        throw new Error(`unexpected command in test: ${command}`);
      })
    );
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    removeTauriBridge();
    vi.useRealTimers();
  });

  async function reachThePlanScreen(): Promise<void> {
    await act(async () => {
      root.render(createElement(AcquisitionFlow, { onComplete: () => {} }));
      await Promise.resolve();
    });
    // Past the 650ms minimum-display delay on the checking screen.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    const continueButton = Array.from(container.querySelectorAll("button")).find(
      (node) => node.textContent === "Continue"
    );
    expect(continueButton, "the checking screen should offer Continue").toBeTruthy();
    await act(async () => {
      continueButton!.click();
      await Promise.resolve();
    });
  }

  it("shows sizes but no time claim, even long after the old 1400ms fallback would have fired", async () => {
    await reachThePlanScreen();
    expect(container.textContent).toContain("What CivicCast Needs");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(container.textContent).not.toMatch(DURATION);
    // And it must not assert a measurement it does not have.
    expect(container.textContent?.toLowerCase()).not.toContain("measured speed");
    // It should say plainly that the estimate comes later.
    expect(container.textContent?.toLowerCase()).toContain("once the download starts");
  });
});

describe("the downloading screen's overall time left is measured, not assumed", () => {
  let container: HTMLDivElement;
  let root: Root;
  let bytesDone: number;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
    bytesDone = 0;
    vi.useFakeTimers();
    installTauriBridge(
      vi.fn(async (command: string) => {
        if (command === "start_acquisition" || command === "startAcquisition") {
          return "CivicCast started downloading its components.";
        }
        if (command === "read_local_installer_state" || command === "readLocalInstallerState") {
          return progressJson([
            {
              id: "app_runtime",
              state: "downloading",
              bytes_done: bytesDone,
              bytes_total: 500_000_000,
              elapsed_seconds: 1
            }
          ]);
        }
        throw new Error(`unexpected command in test: ${command}`);
      })
    );
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    removeTauriBridge();
    vi.useRealTimers();
  });

  async function mount(): Promise<void> {
    await act(async () => {
      root.render(
        createElement(DownloadingScreen, { selectedIds: ["app_runtime"], onAllComplete: () => {} })
      );
      await Promise.resolve();
    });
  }

  function overallText(): string {
    return document.querySelector('[aria-label="Overall download progress"]')?.textContent ?? "";
  }

  it("makes no time claim before any bytes have moved", async () => {
    await mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(overallText()).not.toMatch(DURATION);
    expect(overallText().toLowerCase()).toContain("estimating");
  });

  it("shows a time left once real bytes have moved across two polls", async () => {
    await mount();
    // Two polls with a genuine byte delta between them: the rolling window has
    // something real to average.
    for (let step = 1; step <= 6; step += 1) {
      bytesDone = step * 10_000_000;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(600);
      });
    }
    expect(overallText()).toMatch(DURATION);
    expect(overallText().toLowerCase()).toContain("left");
  });
});
