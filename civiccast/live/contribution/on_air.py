# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 guest on-air → channel live seam (build step 9 slice 3e).

When the operator puts a remote guest on-air, CivicCast must be airing the
channel's **live (composited) feed**. There is **no internal live pad** (slice 1
design): the compositor (GStreamer ``wpesrc`` / OBS, S17 §6 step 3) mixes the
guest into the channel's live source, and the engine airs it through the proven
**S5 content-reload takeover** (``swap_role('live')`` was routed there in slice
1). So this seam reuses ``go_on_air`` / the takeover path rather than inventing a
new pad:

* The **first** guest on-air triggers the channel's live takeover.
* **Subsequent** guests are already inside the live composition — the takeover is
  idempotent (an already-live channel is a silent no-op, handled by the caller
  swallowing ``AlreadyLiveError``).

The actual frame compositing (wpesrc rendering the guest's solo-view URL into the
program) runs on the egress box and is the LPM rung-1 proof (S17 §8 item 2); this
module is the wiring that fires the takeover. ``AlreadyLiveError`` is swallowed
(idempotent: a second guest on-air in an already-live room). Any other hook failure
propagates to the service layer, which reverts guest/room state and raises a
``TakeoverHookError`` → the router returns 503.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from civiccast.egress.takeover_service import AlreadyLiveError
from civiccast.live.contribution.models import ContributionRoom, RemoteGuestSession

_LOG = logging.getLogger(__name__)

# (channel_id) -> None: bring the channel's live (composited) feed on-air. Wired
# to the S5 takeover path in the app factory; None when no engine is wired (the
# operator then airs the composited feed manually).
ChannelGoLive = Callable[[str], None]


def build_contribution_on_air_hook(
    take_live: ChannelGoLive | None,
) -> Callable[[RemoteGuestSession, ContributionRoom], None]:
    """Build the ContributionService ``on_air_hook`` (see module docstring)."""

    def _hook(session: RemoteGuestSession, room: ContributionRoom) -> None:
        if take_live is None:
            _LOG.info(
                "Guest %s on-air in room %s (channel %s); no engine takeover wired "
                "— the operator airs the composited feed.",
                session.session_id,
                room.room_id,
                room.channel_id,
            )
            return
        try:
            take_live(room.channel_id)
        except AlreadyLiveError:
            _LOG.info(
                "Channel %s is already live; guest %s joins the existing composition.",
                room.channel_id,
                session.session_id,
            )

    return _hook


__all__ = ["ChannelGoLive", "build_contribution_on_air_hook"]
