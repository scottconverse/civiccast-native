# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared caption-test fixtures (opt-in only).

Nothing here is autouse.  A test module must request
``deterministic_staff_token`` explicitly (via ``pytestmark``) to get the
behaviour, so unrelated ``tests/captions`` modules -- including ones that
deliberately exercise ambient/configured staff-token behaviour -- are
unaffected.

Why the fixture exists at all
-----------------------------
``civiccast.auth.tokens._configured_tokens`` resolves the documented
deterministic fixture token (``operator-token-a``) ONLY when
``CIVICCAST_STAFF_TOKENS`` is unset: a configured deployment token list (or an
ambient value in a developer shell) takes precedence, and the fixture token is
then rejected with a real 401.  The three caption HTTP router modules
authenticate with that fixture token, so they must neutralize the shadowing
variable to test their routes.

This is a TEST-ONLY environment isolation.  It does not enable a fallback,
does not weaken authorization, and changes no production code.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

#: Variables that shadow the documented deterministic fixture token.  A set
#: ``CIVICCAST_STAFF_TOKENS`` makes ``_configured_tokens`` return the
#: deployment list and ignore ``operator-token-a``.  The DB fallback switch is
#: cleared for the same reason (no ambient value may steer the decision).
_SHADOWING_ENV = (
    "CIVICCAST_STAFF_TOKENS",
    "CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB",
)


@pytest.fixture
def deterministic_staff_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the documented fixture token the effective staff identity.

    Requested explicitly by the three caption router modules.  ``monkeypatch``
    records and restores the previous values, so the surrounding process
    environment is unchanged after each test.
    """

    for name in _SHADOWING_ENV:
        monkeypatch.delenv(name, raising=False)
    # tests/conftest.pytest_configure enables this globally (setdefault), but
    # pin it here so a future refactor cannot silently drop the opt-in these
    # tests depend on.
    if os.environ.get("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN") != "1":
        monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")


@pytest.fixture
def close_app_owned_outboxes(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    """Capture and close every ``AsRunOutbox`` the app builds during a test.

    TEST-side teardown for a KNOWN post-beta.10 product ownership gap: the app
    opens an ``AsRunOutbox`` sqlite3 journal when durable storage is wired, and
    nothing in the product closes it (it is not reachable from ``app.state``,
    nor from ``EgressDaemon``). Without this, a durable ``create_app()`` in a
    test leaks the handle to the GC, whose ResourceWarning pytest promotes to an
    unraisable exception on an unrelated test.

    The construction site in ``civiccast/egress/automation.py`` uses a
    function-local ``from civiccast.reporting.asrun_outbox import AsRunOutbox``,
    so patching that module attribute is the seam the local import resolves.
    Each captured instance is closed with its real ``close()`` on teardown.
    EVERY captured handle is attempted even if one ``close()`` raises: the loop
    never aborts early on the first failure. The first failure is RE-RAISED
    after the whole loop so the test still reports it (never swallowed), while
    later handles are still finalized.
    """

    import civiccast.reporting.asrun_outbox as outbox_module

    captured: list[object] = []
    real_factory = outbox_module.AsRunOutbox

    def recording_factory(*args: object, **kwargs: object) -> object:
        instance = real_factory(*args, **kwargs)
        captured.append(instance)
        return instance

    monkeypatch.setattr(outbox_module, "AsRunOutbox", recording_factory)
    try:
        yield captured
    finally:
        first_close_error: BaseException | None = None
        for instance in captured:
            close = getattr(instance, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except BaseException as exc:  # recorded then re-raised below
                # Record the FIRST close failure but keep going: a later handle
                # must still be finalized even when an earlier one raises.
                if first_close_error is None:
                    first_close_error = exc
        if first_close_error is not None:
            # Never swallow: surface the first close failure to the test run.
            raise first_close_error
