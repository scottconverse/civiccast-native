# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Legacy S17 guest on-air callback kept for app-wiring compatibility.

The current ``ContributionService.put_on_air`` implementation only marks its
CivicCast session and room records; it does not invoke this callback. Constructing
the helper below therefore does not take a channel live, route guest media, or
establish a compositor connection. Any external OBS/GStreamer composition and
channel routing must be commissioned and operated separately.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from civiccast.egress.takeover_service import AlreadyLiveError
from civiccast.live.contribution.models import ContributionRoom, RemoteGuestSession

_LOG = logging.getLogger(__name__)

# Legacy callback type. If explicitly invoked, this requests channel-live
# takeover; the current ContributionService does not invoke its on-air hook.
ChannelGoLive = Callable[[str], None]


def build_contribution_on_air_hook(
    take_live: ChannelGoLive | None,
) -> Callable[[RemoteGuestSession, ContributionRoom], None]:
    """Build the legacy callback; current ``put_on_air`` does not call it."""

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
