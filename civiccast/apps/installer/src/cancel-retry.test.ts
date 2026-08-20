// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// G011.3: the downloading screen's three recovery paths, proved rather than
// assumed.
//
// The A-min fix added a stall watchdog, a role="alert" failure region and
// retry plumbing, but nothing exercised them end to end from the screen, and
// CANCEL was not wired to anything at all: there was no cancel command, no
// cancel button, and no canceled component state -- so an operator who
// realised mid-download that they were on a metered connection had exactly
// one option, which was to kill the window and leave a `.partial` behind with
// nothing on screen having acknowledged it.
//
// Each test below drives the real `DownloadingScreen` against a scripted
// Tauri bridge and asserts on rendered DOM plus the invokes that actually
// crossed the bridge -- never on internal state.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadingScreen } from "./AcquisitionFlow";
import { NO_BYTES_MOVED_THRESHOLD_SECONDS } from "./acquisition-progress";
import type { AcquisitionComponentProgress, InstallerProgress } from "./types";

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

function installTauriBridge(invoke: Bridge["invoke"]): void {
  (window as unknown as { __TAURI__: Bridge }).__TAURI__ = { invoke };
}

function removeTauriBridge(): void {
  delete (window as unknown as { __TAURI__?: Bridge }).__TAURI__;
}

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

function matches(command: string, snake: string, camel: string): boolean {
  return command === snake || command === camel;
}

