# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""RAT-001: maintenance mode is a versioned, fail-closed, enforceable contract.

The supervisor never sets CIVICCAST_SUPERVISOR_MODE on the WSL/Linux path —
these tests pin that the app defaults to "normal" (nothing new gated) when
the env is absent, so the WSL path is provably unchanged, and separately pin
the maintenance behavior: no worker/write-surface supervisors start, every
mutating route 503s, GET routes keep serving, and /health attests the full
gate the supervisor's own maintenance-readiness check depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TOKEN = "maintenance-test-token"  # deterministic local test fixture token, not a secret
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A file-backed SQLite app environment with the durable-storage wiring
    (background_supervisors + finalization_worker_supervisor) populated, so
    the maintenance gate has real supervisors to hold back."""

    db_path = tmp_path / "maintenance.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_TOKEN}:maint-op:Maintenance Operator:meeting_operator,setup_admin,publish_operator",
    )
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "inline")
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE", raising=False)
    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", raising=False)
    _migrate(db_path)
    return tmp_path


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


@pytest.mark.parametrize("blank", [" ", "", "\t", "  \t  ", "\n"])
def test_ccws5_009_present_but_blank_mode_fails_closed_to_unknown(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CC-WS5-009 (Codex): a present-but-blank CIVICCAST_SUPERVISOR_MODE (e.g.
    " ", "", "\\t") must fail CLOSED to "unknown", NOT open to writer-capable
    "normal". Only a genuinely-ABSENT env is backward-compat "normal"; an
    explicitly-present value that strips to empty is a launch that specified a
    mode and got a blank one -- fail-closed, never grant normal behavior."""

    from civiccast.app import _supervisor_mode

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", blank)
    assert _supervisor_mode() == "unknown"


def test_ccws5_009_absent_mode_stays_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    """CC-WS5-009 boundary: a genuinely-UNSET env stays "normal" (unchanged WSL/
    plain-boot backward-compat) -- distinct from the present-but-blank case."""

    from civiccast.app import _supervisor_mode

    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE", raising=False)
    assert _supervisor_mode() == "normal"


def _named_supervisor(app: object, name: str) -> object:
    supervisors = getattr(app.state, "background_supervisors", [])  # type: ignore[attr-defined]
    matches = [s for s in supervisors if getattr(s, "_name", None) == name]
    assert matches, f"no background supervisor named {name!r} in {supervisors!r}"
    return matches[0]


def test_normal_mode_is_the_default_when_env_is_absent(app_env: Path) -> None:
    """expected-red-in-design: no supervisor env at all -> mode "normal", the
    exact WSL/plain-boot posture (nothing new gated), and every worker/write
    surface starts."""

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "normal"
        assert "workers_started" not in health.json()
        assert "mutating_disabled" not in health.json()

        automation = _named_supervisor(app, "civiccast-channel-automation")
        assert automation.running is True
        finalization = app.state.finalization_worker_supervisor
        assert finalization.running is True

        created = client.post(
            "/api/staff/live/recording-targets",
            json={
                "recording_target_id": "fs-primary",
                "name": "Primary recordings",
                "target_uri": (app_env / "recordings").as_uri(),
            },
            headers=_HEADERS,
        )
        assert created.status_code == 201, created.text


def test_maintenance_with_wrong_contract_version_reports_unknown(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """expected-red-in-design: maintenance is set but the contract version is
    wrong -> mode "unknown", fail-closed per the design addendum (an old or
    mode-ignoring control plane can never look maintenance-ready)."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "99")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "unknown"


def test_maintenance_with_absent_contract_version_reports_unknown(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", raising=False)

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.json()["mode"] == "unknown"


def test_explicit_unknown_mode_value_fails_closed_not_normal(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CC-WS5-009 (Codex): an explicitly-PRESENT supervisor mode that is neither
    "maintenance" nor "normal" must fail CLOSED to "unknown" (workers held back,
    mutating routes 503) -- NOT normalize to "normal", which would let an
    incorrectly/maliciously launched control plane run writer-capable while a
    freeze is intended. (A MISSING env stays "normal" for WSL backward-compat --
    that is test_normal_mode_is_the_default_when_env_is_absent.)"""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "unknown")  # explicit, not maintenance/normal
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        assert app.state.supervisor_mode == "unknown"
        assert client.get("/health").json()["mode"] == "unknown"
        automation = _named_supervisor(app, "civiccast-channel-automation")
        assert automation.running is False, (
            "explicit unknown mode must fail closed (hold back workers)"
        )
        mutating = client.post(
            "/api/staff/live/recording-targets",
            json={
                "recording_target_id": "fs-primary",
                "name": "Primary recordings",
                "target_uri": (app_env / "recordings").as_uri(),
            },
            headers=_HEADERS,
        )
        assert mutating.status_code == 503


