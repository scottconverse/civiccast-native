// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// F-22 (rewalk-dd7f835f) pinned: an optional component is never selected by
// default, whatever the hardware recommends — because at that time the large
// caption engine was NOT deliverable, and its pre-tick committed a newcomer
// to a 3.1 GB download the backend could never even drive.
//
// OWNER RULING (2026-08-15, extended 2026-08-16 to `cuda_runtime`) deliberately
// narrows that rule now that `captions_large` IS deliverable (enrolled in the
// Rust production catalog with pinned per-file sources): "the user should get
// the better caption model if the hardware supports it." A large-v3-capable
// machine therefore starts with the large engine AND its GPU acceleration
// pack SELECTED — visibly: the machine-check sentence announces the caption-
// engine selection, each plan row is a checked checkbox the operator can
// untick, and each row's explanation names its own size and the escape. What
// SURVIVES of F-22, pinned below, for BOTH components:
//
//   1. An UNDELIVERABLE component is never selected, whatever the hardware
//      says (the permanently-"Waiting" row can never come back).
//   2. Floor-capable hardware never gets either optional download pre-ticked.
//   3. Each pre-selection is announced in the sentence asking for the
//      decision, with its own size and the untick escape — never silent.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { describe, expect, it } from "vitest";

import {
  captionEngineDecision,
  defaultSelectedComponentIds,
  formatBytes,
  gpuAccelerationDecision,
  gpuAccelerationExplanation,
  largeCaptionEngineExplanation
} from "./acquisition-progress";
import { catalogComponent, COMPONENT_CATALOG, type CatalogComponent } from "./components-catalog";
import type { HardwareInventory, RecommendedCaptionTier } from "./types";

const CATALOG_WITHOUT_LARGE: readonly CatalogComponent[] = COMPONENT_CATALOG.map((component) =>
  component.id === "captions_large" ? { ...component, deliverable: false } : component
);

const CATALOG_WITHOUT_CUDA: readonly CatalogComponent[] = COMPONENT_CATALOG.map((component) =>
  component.id === "cuda_runtime" ? { ...component, deliverable: false } : component
);

function station(capable: RecommendedCaptionTier, installed: RecommendedCaptionTier): HardwareInventory {
  return {
    cpu_model: "AMD Ryzen 7 7800X3D 8-Core Processor",
    physical_cores: 8,
    logical_cores: 16,
    ram_gb: 32,
    gpus: [{ name: "NVIDIA GeForce RTX 4090", dedicated_vram_mb: 24576, vendor: "NVIDIA" }],
    free_disk_bytes: 500 * 1024 * 1024 * 1024,
    install_target: "C:\\",
    recommended_caption_tier: installed,
    hardware_capable_caption_tier: capable
  };
}

