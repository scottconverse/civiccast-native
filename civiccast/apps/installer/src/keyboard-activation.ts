// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

// Pulled out of App.tsx so it is unit-testable without importing that module's
// top-level render side effect (UX-1 / G-5, G-19).

export function isActivationKey(event: KeyboardEvent) {
  return (
    event.key === "Enter" ||
    event.key === " " ||
    event.key === "Space" ||
    event.key === "Spacebar" ||
    event.code === "Enter" ||
    event.code === "NumpadEnter" ||
    event.code === "Space" ||
    event.keyCode === 13 ||
    event.keyCode === 32
  );
}

// Whether the window-level WSL activation shortcut should fire for the given
// focus state. It only fires when nothing else has keyboard focus (the
// native-window-focus-loss case this shortcut exists for) or when the
// primary action button itself is focused. Any other focused control (Retry,
// Cancel, a step button, the "More options" summary, ...) owns its own
// Enter/Space activation and must not be hijacked.
export function shouldActivateWslShortcut(activeElement: Element | null, primaryButton: Element | null) {
  return !activeElement || activeElement === document.body || activeElement === primaryButton;
}

// Whether App should ARM the window-level WSL Enter/Space listener at all.
// The listener belongs to the old wizard; it must NOT be attached while the
// download-experience screens are showing (App's hooks run before the
// showAcquisitionFlow early return, so an ungated effect would leave it
// live underneath the new UI, letting a stray Enter/Space silently fire the
// Windows-helper setup action — reproduced live 2026-07-31, this is the
// regression this predicate exists to pin).
export function shouldArmWslShortcut(params: {
  showAcquisitionFlow: boolean;
  hasInstaller: boolean;
  requestedState: boolean;
  laneIsWslBootstrap: boolean;
}): boolean {
  if (params.showAcquisitionFlow || !params.hasInstaller || params.requestedState) {
    return false;
  }
  return params.laneIsWslBootstrap;
}
