// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// G011.1 regression tests: the first-run "Checking This Computer" screen must
// never show a number CivicCast did not actually measure on THIS machine.
//
// The defect. `fetchHardwareInventory` wrapped the `native_hardware_inventory`
// invoke in `try { ... } catch { return hardwareInventoryMock; }`, and that
// mock was a complete, plausible, entirely fabricated machine: "Generic
// x86_64 CPU", 8 cores, 16 GB RAM, no GPU, and 120 GB free disk. Every path
// that could not reach the native command -- a browser preview, a rejected
// Tauri ACL (which is exactly what chain A-min had just found in the field),
// a probe that threw -- rendered those numbers under the heading "Here is what
// CivicCast found on this computer", and `diskSpaceCheck` evaluated the
// install's go/no-go against the fabricated 120 GB.
//
// No JSX here (plain `.ts`, not `.tsx`) because vitest.config.ts only globs
// `src/**/*.test.ts` -- see AcquisitionFlow.test.ts's header for the same
// note. `createElement` stands in for JSX.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchHardwareInventory } from "./api";
import { MachineCheckScreen } from "./AcquisitionFlow";
import type { HardwareGpu, HardwareInventory } from "./types";

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

function installTauriBridge(invoke: Bridge["invoke"]): void {
  (window as unknown as { __TAURI__: Bridge }).__TAURI__ = { invoke };
}

function removeTauriBridge(): void {
  delete (window as unknown as { __TAURI__?: Bridge }).__TAURI__;
}

function realProbe(overrides: Partial<HardwareInventory> = {}): HardwareInventory {
  return {
    cpu_model: "AMD Ryzen 9 7950X 16-Core Processor",
    physical_cores: 16,
    logical_cores: 32,
    ram_gb: 63.2,
    gpus: [],
    free_disk_bytes: 188_000_000_000,
    install_target: "C:\\Program Files",
    recommended_caption_tier: "floor",
    hardware_capable_caption_tier: "floor",
    ...overrides
  };
}

describe("fetchHardwareInventory never substitutes fabricated hardware facts", () => {
  afterEach(() => {
    removeTauriBridge();
  });

  it("reports the probe as unavailable when there is no native bridge at all", async () => {
    removeTauriBridge();
    const result = await fetchHardwareInventory();
    expect(result.ok).toBe(false);
  });

  it("reports the probe as unavailable when the native command is rejected", async () => {
    installTauriBridge(
      vi.fn(async () => {
        throw new Error("installer.native_hardware_inventory not allowed. Permissions associated");
      })
    );
    const result = await fetchHardwareInventory();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).not.toBe("");
    }
  });

  it("passes the real inventory straight through when the native command answers", async () => {
    const inventory = realProbe();
    installTauriBridge(vi.fn(async () => inventory));
    const result = await fetchHardwareInventory();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.inventory).toEqual(inventory);
    }
  });
});

