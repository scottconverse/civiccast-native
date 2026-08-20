# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "civiccast" / "apps" / "portal-operator" / "src" / "api" / "client.ts"
SETUP_SCREEN = (
    ROOT / "civiccast" / "apps" / "portal-operator" / "src" / "screens" / "SetupScreen.tsx"
)


def test_operator_console_prefers_first_admin_token_over_test_injection() -> None:
    source = CLIENT.read_text(encoding="utf-8")

    assert "const localToken = window.localStorage.getItem('civiccast.staffToken')" in source
    assert "const sessionToken = window.sessionStorage.getItem('civiccast.staffToken')" in source
    assert "const injectedToken = window.__CIVICCAST_STAFF_TOKEN__" in source
    assert source.index("localToken ??") < source.index("sessionToken ??")
    assert source.index("sessionToken ??") < source.index("injectedToken ??")


def test_first_admin_login_and_recovery_sync_local_and_session_staff_tokens() -> None:
    source = SETUP_SCREEN.read_text(encoding="utf-8")

    assert source.count("window.localStorage.setItem('civiccast.staffToken'") == 3
    assert source.count("window.sessionStorage.setItem('civiccast.staffToken'") == 3
