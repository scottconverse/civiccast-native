// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// F-08 (rewalk-dd7f835f, CRITICAL for a mouse-only operator): on the
// "What We'll Download" screen the newcomer walkthrough could not reach
// Continue. Wheel, PageDown, End, dragging the scrollbar and clicking the
// page all failed; only Tab reached the button, and Tab reached it only
// because moving focus scrolls the document as a side effect.
//
// The product-side defect the screenshots prove (042/043, the configured
// 1120x760 window) is that the primary action was BELOW THE FOLD at the
// installer's own default window size -- i.e. reachable only by scrolling.
// That makes every scroll-input failure mode, whatever its cause, a
// dead end for a PEG operator who has a mouse and no reason to press Tab.
//
// The structural rule pinned here removes the whole class: each first-run
// screen is a fixed-height flex column whose ONLY scrolling region is the
// content in the middle, and whose primary action lives outside that region
// and therefore cannot be scrolled away at any window size. That also gives
// the content an explicit `overflow-y: auto` scroller instead of depending on
// the WebView2 document scroller.
//
// jsdom does no layout, so nothing here asserts a pixel. It asserts the two
// things that actually make the rule true: the CSS contract (a real rule
// block in styles.css) and the DOM containment (the action control is not a
// descendant of the scroll region).
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act } from "react-dom/test-utils";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DownloadingScreen, DownloadPlanScreen, MachineCheckScreen } from "./AcquisitionFlow";
import type { HardwareInventory } from "./types";

// ---------------------------------------------------------------------------
// styles.css, read as the contract it is
// ---------------------------------------------------------------------------

// `import.meta.url` is an http: URL under the jsdom environment, so the
// stylesheet is resolved from the vitest root (apps/installer) instead, with
// the repo-root invocation covered as a fallback.
const STYLES_PATH = [
  resolve(process.cwd(), "src/styles.css"),
  resolve(process.cwd(), "civiccast/apps/installer/src/styles.css")
].find((candidate) => existsSync(candidate));

if (!STYLES_PATH) {
  throw new Error(`could not locate the installer stylesheet from cwd ${process.cwd()}`);
}

