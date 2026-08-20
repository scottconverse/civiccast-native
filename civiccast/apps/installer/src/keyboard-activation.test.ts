// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import { describe, expect, it } from "vitest";

import { shouldActivateWslShortcut, shouldArmWslShortcut } from "./keyboard-activation";

describe("shouldActivateWslShortcut", () => {
  it("fires when nothing has keyboard focus (native focus-loss case)", () => {
    const primaryButton = document.createElement("button");
    expect(shouldActivateWslShortcut(null, primaryButton)).toBe(true);
  });

  it("fires when document.body has focus", () => {
    const primaryButton = document.createElement("button");
    expect(shouldActivateWslShortcut(document.body, primaryButton)).toBe(true);
  });

  it("fires when the primary WSL action button itself has focus", () => {
    const primaryButton = document.createElement("button");
    expect(shouldActivateWslShortcut(primaryButton, primaryButton)).toBe(true);
  });

  it("does NOT fire when a different control (Retry, Cancel, a step button, ...) has focus (UX-1 / G-5)", () => {
    const primaryButton = document.createElement("button");
    const retryButton = document.createElement("button");
    expect(shouldActivateWslShortcut(retryButton, primaryButton)).toBe(false);
  });

  it("does NOT fire when the 'More options' summary has focus", () => {
    const primaryButton = document.createElement("button");
    const summary = document.createElement("summary");
    expect(shouldActivateWslShortcut(summary, primaryButton)).toBe(false);
  });
});

describe("shouldArmWslShortcut", () => {
  const wslBlocked = {
    showAcquisitionFlow: false,
    hasInstaller: true,
    requestedState: false,
    laneIsWslBootstrap: true,
  };

  it("arms only for a WSL-bootstrap lane in the old wizard", () => {
    expect(shouldArmWslShortcut(wslBlocked)).toBe(true);
    expect(shouldArmWslShortcut({ ...wslBlocked, laneIsWslBootstrap: false })).toBe(false);
  });

  it("NEVER arms while the download-experience screens are showing (2026-07-31 Blocker)", () => {
    // The exact reproduced case: a WSL-blocked installer state resolves in the
    // background while AcquisitionFlow is on screen. Arming here would let a
    // stray Enter/Space silently fire the Windows-helper setup action.
    expect(shouldArmWslShortcut({ ...wslBlocked, showAcquisitionFlow: true })).toBe(false);
  });

  it("does not arm without an installer, or while an action is in flight", () => {
    expect(shouldArmWslShortcut({ ...wslBlocked, hasInstaller: false })).toBe(false);
    expect(shouldArmWslShortcut({ ...wslBlocked, requestedState: true })).toBe(false);
  });
});
