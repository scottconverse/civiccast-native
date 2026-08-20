# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real setup-boundary app for Playwright.

The browser test exercises the production setup router and app wiring while
adding only local CORS for the Vite preview origin.
"""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from civiccast.app import create_app

app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4174", "http://127.0.0.1:4174"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
