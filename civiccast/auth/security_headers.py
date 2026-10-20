# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Security headers for every HTML/API response.

CivicCast can run loopback-only (the default) or be deliberately exposed on
a station's LAN. Browser-side defenses that cost nothing on loopback (no
UX change, nothing to configure) are worth having unconditionally, because
"loopback-only" is a deployment choice an operator can change, not a
guarantee this code can rely on.

The CSP is scoped to what the built operator console and public portal
actually emit: an external ``<script type="module">`` + external
stylesheet, no inline scripts, no inline event handlers. ``style-src``
allows ``'unsafe-inline'`` because Tailwind/React runtime style injection
(``element.style.x = ...``) is same-origin DOM manipulation, not a
third-party script risk, and locking it down would require refactoring the
frontend for no real security gain. ``worker-src blob:`` and
``media-src blob:`` are required for hls.js's worker-based transmuxer and
MSE blob playback on the public portal. The public player-only preview permits
same-origin framing for Live Room; other pages deny framing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response

_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
    ]
)


async def security_headers_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach standard hardening headers to every response.

    Runs for API responses too (not just HTML) — the headers are harmless
    on JSON. Only the public player preview can be framed by this same origin;
    operator pages and other routes retain the default framing denial.
    """

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # Live Room embeds the public player, never the operator console. Keep both
    # browser framing policies aligned and reject every cross-origin ancestor.
    player_preview = (
        request.method in {"GET", "HEAD"}
        and request.url.path == "/"
        and bool(request.query_params.get("manifest"))
        and response.status_code == 200
    )
    frame_options = "SAMEORIGIN" if player_preview else "DENY"
    csp = _CONTENT_SECURITY_POLICY
    if player_preview:
        csp = csp.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
    response.headers.setdefault("X-Frame-Options", frame_options)
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", csp)
    return response
