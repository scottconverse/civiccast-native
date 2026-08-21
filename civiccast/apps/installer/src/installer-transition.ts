// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors

import type { InstallerLane, InstallerState } from "./types";

/**
 * The lane the wizard should open on.
 *
 * "unavailable" lanes report an optional capability this install does not
 * have (see types.ts LaneStatus). They are never ready, but nothing is
 * waiting on the operator there, so they must not capture the wizard ahead
 * of a step that genuinely still needs setup -- otherwise a running install
 * that merely cannot process video opens looking like an unfinished one.
 */
export function firstActionableLane(installer: InstallerState): InstallerLane | undefined {
  return (
    installer.lanes.find((lane) => !lane.ready && lane.status !== "unavailable") ??
    installer.lanes.find((lane) => !lane.ready) ??
    installer.lanes[0]
  );
}
