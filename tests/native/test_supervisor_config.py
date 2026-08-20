# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the supervisor configuration model and identity constants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.native.runtime_guard import MUTEX_SDDL
from civiccast.native.supervisor.config import (
    CONTROL_PIPE_NAME,
    SERVICE_NAME,
    SINGLETON_MUTEX_NAME,
    SINGLETON_MUTEX_SDDL,
    STARTUP_ORDER,
    SupervisorConfig,
)


def test_defaults_match_the_spec_values() -> None:
    cfg = SupervisorConfig()
    assert cfg.backoff_initial_seconds == 1.0
    assert cfg.backoff_max_seconds == 30.0
    assert cfg.backoff_jitter_fraction == 0.20
    assert cfg.restart_storm_threshold == 5
    assert cfg.restart_storm_window_seconds == 600.0
    assert cfg.graceful_stop_deadline_seconds == 15.0
    assert cfg.postgres_ready_budget_seconds == 60.0
    assert cfg.control_pipe_frame_cap_bytes == 16 * 1024


def test_extra_key_is_forbidden() -> None:
    with pytest.raises(ValidationError):
        SupervisorConfig(unknown_field=1)  # type: ignore[call-arg]


def test_backoff_max_below_initial_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SupervisorConfig(backoff_initial_seconds=10.0, backoff_max_seconds=5.0)


@pytest.mark.parametrize(
    "field",
    [
        "backoff_initial_seconds",
        "backoff_max_seconds",
        "restart_storm_window_seconds",
        "graceful_stop_deadline_seconds",
        "postgres_ready_budget_seconds",
        "guard_interval_seconds",
    ],
)
def test_positive_only_fields_reject_zero(field: str) -> None:
    with pytest.raises(ValidationError):
        SupervisorConfig(**{field: 0})


def test_jitter_fraction_is_bounded_zero_to_one() -> None:
    with pytest.raises(ValidationError):
        SupervisorConfig(backoff_jitter_fraction=1.5)
    with pytest.raises(ValidationError):
        SupervisorConfig(backoff_jitter_fraction=-0.1)


def test_identity_constants() -> None:
    assert SERVICE_NAME == "CivicCastSupervisor"
    assert SINGLETON_MUTEX_NAME == r"Global\CivicCastSupervisorSingleton"
    assert CONTROL_PIPE_NAME == r"\\.\pipe\civiccast-supervisor"
    # spec D3/D7 "same explicit SD": the singleton reuses WS4's runtime-owner
    # mutex DACL rather than defining a second, drift-prone copy.
    assert SINGLETON_MUTEX_SDDL == MUTEX_SDDL


def test_startup_order_is_the_three_direct_children() -> None:
    # Workers are owned by the control plane (D2), not the supervisor, so they
    # are deliberately absent.
    assert STARTUP_ORDER == ("postgres", "nats", "control_plane")
