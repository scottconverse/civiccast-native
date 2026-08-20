# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""GStreamer degraded-mode tier-3 operator alert + tier-5 recovery action."""

from __future__ import annotations

from pathlib import Path

import pytest


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_degraded_env_raises_a_loud_critical_operator_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 3: the control-plane seam that holds a DB session raises the loud
    operator alert when egress was degraded to FFmpeg. The condition kind is
    ``encoder-death`` -- seeded CRITICAL, so the operator safe-to-air surface
    goes OFF the green 'healthy' state (health = DEGRADED, not a green
    'healthy'). The station bootstrap could not raise this itself (it runs
    pre-DB under LocalSystem)."""

    import civiccast.alerting.store as alert_store
    from civiccast.egress import automation

    captured: dict[str, object] = {}

    def _spy_record(session: object, **kwargs: object) -> object:
        captured.update(kwargs)
        captured["session"] = session
        return object()

    monkeypatch.setattr(alert_store, "record_alert_condition", _spy_record)

    session = _FakeSession()
    automation._raise_egress_degraded_alert(
        lambda: session, reason="closure at C:/x is corrupt"
    )

    assert captured["kind"] == "encoder-death"
    assert captured["detail"] == "closure at C:/x is corrupt"
    assert captured["resource_ref"] == "station:egress-engine"
    assert "FFmpeg" in str(captured["summary"])
    assert session.committed is True
    assert session.closed is True


def test_degraded_alert_never_propagates_a_db_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alerting must never block control-plane startup: a raising session
    factory (a schema-less/degraded DB) is swallowed, not re-raised."""

    from civiccast.egress import automation

    def _boom() -> object:
        raise RuntimeError("DB down")

    # Must not raise.
    automation._raise_egress_degraded_alert(_boom, reason="whatever")


def test_degraded_alert_kind_is_a_seeded_critical_condition() -> None:
    """Pin that the kind chosen for the degrade is one alerting migration 0039
    seeds CRITICAL -- the mechanism by which this codebase drives the
    safe-to-air surface off green (there is no free-text per-channel health
    setter; a firing critical condition is how a non-dead-but-degraded state is
    surfaced loudly)."""

    import typing

    from civiccast.alerting.models import AlertConditionKind
    from civiccast.egress.automation import _EGRESS_DEGRADED_ALERT_KIND

    assert _EGRESS_DEGRADED_ALERT_KIND in typing.get_args(AlertConditionKind)
    # These are the migration 0039 critical-seeded kinds; encoder-death is one.
    critical_seeded = {
        "off-air",
        "encoder-death",
        "server-crash",
        "relay-blocked",
        "missing-media",
        "db-unreachable",
        "service-down",
    }
    assert _EGRESS_DEGRADED_ALERT_KIND in critical_seeded


# --------------------------------------------------------------------------
# Tier 5: operator recovery ("repair GStreamer runtime & restore full egress")
# --------------------------------------------------------------------------


def _make_closure_dir(install_root: Path) -> None:
    (install_root / "runtime" / "dependencies" / "gstreamer").mkdir(parents=True)


def test_recovery_healthy_closure_launches_nothing(tmp_path: Path) -> None:
    """Tier 5, transient case: the closure verifies clean now, so no
    destructive re-stage runs. GStreamer egress restores on the next
    control-plane env re-derivation."""

    from civiccast.native import gstreamer_repair

    _make_closure_dir(tmp_path)
    launched: list[list[str]] = []

    result = gstreamer_repair.trigger_gstreamer_repair(
        install_root=tmp_path,
        verifier=lambda _root: True,
        launcher=lambda argv: launched.append(argv) or 0,
    )

    assert result.healthy is True
    assert result.triggered is False
    assert result.remedy == "already-healthy"
    assert launched == []  # nothing destructive ran


def test_recovery_corrupt_closure_launches_scoped_signed_restage(tmp_path: Path) -> None:
    """Tier 5, missing-bytes case: launches the installer's signed re-stage
    scoped to native-app-payload (the pack the closure lives in), detached."""

    from civiccast.native import gstreamer_repair

    _make_closure_dir(tmp_path)
    (tmp_path / gstreamer_repair.INSTALLER_BINARY_NAME).write_bytes(b"exe")
    launched: list[list[str]] = []

    result = gstreamer_repair.trigger_gstreamer_repair(
        install_root=tmp_path,
        verifier=lambda _root: False,
        launcher=lambda argv: launched.append(argv) or 4321,
    )

    assert result.triggered is True
    assert result.healthy is False
    assert result.remedy == "restage-launched"
    assert result.pid == 4321
    assert len(launched) == 1
    argv = launched[0]
    assert argv[0] == str(tmp_path / gstreamer_repair.INSTALLER_BINARY_NAME)
    assert argv[1] == "--civiccast-repair"
    assert argv[2] == str(tmp_path)
    assert argv[3:] == ["--require-component", "native-app-payload"]


def test_recovery_corrupt_closure_without_installer_binary_reports_honestly(
    tmp_path: Path,
) -> None:
    """No installer binary on-box: cannot re-stage the signed closure. Report
    it (remedy=installer-missing) rather than pretend success."""

    from civiccast.native import gstreamer_repair

    _make_closure_dir(tmp_path)
    launched: list[list[str]] = []

    result = gstreamer_repair.trigger_gstreamer_repair(
        install_root=tmp_path,
        verifier=lambda _root: False,
        launcher=lambda argv: launched.append(argv) or 0,
    )

    assert result.triggered is False
    assert result.remedy == "installer-missing"
    assert launched == []


def test_recovery_launch_failure_is_reported_not_raised(tmp_path: Path) -> None:
    """A spawn that fails is reported (remedy=launch-failed), never raised out
    of the recovery action (a staff endpoint calls it)."""

    from civiccast.native import gstreamer_repair

    _make_closure_dir(tmp_path)
    (tmp_path / gstreamer_repair.INSTALLER_BINARY_NAME).write_bytes(b"exe")

    def _boom(_argv: list[str]) -> int:
        raise OSError("spawn failed")

    result = gstreamer_repair.trigger_gstreamer_repair(
        install_root=tmp_path,
        verifier=lambda _root: False,
        launcher=_boom,
    )

    assert result.triggered is False
    assert result.remedy == "launch-failed"


def test_recovery_build_repair_command_shape(tmp_path: Path) -> None:
    """The repair argv is exactly the scoped one-shot invocation."""

    from civiccast.native import gstreamer_repair

    binary = tmp_path / "CivicCast Native.exe"
    argv = gstreamer_repair.build_repair_command(binary, tmp_path)
    assert argv == [
        str(binary),
        "--civiccast-repair",
        str(tmp_path),
        "--require-component",
        "native-app-payload",
    ]
