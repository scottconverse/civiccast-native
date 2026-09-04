# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gi-free decision logic for seamless program-leg reloads (D-S1-6 / B3 fix).

Kept out of ``engine.py`` for the same reason ``decode_policy.py`` is: ``engine.py``
cannot be imported at all without ``gi`` + a real GStreamer install, so any logic
worth unit-testing on a bare checkout has to live in a sibling module the engine
imports rather than duplicates.

Two independent decisions live here, both born from the same soak defect
(Desktop/CIVICCAST-EVIDENCE/soak-120-4b30c99-20260904, kit 4b30c99): back-to-back
scheduled premieres EOS'd the GStreamer worker at every plan boundary because
nothing extended a live (ON_AIR) plan before it ran out.

1. **When to trigger a rollover reload.** A cold conform (``SourcePreparer``) can
   take minutes; triggering the reload only 30s before the live plan's projected
   end (the first cut of this fix) leaves the prepare step racing the pipeline's
   own EOS. ``rollover_trigger_at`` computes an EARLIER, boundary-aligned trigger
   time: the moment the plan's LAST segment begins, or ``min_lead_seconds`` before
   the plan's projected end -- whichever is earlier (the more conservative, i.e.
   earliest, of the two).

2. **Whether the engine may defer the selector switch to the outgoing leg's own
   EOS**, instead of cutting to the new leg the instant it is ready
   (``GstPlayoutEngine.reload_program``'s historic behavior). Triggering the
   rollover much earlier (per 1 above) means the new leg is typically ready WELL
   before the old leg's natural end; switching immediately on readiness would then
   TRUNCATE the tail of the still-airing item -- a regression worse than the
   EOS-restart this fix targets. Deferring the switch to the old leg's own EOS
   keeps the two legs mutually synchronized on the shared pipeline clock (both
   built from the same wall-clock join-in-progress offset) and lets the airing
   item finish naturally, with no re-decode and no jump.

   Deferring is safe ONLY for an automation-driven extension of an already-ON_AIR
   plan with no operator override in effect. An operator-initiated live takeover or
   forced slate is a deliberate "now" request -- see ``PlayoutSupervisor.
   request_live_takeover``/``request_fallback_slate`` (civiccast/egress/
   supervisor.py) -- and must still cut immediately, so ``should_defer_switch``
   returns False whenever a manual override is active, or the channel was not
   already ON_AIR (e.g. the FALLBACK_SLATE gap-replan reload, which issue #157
   requires to interrupt filler immediately, never wait for it to end).
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: Filename marker ``GstreamerEncoderStrategy.reload_content`` (gst/strategy.py)
#: writes into the one-shot reload sidecar filename, and both worker dispatch
#: paths (``engine._dispatch_control`` for the POSIX FIFO, ``worker.
#: _dispatch_control_with_ack`` for the Windows D2 pipe seam) read back via
#: ``reload_switch_is_deferred`` -- the flag rides the filename instead of a new
#: control-line token because ``parse_control_line``'s ``reload <path>`` grammar
#: takes the ENTIRE line remainder as the path (control.py), so a path is the
#: only slot available to carry information without a wire-format version bump.
DEFERRED_SWITCH_SUFFIX = ".defer-eos.json"
IMMEDIATE_SWITCH_SUFFIX = ".immediate.json"


def reload_sidecar_suffix(*, switch_at_end_of_current: bool) -> str:
    """The filename suffix ``reload_content`` appends, encoding the switch mode."""

    return DEFERRED_SWITCH_SUFFIX if switch_at_end_of_current else IMMEDIATE_SWITCH_SUFFIX


def reload_switch_is_deferred(reload_path: str) -> bool:
    """True when ``reload_path`` (as sent over the control channel) was written
    with ``switch_at_end_of_current=True``. Unknown/legacy filenames (no
    recognized suffix) default to False -- immediate switch, today's behavior --
    so an old daemon/new worker or new daemon/old-format sidecar pairing degrades
    to the pre-existing safe behavior rather than hanging waiting for an EOS
    nobody promised to defer to."""

    return reload_path.endswith(DEFERRED_SWITCH_SUFFIX)


def should_defer_switch(*, previous_state: str | None, manual_override_active: bool) -> bool:
    """True when a content-reload should defer its selector switch to the
    outgoing leg's own EOS rather than cutting the instant the new leg is ready.

    Only an automation-driven extension of an already-ON_AIR plan qualifies:
    a FALLBACK_SLATE gap-replan (``previous_state != "ON_AIR"``) and any reload
    issued while an operator override is active (live takeover / forced slate --
    ``manual_override_active``) must always cut in immediately.
    """

    return previous_state == "ON_AIR" and not manual_override_active


def rollover_trigger_at(
    *,
    plan_end_at: datetime,
    last_segment_start_at: datetime,
    min_lead_seconds: float,
) -> datetime:
    """The earliest wall-clock moment a rollover check should start re-querying
    the schedule for a live plan projected to end at ``plan_end_at``.

    Boundary-aligned: the moment the plan's LAST segment begins is the latest
    point a fresh plan could still be built and prepared without the two racing
    (a cold conform inside that final segment has the least runway of any
    segment in the plan). ``min_lead_seconds`` before the projected end is a
    floor under that for a plan with one long segment (no earlier "last segment
    start" boundary to align to). The earlier (smaller) of the two wins -- never
    later than either candidate.
    """

    if min_lead_seconds < 0:
        raise ValueError("min_lead_seconds must be zero or greater")
    lead_floor = plan_end_at - timedelta(seconds=min_lead_seconds)
    return min(last_segment_start_at, lead_floor)


__all__ = [
    "DEFERRED_SWITCH_SUFFIX",
    "IMMEDIATE_SWITCH_SUFFIX",
    "reload_sidecar_suffix",
    "reload_switch_is_deferred",
    "rollover_trigger_at",
    "should_defer_switch",
]
