// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// F-06 (rewalk-dd7f835f): two adjacent first-run screens made opposite claims
// about the same engine. Screen 1: "This station's graphics card can run the
// highest-quality caption engine in real time. We've selected it for you."
// Screen 2, one click later, on the row for that same engine: "too slow for
// live captioning on this hardware."
//
// The reason they could disagree is that they did not share a fact. The
// sentence was computed from the probed caption tiers; the row's explanation
// was a hardcoded string in components-catalog.ts that knows nothing about
// the machine, so no amount of care on either side could keep them in
// agreement. These tests pin the single decision both surfaces read, and pin
// the property that actually matters to an operator: the two never contradict
// each other, on any hardware, whether or not the large engine is obtainable.
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

/** "This machine can run the quality engine while the meeting is happening." */
function claimsItRunsLiveHere(text: string): boolean {
  return /(can|could) run (it|the (higher|highest)-quality caption engine)[^.]*\b(live|in real time)\b/i.test(text);
}

/** "This machine cannot keep up with it during a meeting." */
function claimsItIsTooSlowForLive(text: string): boolean {
  return /too slow for live/i.test(text);
}

describe("F-06 as the operator saw it: two adjacent screens, rendered", () => {
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

  it("does not say the card runs the quality engine in real time and then that it is too slow for live", () => {
    // The literal walkthrough sequence: a large-v3-capable station, Continue,
    // and the row for the very engine just promised.
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
    expect(claimsItRunsLiveHere(bannerText) && claimsItIsTooSlowForLive(largeRow)).toBe(false);
  });
});

describe("F-06: the machine-check sentence and the large-engine row cannot contradict each other", () => {
  it("does not both promise real-time quality captions and call the same engine too slow for live", () => {
    // The exact walkthrough shape: a large-v3-capable station, with the
    // engine obtainable so the congratulating sentence is the one shown.
    const hardware = station(tiers("large-v3", "large-v3"));
    const banner = recommendationSentence(hardware, CATALOG_WITH_LARGE);
    const row = largeCaptionEngineExplanation(captionEngineDecision(hardware, CATALOG_WITH_LARGE));

    expect(claimsItRunsLiveHere(banner)).toBe(true);
    expect(claimsItIsTooSlowForLive(row)).toBe(false);
    expect(claimsItIsTooSlowForLive(`${banner} ${row}`)).toBe(false);
  });

  it("says the engine is too slow here only when this station really cannot run it live", () => {
    const slowStation = station(tiers("floor", "floor"));
    const row = largeCaptionEngineExplanation(captionEngineDecision(slowStation, CATALOG_WITH_LARGE));
    expect(claimsItIsTooSlowForLive(row)).toBe(true);
    expect(claimsItRunsLiveHere(recommendationSentence(slowStation, CATALOG_WITH_LARGE))).toBe(false);
  });

  it("derives the row's explanation from the hardware fact, not from a fixed string", () => {
    // The structural half of the fix. If the row copy is static, these two
    // are byte-identical -- which is precisely how a screen that knew the
    // station could run the engine live sat next to a row asserting it could
    // not. Asserted against the REAL catalog, so it holds in the shipped
    // release as well as in the obtainable-large future.
    const capable = largeCaptionEngineExplanation(captionEngineDecision(station(tiers("large-v3", "floor"))));
    const notCapable = largeCaptionEngineExplanation(captionEngineDecision(station(tiers("floor", "floor"))));
    expect(capable).not.toBe(notCapable);
  });

  it("claims nothing about live captioning on this station when the graphics probe could not run", () => {
    // G011.1's rule, applied to the second surface too: an unread probe must
    // not become a claim about the machine. `hardware_capable_caption_tier`
    // falls back to "floor" when DXGI could not be reached, which would
    // otherwise print "too slow for live captioning on this station" about a
    // card nobody looked at.
    const unknown = station({ gpus: null, ...tiers("floor", "floor") });
    const decision = captionEngineDecision(unknown, CATALOG_WITH_LARGE);
    expect(decision.largeRunsLiveHere).toBeNull();
    const row = largeCaptionEngineExplanation(decision);
    expect(claimsItIsTooSlowForLive(row)).toBe(false);
    expect(claimsItRunsLiveHere(row)).toBe(false);
  });

  it("never says the quality engine was selected unless it actually was", () => {
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
