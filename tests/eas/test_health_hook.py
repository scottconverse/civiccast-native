# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c: the EAS source-health hook routes into the S8 alert hub on STATE CHANGE only."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from civiccast.app import _build_eas_health_hook
from civiccast.eas.models import EasCapSource


@contextmanager
def _fake_factory():
    yield SimpleNamespace(commit=lambda: None)


def _source() -> EasCapSource:
    return EasCapSource(source_id="src_nws", label="NWS", kind="nws-cap")


def test_health_hook_fires_only_on_state_change() -> None:
    src = _source()
    with patch("civiccast.alerting.store.record_alert_condition") as rec:
        hook = _build_eas_health_hook(_fake_factory)
        hook(src, True, "ok")  # first sight + healthy -> no-op
        hook(src, True, "ok")  # unchanged -> no-op
        hook(src, False, "fetch failed")  # transition to unhealthy -> fire
        hook(src, False, "still failing")  # unchanged -> no-op
        hook(src, True, "recovered")  # transition to healthy -> resolve
        resolved_flags = [c.kwargs["resolved"] for c in rec.call_args_list]
        kinds = {c.kwargs["kind"] for c in rec.call_args_list}
    assert rec.call_count == 2
    assert resolved_flags == [False, True]
    assert kinds == {"eas-source-unavailable"}


def test_health_hook_first_failure_fires_immediately() -> None:
    src = _source()
    with patch("civiccast.alerting.store.record_alert_condition") as rec:
        hook = _build_eas_health_hook(_fake_factory)
        hook(src, False, "down on first poll")  # first sight + unhealthy -> fire
        assert rec.call_count == 1
        assert rec.call_args.kwargs["resolved"] is False
        assert rec.call_args.kwargs["resource_ref"] == "src_nws"
