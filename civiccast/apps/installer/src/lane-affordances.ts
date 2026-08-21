// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import type { InstallerLane, InstallerState } from "./types";

/**
 * GUI gates that decide which remedies the installer offers for a lane.
 *
 * Extracted from App.tsx (which mounts a React root at import time and so
 * cannot be unit-tested) for the same reason installer-transition.ts and
 * progress-visual.ts were: these are pure predicates whose wrong answer ships
 * a button that cannot work.
 *
 * Formerly `wsl-affordances.ts`. That file used to gate the retired WSL2
 * bootstrap remedy -- "Set up Windows helper", and "Repair this step" on the
 * platform lane -- both of which routed through main.rs's
 * `is_wsl_bootstrap_lane` into headless-bootstrap.ps1's `apt-get install`.
 * That whole pipeline (script, Rust dispatch, and this module's WSL
 * predicates) was deleted under the owner's "no linux" decision. Renamed to
 * drop the now-inapplicable name.
 */

/** True for the native Windows station -- the only Windows deployment now. */
export function isWindowsPlatform(installer: InstallerState) {
  return installer.platform === "windows-native";
}

/**
 * True when "Repair this step" should render.
 *
 * The `platform` lane is suppressed: main.rs routes "repair" on every
 * non-runtime lane to a state write that queues nothing and returns
 * "CivicCast queued a repair pass" -- a promise nothing keeps. A button that
 * cannot deliver is worse than no button (same reasoning that keeps the
 * ffmpeg lane out of "blocked").
 */
export function canRepairLane(_installer: InstallerState, lane: InstallerLane) {
  if (lane.id === "platform") {
    return false;
  }
  return lane.status === "error" || lane.status === "blocked";
}
