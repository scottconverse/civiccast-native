// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// The first-run download experience is gated by exactly ONE thing: the
// `civiccast.acquisitionFlowComplete` localStorage key (App.tsx's
// `showAcquisitionFlow` initial state). That key is set the moment every
// selected component reports complete, and until this change nothing in the
// product could ever unset it:
//
//   * "Reset progress" clears installer-state files, not localStorage;
//   * Tauri's NSIS uninstaller only removes $LOCALAPPDATA\org.civiccast.native
//     when the operator ticks "Delete the installer's saved settings for this
//     Windows account", and a silent (/S) uninstall never shows that box;
//   * a silent (/S) INSTALL never launches this GUI at all (main.rs's
//     `start_acquisition` doc comment), so it cannot even reach the flow.
//
// A station that lands on "Ready" with no `%PROGRAMDATA%\CivicCast\packs\
// local-ai-model` and no `packs\captions-floor` therefore had no surface
// anywhere -- Setup app or operator console -- that could start the download.
// This file pins the two halves of the escape hatch that closes that: the
// latch is clearable, and the wizard actually offers a control that clears it.
//
// No JSX (plain `.ts`, not `.tsx`) -- vitest.config.ts globs only
// `src/**/*.test.ts`; see AcquisitionFlow.test.ts's header.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { beforeEach, describe, expect, it } from "vitest";

import { acquisitionFlowAlreadyComplete, clearAcquisitionFlowComplete } from "./AcquisitionFlow";

const ACQUISITION_DONE_KEY = "civiccast.acquisitionFlowComplete";

// vitest's `include` glob runs from this package's own root
// (civiccast/apps/installer), so process.cwd() is stable here -- the same
// convention styles.test.ts uses.
function readAppSource(): string {
  return readFileSync(join(process.cwd(), "src", "App.tsx"), "utf-8");
}

describe("the acquisition-complete latch is clearable", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("reports complete only while the key is set, and clearing it undoes that", () => {
    expect(acquisitionFlowAlreadyComplete()).toBe(false);
    window.localStorage.setItem(ACQUISITION_DONE_KEY, "1");
    expect(acquisitionFlowAlreadyComplete()).toBe(true);
    clearAcquisitionFlowComplete();
    expect(acquisitionFlowAlreadyComplete()).toBe(false);
    expect(window.localStorage.getItem(ACQUISITION_DONE_KEY)).toBeNull();
  });

  it("is a no-op, not a throw, when the latch was never set", () => {
    expect(() => clearAcquisitionFlowComplete()).not.toThrow();
    expect(acquisitionFlowAlreadyComplete()).toBe(false);
  });

  it("clears the SAME key the flow itself writes, so the two cannot drift", () => {
    // AcquisitionFlow.tsx owns the key name privately; this asserts the
    // setter and the clearer agree by driving both through their public
    // surfaces rather than re-transcribing the constant a third time.
    const flowSource = readFileSync(join(process.cwd(), "src", "AcquisitionFlow.tsx"), "utf-8");
    const declarations = flowSource.match(/ACQUISITION_DONE_KEY = "[^"]+"/g) ?? [];
    expect(declarations).toEqual([`ACQUISITION_DONE_KEY = "${ACQUISITION_DONE_KEY}"`]);
  });
});

describe("the wizard offers a way back into the download experience", () => {
  it("wires a control that clears the latch and re-enters the flow", () => {
    const source = readAppSource();
    expect(source).toContain("clearAcquisitionFlowComplete");
    expect(source).toContain("const openAcquisitionFlow = () => {");
    expect(source).toContain("setShowAcquisitionFlow(true)");
    expect(source).toContain("Download AI models and captions");
  });

  it("puts that control on the wizard shell, not only on a failure path", () => {
    // The stranded station reports "Ready", every lane success, no error and
    // no blocked lane anywhere -- so a control gated on `lane.status ===
    // "error"` (the shape "Open installer log" uses) would still be
    // unreachable on exactly the machines that need it. It belongs in the
    // always-rendered "More options" disclosure beside "Show uninstall
    // instructions".
    const source = readAppSource();
    const uninstallAt = source.indexOf("Show uninstall instructions");
    const moreActionsAt = source.indexOf('<details className="more-actions">');
    const controlAt = source.indexOf("Download AI models and captions");
    expect(moreActionsAt).toBeGreaterThan(-1);
    expect(controlAt).toBeGreaterThan(moreActionsAt);
    expect(controlAt).toBeLessThan(uninstallAt);
  });
});
