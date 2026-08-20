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
MSE blob playback on the public portal.
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
    on JSON and this keeps the middleware a single unconditional pass
    rather than a route-shape-sniffing branch.
    """

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
    return response
