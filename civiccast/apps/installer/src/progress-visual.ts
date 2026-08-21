// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import type { InstallerProgress } from "./types";

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
