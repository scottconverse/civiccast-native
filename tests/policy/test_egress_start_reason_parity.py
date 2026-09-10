# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: the Channels screen's Start-refusal reasons equal the API's 409 detail.

PR #216's self-audit claimed the 409 detail string was "identical in router
and screen constant"; the hostile review showed the Python string carried
"for {channel_id}" and the TS constant did not. This pins the parity by
evaluating the TS template literals against the Python functions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from civiccast.egress.router import start_disabled_config_reason, start_without_config_reason

REPO_ROOT = Path(__file__).resolve().parents[2]
SCREEN = REPO_ROOT / "civiccast/apps/portal-operator/src/screens/egress-start.ts"


def _ts_template(function_name: str) -> str:
    source = SCREEN.read_text(encoding="utf-8")
    match = re.search(
        rf"export function {function_name}\(channelId: string\): string \{{\s*return `([^`]*)`",
        source,
    )
    assert match is not None, f"{function_name} template literal not found in {SCREEN}"
    return match.group(1)


@pytest.mark.parametrize(
    ("ts_function", "py_function"),
    [
        ("startWithoutConfigReason", start_without_config_reason),
        ("startDisabledConfigReason", start_disabled_config_reason),
    ],
)
def test_screen_reason_equals_router_409_detail(ts_function, py_function) -> None:  # type: ignore[no-untyped-def]
    template = _ts_template(ts_function)
    assert "${channelId}" in template
    for channel_id in ("public", "government"):
        assert template.replace("${channelId}", channel_id) == py_function(channel_id)