describe("MachineCheckScreen renders only measured values", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  function render(props: Parameters<typeof MachineCheckScreen>[0]): void {
    act(() => {
      root.render(createElement(MachineCheckScreen, props));
    });
  }

  function text(): string {
    return container.textContent ?? "";
  }

  function alertText(): string {
    return Array.from(container.querySelectorAll('[role="alert"]'))
      .map((node) => node.textContent ?? "")
      .join(" ");
  }

  it("shows the real probed numbers when every value was obtained", () => {
    render({ hardware: realProbe(), probeError: null, onContinue: () => {} });
    expect(text()).toContain("AMD Ryzen 9 7950X 16-Core Processor");
    expect(text()).toContain("63.2 GB");
    expect(text()).toContain("175.1 GB");
  });

  it("says a value is unavailable rather than printing a stand-in number", () => {
    render({
      hardware: realProbe({ cpu_model: null, ram_gb: null, free_disk_bytes: null, gpus: null }),
      probeError: null,
      onContinue: () => {}
    });
    expect(text()).toContain("Unavailable");
    // The exact fabrications the old mock printed. None of them may appear
    // when nothing was actually measured.
    expect(text()).not.toContain("Generic x86_64 CPU");
    expect(text()).not.toContain("120.0 GB");
    expect(text()).not.toContain("16 GB");
    expect(text()).not.toContain("0 GB");
  });

  it("never blocks the install on a free-space reading it could not take", () => {
    render({
      hardware: realProbe({ free_disk_bytes: null }),
      probeError: null,
      onContinue: () => {}
    });
    // Honest: says the check could not be made, and still offers Continue --
    // an unknown must not masquerade as either a pass or a full disk.
    expect(alertText()).toBe("");
    expect(text()).toMatch(/could not check/i);
    const buttons = Array.from(container.querySelectorAll("button")).map((node) => node.textContent);
    expect(buttons).toContain("Continue");
  });

  it("still blocks on a REAL short-space reading", () => {
    render({
      hardware: realProbe({ free_disk_bytes: 2 * 1024 * 1024 * 1024 }),
      probeError: null,
      onContinue: () => {}
    });
    expect(alertText()).toMatch(/enough free disk space/i);
    const buttons = Array.from(container.querySelectorAll("button")).map((node) => node.textContent);
    expect(buttons).not.toContain("Continue");
  });

  it("surfaces a failed probe as an alert instead of drawing a fabricated machine", () => {
    render({
      hardware: null,
      probeError: "CivicCast could not check this computer's hardware.",
      onContinue: () => {}
    });
    expect(alertText()).toMatch(/could not check this computer/i);
    expect(text()).not.toContain("Generic x86_64 CPU");
    expect(text()).not.toContain("120.0 GB");
  });

  // F-05 (newcomer walkthrough): the "Checking This Computer" screen's
  // Graphics line showed "NVIDIA GeForce RTX 5070 Ti (16 GB)" listed THREE
  // TIMES on a machine with no such card. The delta re-walk of a later
  // candidate could not re-trigger it (the wizard screen was never reached,
  // and /api/hardware returned a single GPU that day) so F-05's status on
  // this display path was UNKNOWN until traced here.
  //
  // Root cause: hardware_inventory.rs's collect_gpus() pushes one GpuFacts
  // per DXGI adapter returned by IDXGIFactory1::EnumAdapters1, with no
  // identity check -- a virtualized/projected GPU (the GPU-PV path Windows
  // Sandbox and similar hosts use to project a host adapter into a guest,
  // which is exactly the kind of environment newcomer walkthroughs run in)
  // can enumerate the SAME physical adapter more than once. Nothing dedupes
  // that before it reaches the frontend: hardware.gpus travels straight
  // from the Rust probe to gpuSummaryLine (AcquisitionFlow.tsx), which only
  // FILTERS by dedicated_vram_mb > 0 (line 83) and then joins every
  // surviving entry with ", " (line 87) -- it never collapses duplicates.
  // A tripled adapter is therefore tripled on screen, verbatim.
  it("F-05: collapses a GPU that DXGI enumerated more than once into a single Graphics entry", () => {
    const trippedAdapter: HardwareGpu = {
      name: "NVIDIA GeForce RTX 5070 Ti",
      dedicated_vram_mb: 16 * 1024,
      vendor: "NVIDIA"
    };
    render({
      // Same shape collect_gpus() would hand the frontend if EnumAdapters1
      // returned the same physical card three times (GPU-PV / LDA-style
      // re-enumeration) -- nothing in HardwareInventory distinguishes this
      // from three real cards, so the display itself must be the one that
      // refuses to show a phantom trio.
      hardware: realProbe({ gpus: [trippedAdapter, trippedAdapter, trippedAdapter] }),
      probeError: null,
      onContinue: () => {}
    });
    const graphicsLine = text();
    // Count occurrences of the model name in the rendered text: exactly one
    // means the display deduped; more than one reproduces F-05 verbatim.
    const occurrences = graphicsLine.split("NVIDIA GeForce RTX 5070 Ti").length - 1;
    expect(occurrences).toBe(1);
    expect(graphicsLine).toContain("NVIDIA GeForce RTX 5070 Ti (16 GB)");
  });

  it("F-05: keeps distinct GPUs distinct (dedup is by identity, not by merging everything into one line)", () => {
    const nvidia: HardwareGpu = { name: "NVIDIA GeForce RTX 5070 Ti", dedicated_vram_mb: 16 * 1024, vendor: "NVIDIA" };
    const intel: HardwareGpu = { name: "Intel Arc A770", dedicated_vram_mb: 16 * 1024, vendor: "Intel" };
    render({
      hardware: realProbe({ gpus: [nvidia, nvidia, intel] }),
      probeError: null,
      onContinue: () => {}
    });
    const graphicsLine = text();
    expect(graphicsLine.split("NVIDIA GeForce RTX 5070 Ti").length - 1).toBe(1);
    expect(graphicsLine).toContain("Intel Arc A770 (16 GB)");
  });
});
