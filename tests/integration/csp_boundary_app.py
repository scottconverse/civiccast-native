# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real app fixture for the CSP-vs-built-portals Playwright gate.

Serves the actual production app (security headers + CSP included) with
the operator console and public portal dist directories mounted, exactly
as ``_mount_packaged_portals`` does for a real station install. No extra
CORS layer — same-origin only, matching the real deployment shape the CSP
has to work against.
"""

from __future__ import annotations

import os

os.environ.setdefault("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
os.environ.setdefault("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
os.environ.setdefault("CIVICCAST_ACTIVITYPUB_MODE", "disabled")
os.environ.pop("DATABASE_URL", None)

from civiccast.app import create_app

app = create_app()
