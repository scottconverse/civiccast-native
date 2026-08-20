# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 six-hour live/caption/summary/publish soak evidence."""

from __future__ import annotations

from datetime import timedelta
from importlib import import_module


class TestSixHourSoakContract:
    def test_soak_drives_all_pipeline_stages_when_release_mode_runs(self) -> None:
        soak_module = import_module("civiccast.live.soak")

        plan = soak_module.build_six_hour_soak_plan(duration=timedelta(hours=6))

        assert plan.duration == timedelta(hours=6)
        assert plan.stages == ["live", "caption", "egress", "summary", "publish"]
        assert plan.uses_live_state_machine is True

    def test_shortened_soak_cannot_be_reported_as_six_hour_evidence(self) -> None:
        soak_module = import_module("civiccast.live.soak")

        result = soak_module.render_soak_evidence(
            duration=timedelta(minutes=5),
            release_mode=True,
        )

        assert result.status == "failed"
        assert "six-hour" in result.operator_action.lower()