describe("optional-download defaults: F-22's survivors + the 2026-08-15 owner ruling", () => {
  it("never selects an undeliverable component, on every hardware shape (F-22 survivor)", () => {
    for (const capable of ["floor", "large-v3"] as const) {
      for (const installed of ["floor", "large-v3"] as const) {
        for (const catalog of [CATALOG_WITHOUT_LARGE, CATALOG_WITHOUT_CUDA]) {
          const selected = defaultSelectedComponentIds(station(capable, installed), catalog);
          for (const component of catalog) {
            if (!component.deliverable) {
              expect(selected).not.toContain(component.id);
            }
          }
          for (const id of selected) {
            const component = catalog.find((entry) => entry.id === id);
            expect(component, `default-selected ${id} is not in the catalog`).toBeDefined();
            expect(component?.deliverable, `default-selected undeliverable component: ${id}`).toBe(true);
          }
        }
      }
    }
  });

  it("never pre-selects the large engine or its GPU pack for floor-capable hardware (F-22 survivor)", () => {
    for (const installed of ["floor", "large-v3"] as const) {
      const selected = defaultSelectedComponentIds(station("floor", installed), COMPONENT_CATALOG);
      expect(selected).not.toContain("captions_large");
      expect(selected).not.toContain("cuda_runtime");
    }
  });

  it("pre-selects the large engine on large-v3-capable hardware (2026-08-15 owner ruling)", () => {
    const selected = defaultSelectedComponentIds(station("large-v3", "large-v3"), COMPONENT_CATALOG);
    expect(selected).toContain("captions_large");
    const decision = captionEngineDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG);
    expect(decision.largeSelectedByDefault).toBe(true);
    expect(decision.largeRunsLiveHere).toBe(true);
  });

  it("pre-selects the GPU acceleration pack on large-v3-capable hardware (2026-08-16 owner ruling)", () => {
    const selected = defaultSelectedComponentIds(station("large-v3", "large-v3"), COMPONENT_CATALOG);
    expect(selected).toContain("cuda_runtime");
    const decision = gpuAccelerationDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG);
    expect(decision.selectedByDefault).toBe(true);
    expect(decision.obtainable).toBe(true);
  });

  it("never pre-selects the GPU acceleration pack when it is undeliverable, even on capable hardware", () => {
    const selected = defaultSelectedComponentIds(station("large-v3", "large-v3"), CATALOG_WITHOUT_CUDA);
    expect(selected).not.toContain("cuda_runtime");
    // The large engine's own selection is unaffected by cuda_runtime's
    // deliverability -- the two components are independently gated.
    expect(selected).toContain("captions_large");
  });

  it("announces the pre-selection with the size and the untick escape — never silent", () => {
    const explanation = largeCaptionEngineExplanation(
      captionEngineDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG),
      COMPONENT_CATALOG
    );
    // The size, in the sentence that asks for the decision -- not only in the
    // column at the far right of the row.
    expect(explanation).toContain(formatBytes(catalogComponent("captions_large").placeholderSizeBytes));
    // Selected, said plainly, with the way out.
    expect(explanation).toMatch(/selected/i);
    expect(explanation).toMatch(/untick/i);
    expect(explanation).toMatch(/add (it|this)[^.]*later/i);
  });

  it("still offers an un-ticked, informed choice on capable hardware when NOT pre-selected", () => {
    // The decision seam: capable hardware, deliverable engine, but a
    // selection that did not include it (e.g. the operator unticked and the
    // screen re-derives). The explanation must present the off-by-default
    // framing with the size and the cost of skipping.
    const decision = {
      ...captionEngineDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG),
      largeSelectedByDefault: false
    };
    const explanation = largeCaptionEngineExplanation(decision, COMPONENT_CATALOG);
    expect(explanation).toContain(formatBytes(catalogComponent("captions_large").placeholderSizeBytes));
    expect(explanation).toMatch(/off (by default|unless)/i);
    expect(explanation).toMatch(/skip/i);
    expect(explanation).toMatch(/add (it|this)[^.]*later/i);
  });

  it("keeps saying nothing about size or skipping when the component cannot be downloaded at all", () => {
    // No decision to make, so no consequence to weigh -- offering one would
    // be noise. Preserved with a catalog override now that the shipped
    // catalog delivers the component for real.
    const explanation = largeCaptionEngineExplanation(
      captionEngineDecision(station("large-v3", "floor"), CATALOG_WITHOUT_LARGE),
      CATALOG_WITHOUT_LARGE
    );
    expect(explanation).toContain("Not available to download in this release");
    expect(explanation).not.toMatch(/skip/i);
  });

  // --- cuda_runtime (GPU caption acceleration): the second pre-selected
  // download the 2026-08-16 owner ruling adds, held to the SAME three
  // surviving F-22 invariants as captions_large above.

  it("announces the GPU pack's pre-selection with its own size and the untick escape — never silent", () => {
    const explanation = gpuAccelerationExplanation(
      gpuAccelerationDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG),
      COMPONENT_CATALOG
    );
    expect(explanation).toContain(formatBytes(catalogComponent("cuda_runtime").placeholderSizeBytes));
    expect(explanation).toMatch(/selected/i);
    expect(explanation).toMatch(/untick/i);
    expect(explanation).toMatch(/add (it|this)[^.]*later/i);
  });

  it("still offers an un-ticked, informed choice for the GPU pack when NOT pre-selected", () => {
    const decision = {
      ...gpuAccelerationDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG),
      selectedByDefault: false
    };
    const explanation = gpuAccelerationExplanation(decision, COMPONENT_CATALOG);
    expect(explanation).toContain(formatBytes(catalogComponent("cuda_runtime").placeholderSizeBytes));
    expect(explanation).toMatch(/off (by default|unless)/i);
    expect(explanation).toMatch(/skip/i);
    expect(explanation).toMatch(/add (it|this)[^.]*later/i);
  });

  it("keeps saying nothing about size or skipping for the GPU pack when it cannot be downloaded at all", () => {
    const explanation = gpuAccelerationExplanation(
      gpuAccelerationDecision(station("large-v3", "large-v3"), CATALOG_WITHOUT_CUDA),
      CATALOG_WITHOUT_CUDA
    );
    expect(explanation).toContain("Not available to download in this release");
    expect(explanation).not.toMatch(/skip/i);
  });

  it("keeps the two pre-selected downloads' explanations independently truthful about total size", () => {
    // Neither explanation borrows or restates the other's size -- each row
    // states only its own, so the two together are still an honest total
    // (the sum of the two individually-stated figures), never a copy-pasted
    // shared number that could drift from either component's real size.
    const largeExplanation = largeCaptionEngineExplanation(
      captionEngineDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG),
      COMPONENT_CATALOG
    );
    const gpuExplanation = gpuAccelerationExplanation(
      gpuAccelerationDecision(station("large-v3", "large-v3"), COMPONENT_CATALOG),
      COMPONENT_CATALOG
    );
    expect(largeExplanation).toContain(formatBytes(catalogComponent("captions_large").placeholderSizeBytes));
    expect(gpuExplanation).toContain(formatBytes(catalogComponent("cuda_runtime").placeholderSizeBytes));
    expect(largeExplanation).not.toContain(formatBytes(catalogComponent("cuda_runtime").placeholderSizeBytes));
    expect(gpuExplanation).not.toContain(formatBytes(catalogComponent("captions_large").placeholderSizeBytes));
  });
});
