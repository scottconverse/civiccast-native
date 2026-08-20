// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import type { InstallerProgress } from "./types";

const ACTIVE_WINDOWS_BOOTSTRAP_STATUSES = [
  "wsl_install_requested",
  "wsl_install_started",
  "running",
  "already_running",
  "accepted"
];

export function isWindowsBootstrapProgress(progress: InstallerProgress | null) {
  return Boolean(
    progress &&
      ["wsl2", "platform"].includes(progress.current_lane_id) &&
      ACTIVE_WINDOWS_BOOTSTRAP_STATUSES.includes(progress.status) &&
      !progress.reboot_required
  );
}

export function isRuntimeBootstrapProgress(progress: InstallerProgress | null) {
  return Boolean(
    progress &&
      ["runtime", "ffmpeg", "storage", "service", "dashboard"].includes(progress.current_lane_id) &&
      progress.status === "running" &&
      !progress.reboot_required
  );
}

export function installerActivityElapsedSeconds(progress: InstallerProgress, nowUnix: number) {
  const nativeElapsed = Math.max(progress.elapsed_seconds ?? 0, 0);
  const activityStartedAt = progress.started_at_unix ?? progress.updated_at_unix;
  const locallyObservedElapsed = Math.max(Math.floor(nowUnix - activityStartedAt), 0);
  return Math.max(nativeElapsed, locallyObservedElapsed);
}

/**
 * Windows/WSL does not expose trustworthy byte progress for every servicing,
 * update, and distro-install command. Keep the meter indeterminate so a long
 * phase visibly animates instead of looking frozen at (for example) step 1/2.
 * The adjacent text still reports the real phase, step number, and elapsed time.
 */
export function windowsBootstrapProgressIsIndeterminate(progress: InstallerProgress | null) {
  return isWindowsBootstrapProgress(progress);
}