describe("cancel, retry and the stall watchdog on the downloading screen", () => {
  let container: HTMLDivElement;
  let root: Root;
  let invokeMock: ReturnType<typeof vi.fn>;
  /** What the polled installer state currently reports. Mutated by each test. */
  let reported: AcquisitionComponentProgress[];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
    vi.useFakeTimers();
    reported = [];
    invokeMock = vi.fn(async (command: string) => {
      if (matches(command, "start_acquisition", "startAcquisition")) {
        return "CivicCast started downloading its components.";
      }
      if (matches(command, "cancel_acquisition", "cancelAcquisition")) {
        // The real command marks every unfinished component canceled and
        // persists that into the polled state; mirror that here.
        reported = reported.map((component) =>
          component.state === "complete" || component.state === "found_locally"
            ? component
            : { ...component, state: "canceled", error: undefined }
        );
        return "CivicCast stopped downloading.";
      }
      if (matches(command, "retry_acquisition_component", "retryAcquisitionComponent")) {
        return "Retrying app_runtime.";
      }
      if (matches(command, "read_local_installer_state", "readLocalInstallerState")) {
        return progressJson(reported);
      }
      throw new Error(`unexpected command in test: ${command}`);
    });
    installTauriBridge(invokeMock);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    removeTauriBridge();
    vi.useRealTimers();
  });

  async function mount(selectedIds: readonly string[] = ["app_runtime"]): Promise<void> {
    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds: selectedIds as never,
          onAllComplete: () => {}
        })
      );
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
  }

  async function tick(ms: number): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  function buttons(): HTMLButtonElement[] {
    return Array.from(container.querySelectorAll("button"));
  }

  function buttonNamed(label: RegExp): HTMLButtonElement | undefined {
    return buttons().find((node) => label.test(node.textContent ?? ""));
  }

  async function click(node: HTMLButtonElement): Promise<void> {
    await act(async () => {
      node.click();
      await Promise.resolve();
    });
  }

  function alertText(): string {
    return Array.from(container.querySelectorAll('[role="alert"]'))
      .map((node) => node.textContent ?? "")
      .join(" ");
  }

  function callsTo(snake: string, camel: string): unknown[][] {
    return invokeMock.mock.calls.filter(([command]) => matches(command as string, snake, camel));
  }

  // -------------------------------------------------------------------
  // 1. Cancel during an active download
  // -------------------------------------------------------------------

  it("offers a cancel control while a download is actually running", async () => {
    reported = [
      { id: "app_runtime", state: "downloading", bytes_done: 5_000_000, bytes_total: 500_000_000, elapsed_seconds: 2 }
    ];
    await mount();
    expect(buttonNamed(/^Stop downloading$/)).toBeTruthy();
  });

  it("cancel invokes the native cancel command and leaves the row in a defined, recoverable state", async () => {
    reported = [
      { id: "app_runtime", state: "downloading", bytes_done: 5_000_000, bytes_total: 500_000_000, elapsed_seconds: 2 }
    ];
    await mount();

    await click(buttonNamed(/^Stop downloading$/)!);
    expect(callsTo("cancel_acquisition", "cancelAcquisition")).toHaveLength(1);

    // Let the next poll bring the canceled state back from the backend.
    await tick(2500);

    const rowText = container.querySelector(".download-list")?.textContent ?? "";
    // Defined: the row SAYS it was stopped. Not wedged: it does not sit on
    // "Downloading" or "Waiting" with no explanation.
    expect(rowText).toMatch(/stopped/i);
    expect(rowText).not.toMatch(/Downloading|Waiting/);
    // Recoverable: a resume affordance is present on the canceled row.
    expect(buttonNamed(/Resume download/)).toBeTruthy();
    // A cancel the operator asked for is not an error condition.
    expect(alertText()).toBe("");
  });

  it("resuming a canceled row re-invokes acquisition for that component", async () => {
    reported = [
      { id: "app_runtime", state: "downloading", bytes_done: 5_000_000, bytes_total: 500_000_000, elapsed_seconds: 2 }
    ];
    await mount();
    await click(buttonNamed(/^Stop downloading$/)!);
    await tick(2500);

    await click(buttonNamed(/Resume download/)!);

    const retries = callsTo("retry_acquisition_component", "retryAcquisitionComponent");
    expect(retries).toHaveLength(1);
    expect(retries[0][1]).toMatchObject({ componentId: "app_runtime" });
  });

  it("hides the cancel control once every component has finished", async () => {
    reported = [
      { id: "app_runtime", state: "complete", bytes_done: 500_000_000, bytes_total: 500_000_000, elapsed_seconds: 9 }
    ];
    await mount();
    expect(buttonNamed(/^Stop downloading$/)).toBeFalsy();
  });

  // -------------------------------------------------------------------
  // 2. Retry after a failed component
  // -------------------------------------------------------------------

  it("retry after a failed component actually re-invokes acquisition, with that component's id", async () => {
    reported = [
      {
        id: "app_runtime",
        state: "error",
        bytes_done: 0,
        bytes_total: 500_000_000,
        elapsed_seconds: 4,
        error: { kind: "network_failed", detail: "connection reset" }
      }
    ];
    await mount();

    const retryButton = buttonNamed(/Resume download|Retry download/);
    expect(retryButton, "a failed row must offer a retry").toBeTruthy();
    await click(retryButton!);

    const retries = callsTo("retry_acquisition_component", "retryAcquisitionComponent");
    expect(retries).toHaveLength(1);
    expect(retries[0][1]).toMatchObject({ componentId: "app_runtime" });
    // And the operator is told it happened.
    expect(container.textContent).toMatch(/Retrying/i);
  });

  it("retries only the failed component, not the one that already succeeded", async () => {
    reported = [
      { id: "app_runtime", state: "complete", bytes_done: 500_000_000, bytes_total: 500_000_000, elapsed_seconds: 9 },
      {
        id: "server_binaries",
        state: "error",
        bytes_done: 0,
        bytes_total: 98_000_000,
        elapsed_seconds: 3,
        error: { kind: "source_not_found", detail: "https://example.invalid/x.ccpack" }
      }
    ];
    await mount(["app_runtime", "server_binaries"]);

    await click(buttonNamed(/Resume download|Retry download/)!);
    const retries = callsTo("retry_acquisition_component", "retryAcquisitionComponent");
    expect(retries).toHaveLength(1);
    expect(retries[0][1]).toMatchObject({ componentId: "server_binaries" });
  });

  // -------------------------------------------------------------------
  // 3. The stall watchdog on the zero-bytes case
  // -------------------------------------------------------------------

  it("surfaces an alert when every row is still pending and not one byte has moved", async () => {
    reported = [
      { id: "app_runtime", state: "pending", bytes_done: 0, bytes_total: 500_000_000, elapsed_seconds: 0 }
    ];
    await mount();

    // Before the threshold: silence is still legitimate (the driver
    // resolves the catalog and opens the first connection).
    await tick((NO_BYTES_MOVED_THRESHOLD_SECONDS - 5) * 1000);
    expect(alertText()).toBe("");

    await tick(10_000);
    expect(alertText()).toMatch(/no files have started downloading/i);
    expect(alertText()).toMatch(/installer log/i);
  });

  it("does not raise the zero-bytes alert once bytes have actually moved", async () => {
    reported = [
      { id: "app_runtime", state: "downloading", bytes_done: 1, bytes_total: 500_000_000, elapsed_seconds: 1 }
    ];
    await mount();
    await tick((NO_BYTES_MOVED_THRESHOLD_SECONDS + 10) * 1000);
    expect(alertText()).toBe("");
  });
});