def test_explicit_normal_mode_value_is_normal(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit "normal" mode value is normal (workers run) -- distinct from an
    unrecognized value, which fails closed (above)."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "normal")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        assert app.state.supervisor_mode == "normal"
        automation = _named_supervisor(app, "civiccast-channel-automation")
        assert automation.running is True


def test_unknown_mode_is_fail_closed_holds_back_workers(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-CP-1 (coordinator review, FALSIFICATION): "unknown" (the maintenance
    env is SET but the contract version is unrecognized) must FAIL-CLOSED like
    maintenance -- hold back the worker/write surfaces. The supervisor clearly
    intended a freeze; the app must NOT fall back to normal and start workers
    during the intended window. An app that treats "unknown" as "normal" and
    relies only on the supervisor's external readiness gate to refuse is the
    exact RAT-001 fail-open: worker automation comes up while the maintenance
    marker is held."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "99")  # unrecognized -> "unknown"

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        assert app.state.supervisor_mode == "unknown"
        automation = _named_supervisor(app, "civiccast-channel-automation")
        assert automation.running is False, "unknown mode must hold back automation (fail-closed)"
        finalization = app.state.finalization_worker_supervisor
        assert finalization.running is False, (
            "unknown mode must hold back the finalization worker (fail-closed)"
        )


def test_unknown_mode_is_fail_closed_503s_mutating_routes(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-CP-1: the mutating-route guard also fires for "unknown", not just
    "maintenance" -- a mutating POST is refused 503, a GET keeps serving."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "99")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        assert app.state.supervisor_mode == "unknown"
        mutating = client.post(
            "/api/staff/live/recording-targets",
            json={
                "recording_target_id": "fs-primary",
                "name": "Primary recordings",
                "target_uri": (app_env / "recordings").as_uri(),
            },
            headers=_HEADERS,
        )
        assert mutating.status_code == 503
        assert mutating.json() == {"error": "maintenance"}
        assert client.get("/api/staff/schedule", headers=_HEADERS).status_code == 200


def test_maintenance_mode_holds_back_automation_and_finalization_worker(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """positive: correct maintenance env -> ChannelAutomationService and the
    finalization worker (the worker/write surfaces) are NOT started."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        automation = _named_supervisor(app, "civiccast-channel-automation")
        assert automation.running is False
        finalization = app.state.finalization_worker_supervisor
        assert finalization.running is False


def test_maintenance_mode_attests_full_gate_on_health(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """positive: /health attests mode + workers_started:false +
    mutating_disabled:true + mode_contract:1 -- the exact fields the
    supervisor's maintenance-readiness gate is defined against."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["mode"] == "maintenance"
        assert body["workers_started"] is False
        assert body["mutating_disabled"] is True
        assert body["mode_contract"] == 1


def test_maintenance_mode_503s_mutating_routes_but_serves_get(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """positive: a POST to a mutating route returns 503 {"error":"maintenance"};
    a GET read route returns 200.

    FALSIFICATION: this POST carries a fully valid, correctly-authorized
    payload that a normal-mode app accepts with 201 (see
    test_normal_mode_is_the_default_when_env_is_absent) — if the maintenance
    guard were checking anything other than the request method (e.g. an
    always-503 bug, or a bug that only fires on malformed bodies), this
    would be indistinguishable from the guard actually working. It also
    proves the guard isn't a blanket outage: GET keeps serving in the same
    breath.
    """

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        mutating = client.post(
            "/api/staff/live/recording-targets",
            json={
                "recording_target_id": "fs-primary",
                "name": "Primary recordings",
                "target_uri": (app_env / "recordings").as_uri(),
            },
            headers=_HEADERS,
        )
        assert mutating.status_code == 503
        assert mutating.json() == {"error": "maintenance"}

        read = client.get("/api/staff/schedule", headers=_HEADERS)
        assert read.status_code == 200

        health = client.get("/health")
        assert health.status_code == 200


def test_maintenance_mode_503s_egress_command_enqueue_route(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """positive: the egress command-enqueue surface (a POST under
    /api/staff/egress) is refused exactly like any other mutating route."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/staff/egress/channels/gov/commands",
            json={"action": "start"},
            headers=_HEADERS,
        )
        assert response.status_code == 503
        assert response.json() == {"error": "maintenance"}
