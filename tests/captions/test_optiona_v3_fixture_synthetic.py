# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Synthetic two-handle proof for the ``close_app_owned_outboxes`` teardown.

Option A audit finding: a teardown that calls ``close()`` in a plain loop stops
at the FIRST exception, so later captured handles are never finalized. The
fixture must attempt EVERY close and still surface the first failure (never
swallow it). This pins that contract with two synthetic handles where the first
close raises.
"""

from __future__ import annotations

import pytest


class _RaisingHandle:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True
        raise OSError("first handle refused to close")


class _GoodHandle:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_first_close_failure_still_attempts_every_later_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every captured close() is attempted; the FIRST failure is re-raised."""

    from tests.captions import conftest as caption_conftest

    first, second = _RaisingHandle(), _GoodHandle()
    handles = iter([first, second])

    import civiccast.reporting.asrun_outbox as outbox_module

    monkeypatch.setattr(outbox_module, "AsRunOutbox", lambda *a, **k: next(handles))

    # Drive the real fixture generator: setup -> yield -> teardown. Importing
    # the module directly avoids any pytest-internal wrapper indirection, so
    # this proof can never degrade into a silent skip.
    generator = caption_conftest.close_app_owned_outboxes.__wrapped__(monkeypatch)
    captured = next(generator)
    assert captured == [], "fixture should yield an empty capture list"

    # Simulate two constructed app-owned handles.
    captured.extend([first, second])

    with pytest.raises(OSError, match="first handle refused to close"):
        next(generator)  # teardown

    assert first.closed is True, "first handle was not attempted"
    assert second.closed is True, "second handle was skipped after the first close raised"
