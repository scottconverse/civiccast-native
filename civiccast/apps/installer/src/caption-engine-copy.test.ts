// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// Keep first-run installer guidance aligned with the shipped native live
// caption path: Whistle is the CPU primary and Whisper is the fallback.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DownloadPlanScreen, MachineCheckScreen } from "./AcquisitionFlow";
import {
  captionEngineDecision,
  defaultSelectedComponentIds,
  largeCaptionEngineExplanation,
  recommendationSentence
} from "./acquisition-progress";
import { COMPONENT_CATALOG, type CatalogComponent } from "./components-catalog";
import type { HardwareInventory, RecommendedCaptionTier } from "./types";

/** The real catalog, with the large engine flipped to obtainable -- the state
 * this release is one published pack away from, and the exact state in which
 * F-06's contradicting pair becomes reachable again. */
const CATALOG_WITH_LARGE: readonly CatalogComponent[] = COMPONENT_CATALOG.map((component) =>
  component.id === "captions_large" ? { ...component, deliverable: true } : component
);

function station(overrides: Partial<HardwareInventory> = {}): HardwareInventory {
  return {
    cpu_model: "AMD Ryzen 7 7800X3D 8-Core Processor",
    physical_cores: 8,
    logical_cores: 16,
    ram_gb: 32,
    gpus: [{ name: "NVIDIA GeForce RTX 4090", dedicated_vram_mb: 24576, vendor: "NVIDIA" }],
    free_disk_bytes: 500 * 1024 * 1024 * 1024,
    install_target: "C:\\",
    recommended_caption_tier: "floor",
    hardware_capable_caption_tier: "floor",
    ...overrides
  } as HardwareInventory;
}

function tiers(capable: RecommendedCaptionTier, installed: RecommendedCaptionTier) {
  return { hardware_capable_caption_tier: capable, recommended_caption_tier: installed };
}

describe("installer caption guidance as the operator sees it", () => {
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

  function render(element: ReturnType<typeof createElement>): string {
    act(() => {
      root.render(element);
    });
    return container.textContent ?? "";
  }

  it("identifies Whistle as the live primary and Large Whisper as optional fallback", () => {
    const hardware = station(tiers("large-v3", "large-v3"));

    const banner = render(
      createElement(MachineCheckScreen, { hardware, probeError: null, onContinue: () => {} })
    ).slice(0);
    const bannerText =
      container.querySelector(".recommendation-banner")?.textContent ?? banner;

    render(
      createElement(DownloadPlanScreen, {
        freeDiskBytes: hardware.free_disk_bytes,
        hardware,
        selected: new Set<never>(),
        onToggleLarge: () => {},
        linkSpeedBps: null,
        onContinue: () => {}
      })
    );
    const largeRow =
      Array.from(container.querySelectorAll(".plan-row")).find((row) =>
        row.textContent?.includes("Caption engine — Large")
      )?.textContent ?? "";

    expect(largeRow).not.toBe("");
    expect(bannerText).toMatch(/Whistle remains the CPU primary for live captions/i);
    expect(bannerText).toMatch(/Whisper fallback/i);
    expect(largeRow).toMatch(/Whistle remains the CPU primary for live captions/i);
    expect(largeRow).toMatch(/Whisper fallback/i);
    expect(`${bannerText} ${largeRow}`).not.toMatch(/Large Whisper[^.]*primary for live captions/i);
  });

  it("describes whether this station meets the larger Whisper hardware tier", () => {
    const capable = largeCaptionEngineExplanation(captionEngineDecision(station(tiers("large-v3", "floor"))));
    const notCapable = largeCaptionEngineExplanation(captionEngineDecision(station(tiers("floor", "floor"))));
    expect(capable).not.toBe(notCapable);
    expect(capable).toMatch(/meets the hardware tier for the larger Whisper model/i);
    expect(notCapable).toMatch(/does not meet the hardware tier/i);
    expect(notCapable).toMatch(/Medium Whisper model remains available/i);
  });

  it("leaves Large-model hardware eligibility unknown when the graphics probe could not run", () => {
    const unknown = station({ gpus: null, ...tiers("floor", "floor") });
    const decision = captionEngineDecision(unknown, CATALOG_WITH_LARGE);
    expect(decision.largeMeetsHardwareTier).toBeNull();
    const row = largeCaptionEngineExplanation(decision);
    expect(row).toMatch(/could not check/i);
    expect(row).toMatch(/larger Whisper model/i);
  });

  it("never says Large was selected unless it is in the default component set", () => {
    for (const catalog of [COMPONENT_CATALOG, CATALOG_WITH_LARGE]) {
      for (const capable of ["floor", "large-v3"] as const) {
        for (const installed of ["floor", "large-v3"] as const) {
          const hardware = station(tiers(capable, installed));
          const banner = recommendationSentence(hardware, catalog);
          const selected = defaultSelectedComponentIds(hardware, catalog).includes("captions_large");
          if (/we'?ve selected it|has selected it/i.test(banner)) {
            expect(selected).toBe(true);
          }
        }
      }
    }
  });
});