const STYLES = readFileSync(STYLES_PATH, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

function ruleBlock(selector: string): string | null {
  for (const chunk of STYLES.split("}")) {
    const brace = chunk.indexOf("{");
    if (brace < 0) {
      continue;
    }
    const selectors = chunk
      .slice(0, brace)
      .split(",")
      .map((one) => one.trim().replace(/\s+/g, " "))
      .filter(Boolean);
    if (selectors.includes(selector)) {
      return chunk.slice(brace + 1);
    }
  }
  return null;
}

function declaration(selector: string, property: string): string | null {
  const block = ruleBlock(selector);
  if (block === null) {
    return null;
  }
  const match = block.match(new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`));
  return match ? match[1].trim() : null;
}

// ---------------------------------------------------------------------------
// Rendering harness (same primitives the other suites in this folder use)
// ---------------------------------------------------------------------------

type Bridge = { invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown> };

const HARDWARE: HardwareInventory = {
  cpu_model: "AMD Ryzen 7 7800X3D 8-Core Processor",
  physical_cores: 8,
  logical_cores: 16,
  ram_gb: 8,
  gpus: [],
  free_disk_bytes: 65 * 1024 * 1024 * 1024,
  install_target: "C:\\",
  recommended_caption_tier: "floor",
  hardware_capable_caption_tier: "floor"
};

/**
 * The single scrolling region of a first-run screen. Marked in the DOM rather
 * than found by class name so the assertion is about the ROLE the element
 * plays, not about a styling hook that could be renamed underneath it.
 */
function scrollRegions(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>("[data-scroll-region]"));
}

function buttonNamed(container: HTMLElement, label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll("button")).find(
    (button) => button.textContent?.trim() === label
  );
  if (!found) {
    throw new Error(
      `no button labelled "${label}"; buttons present: ${Array.from(container.querySelectorAll("button"))
        .map((button) => JSON.stringify(button.textContent?.trim()))
        .join(", ") || "(none)"}`
    );
  }
  return found;
}

describe("F-08: a first-run screen's primary action cannot be scrolled out of reach", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.localStorage.clear();
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    delete (window as unknown as { __TAURI__?: Bridge }).__TAURI__;
    vi.useRealTimers();
  });

  it("styles.css gives the first-run shell a fixed viewport height and a column layout", () => {
    // Without a bounded height there is nothing for the footer to be pinned
    // against: the shell grows with its content and the action scrolls with
    // the page, which is exactly the state F-08 was captured in.
    expect(declaration(".shell-frame", "display")).toBe("flex");
    expect(declaration(".shell-frame", "flex-direction")).toBe("column");
    expect(declaration(".shell-frame", "height")).toMatch(/^100(vh|dvh)$/);
    expect(declaration(".shell-frame", "max-height")).toMatch(/^100(vh|dvh)$/);
  });

  it("styles.css makes the middle region the one scroller, and one that can actually shrink", () => {
    expect(declaration(".shell-scroll", "overflow-y")).toBe("auto");
    // The flexbox rule this whole layout stands on: a flex item's default
    // `min-height: auto` refuses to shrink below its content, so without this
    // the "scroll" region grows to fit and pushes the footer off-screen
    // instead of scrolling.
    expect(declaration(".shell-scroll", "min-height")).toBe("0");
    expect(declaration(".shell-scroll", "flex")).toMatch(/^1 1 auto$/);
  });

  it("puts each scrolling region in the tab order, so it can be scrolled by keyboard", async () => {
    // Moving the scroll off the document and into a container costs the
    // keyboard its default scroller: PageDown/End/arrows act on whatever has
    // focus, and a plain `overflow-y: auto` div is only implicitly focusable
    // in recent Chromium ("keyboard-focusable scrollers"), which is not a
    // safe assumption across the WebView2 versions a PEG station may have.
    // F-08 was a KEYBOARD-and-mouse finding; this keeps the keyboard half.
    (window as unknown as { __TAURI__: Bridge }).__TAURI__ = {
      invoke: async () => "null"
    };
    const screens = [
      createElement(MachineCheckScreen, { hardware: HARDWARE, probeError: null, onContinue: () => {} }),
      createElement(DownloadPlanScreen, {
        freeDiskBytes: HARDWARE.free_disk_bytes,
        hardware: HARDWARE,
        selected: new Set(["app_runtime" as const]),
        onToggleLarge: () => {},
        linkSpeedBps: null,
        onContinue: () => {}
      }),
      createElement(DownloadingScreen, { selectedIds: ["app_runtime"], onAllComplete: () => {} })
    ];
    for (const screen of screens) {
      await act(async () => {
        root.render(screen);
        await Promise.resolve();
      });
      const region = scrollRegions(container)[0];
      expect(region, "no scroll region on this screen").toBeDefined();
      expect(region.getAttribute("tabindex")).toBe("0");
      // And it must announce itself, or a screen reader lands on an unnamed
      // focus stop between the heading and the action.
      expect(region.getAttribute("aria-label")).toBeTruthy();
      region.focus();
      expect(document.activeElement).toBe(region);
    }
  });

  it("the machine-check screen keeps Continue outside the scrolling region", () => {
    act(() => {
      root.render(
        createElement(MachineCheckScreen, { hardware: HARDWARE, probeError: null, onContinue: () => {} })
      );
    });
    const regions = scrollRegions(container);
    expect(regions).toHaveLength(1);
    expect(regions[0].contains(buttonNamed(container, "Continue"))).toBe(false);
  });

  it("the download-plan screen keeps Continue outside the scrolling region", () => {
    act(() => {
      root.render(
        createElement(DownloadPlanScreen, {
          freeDiskBytes: HARDWARE.free_disk_bytes,
          hardware: HARDWARE,
          selected: new Set(["app_runtime" as const]),
          onToggleLarge: () => {},
          linkSpeedBps: null,
          onContinue: () => {}
        })
      );
    });
    const regions = scrollRegions(container);
    expect(regions).toHaveLength(1);
    // The plan rows are the long part -- they must be what scrolls.
    expect(regions[0].querySelector(".plan-list")).not.toBeNull();
    expect(regions[0].contains(buttonNamed(container, "Continue"))).toBe(false);
  });

  it("the downloading screen keeps its stop control outside the scrolling region", async () => {
    (window as unknown as { __TAURI__: Bridge }).__TAURI__ = {
      invoke: async (command: string) => {
        if (command === "start_acquisition" || command === "startAcquisition") {
          return "started";
        }
        return "null";
      }
    };
    await act(async () => {
      root.render(
        createElement(DownloadingScreen, {
          selectedIds: ["app_runtime", "server_binaries", "captions_medium", "local_ai_model"],
          onAllComplete: () => {}
        })
      );
      await Promise.resolve();
    });
    const regions = scrollRegions(container);
    expect(regions).toHaveLength(1);
    expect(regions[0].querySelector(".download-list")).not.toBeNull();
    expect(regions[0].contains(buttonNamed(container, "Stop downloading"))).toBe(false);
    // The headline "x of y" must stay put too -- it is the one number an
    // operator watches, and it was the number frozen on screen in F-04.
    expect(regions[0].querySelector(".overall-progress")).toBeNull();
  });
});
