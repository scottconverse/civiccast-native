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
 * NATIVE-ONLY as of 2026-08-20. This module previously also gated the WSL2
 * bootstrap remedy -- "Set up Windows helper", and "Repair this step" on the
 * platform lane -- both of which routed through main.rs's
 * `is_wsl_bootstrap_lane` into headless-bootstrap.ps1's `apt-get install`.
 * That install target was retired with the rest of the WSL lane, so the
 * remedy no longer exists and these predicates now say so unconditionally
 * rather than by checking a platform value that can only take one Windows
 * form.
 *
 * The filename is unchanged deliberately: renaming it while App.tsx's call
 * sites still branch on `isWslBootstrapLane` would be churn on top of churn.
 * Both go together when those dead branches are simplified, which needs the
 * installer UI driven for real, not a compile.
 */

/** The two lane ids whose remedy WAS the WSL bootstrap. */
export function isWslBootstrapLaneId(lane: InstallerLane) {
  return lane.id === "wsl2" || lane.id === "platform";
}

/** True for the native Windows station -- the only Windows deployment now. */
export function isWindowsPlatform(installer: InstallerState) {
  return installer.platform === "windows-native";
}

/**
 * Always false: there is no WSL bootstrap to offer.
 *
 * Kept as a named predicate rather than deleted so App.tsx's three call sites
 * keep reading as intent ("this lane does not offer the bootstrap") instead of
 * becoming bare `false` literals a later reader has to reverse-engineer.
 */
export function isWslBootstrapLane(_installer: InstallerState, _lane: InstallerLane) {
  return false;
}

/**
 * True when "Repair this step" should render.
 *
 * The wsl2/platform lanes are suppressed unconditionally now. main.rs routes
 * "repair" on every non-runtime lane to a state write that queues nothing and
 * returns "CivicCast queued a repair pass" -- a promise nothing keeps. That
 * was already the behaviour on a native station; it is simply no longer
 * conditional. Same reasoning that keeps the ffmpeg lane out of "blocked".
 */
export function canRepairLane(installer: InstallerState, lane: InstallerLane) {
  if (isWslBootstrapLaneId(lane)) {
    return false;
  }
  return lane.status === "error" || lane.status === "blocked";
}
