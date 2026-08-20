# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

"""The native station's front door: /operator/ and / must actually be served.

``civiccast/app.py``'s ``_mount_packaged_portals`` mounts the operator console
and the resident portal ONLY when ``CIVICCAST_OPERATOR_CONSOLE_DIST`` /
``CIVICCAST_PUBLIC_PORTAL_DIST`` are set, and ``_configured_static_dir``
returned ``None`` for an unset or missing directory. Nothing on a native
station ever set either variable (only the WSL ``headless-bootstrap.ps1``
did), so the control plane came up answering ``/health`` and 404ing both of
the surfaces the product is actually reached through -- with no log line
anywhere saying so. ``station_runtime`` now emits both (see
``tests/native/test_station_runtime.py``); these pin the consuming end.

Chain L (TESTER2 request-0050c) is the SECOND half of the same 404. Emitting
the variables was not enough, because the only thing that emitted them --
``load_native_station_environment`` -- fails closed on a station that is
installed but not yet ACTIVATED, and the supervisor's degrade for that state
handed the control-plane child a wholly EMPTY env. So a station that installed
cleanly, ran, and answered ``/health`` still 404'd ``/operator/``: the
compiled portals were on disk (they ship in the ``native-app-payload`` pack)
and nobody told the control plane where. These pin the producing end for that
state, and pin the served paths to the ``civiccast`` package's OWN location
rather than to arithmetic on a root.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import _configured_static_dir, create_app


def _write_portal(root: Path, name: str, body: str) -> Path:
    dist = root / name
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(body, encoding="utf-8")
    return dist


def _miniature_installed_station(root: Path) -> Path:
    """Lay the EXTRACT-shaped tree a real install actually produces, and
    return its embedded ``python.exe``.

    Extract-shaped, not wheel-shaped, on purpose. The verified delivery chain
    is: ``scripts/build_native_app_payload_pack.py`` packs the payload tree
    with pack-relative paths identical to their payload-root-relative paths;
    ``civiccast/apps/installer/src-tauri/src/native_packs.rs`` strips the
    ``payload/`` archive prefix on extraction; and
    ``native_pack_staging::pack_extraction_destination`` bridges the
    ``native-app-payload`` component to ``<INSTDIR>\\runtime`` (NOT the generic
    ``packs\\<component>\\payload\\`` convention). So on a real station the
    interpreter's own site-packages is ``<INSTDIR>\\runtime\\Lib\\
    site-packages`` and the compiled portals are inside the ``civiccast``
    package there.

    Deliberately NOT activated: no ``station-set.json``, no
    ``activation-self-test.json``, no caption model. That is exactly the state
    TESTER2's station was in (request-0050c: install PASS, service RUNNING,
    /health 200, first-run acquisition still downloading the caption engine)
    when ``/operator/`` answered 404.
    """

    package = root / "runtime" / "Lib" / "site-packages" / "civiccast"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for portal, body in (
        ("portal-operator", "<h1>Operator console</h1>"),
        ("portal-public", "<h1>Resident portal</h1>"),
    ):
        dist = package / "apps" / portal / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text(body, encoding="utf-8")
    python = root / "runtime" / "python.exe"
    python.write_bytes(b"")
    return python


def test_control_plane_serves_both_portals_when_the_station_env_points_at_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    operator = _write_portal(tmp_path, "portal-operator", "<h1>Operator console</h1>")
    public = _write_portal(tmp_path, "portal-public", "<h1>Resident portal</h1>")
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_DIST", str(operator))
    monkeypatch.setenv("CIVICCAST_PUBLIC_PORTAL_DIST", str(public))

    client = TestClient(create_app())

    operator_response = client.get("/operator/", headers={"accept": "text/html"})
    public_response = client.get("/", headers={"accept": "text/html"})

    assert operator_response.status_code == 200
    assert "Operator console" in operator_response.text
    assert public_response.status_code == 200
    assert "Resident portal" in public_response.text


def test_unknown_api_path_gets_a_json_404_not_the_spa_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W-5 (audit walkthrough): before the fix, a browser-style request
    (``Accept: text/html`` / ``*/*``, what real clients send) for an
    unmatched ``/api/*`` path fell through the ``/`` catch-all mount and was
    answered with the resident portal's ``index.html`` at status 200 -- an
    HTML document with no JSON body, for a caller that asked the API for a
    resource. This pins the fix: any path under ``/api`` that no router
    claims gets a genuine ``application/json`` 404 with a ``detail`` field,
    on both the default (``*/*``-ish TestClient) and explicit
    ``text/html`` Accept headers, and the SPA fallback keeps working for
    everything else (``/`` and ``/operator/`` still serve their shells; a
    non-API deep link like ``/watch/abc`` still falls back to index.html).
    """

    operator = _write_portal(tmp_path, "portal-operator", "<h1>Operator console</h1>")
    public = _write_portal(tmp_path, "portal-public", "<h1>Resident portal</h1>")
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_DIST", str(operator))
    monkeypatch.setenv("CIVICCAST_PUBLIC_PORTAL_DIST", str(public))

    client = TestClient(create_app())

    default_response = client.get("/api/does-not-exist")
    assert default_response.status_code == 404
    assert default_response.headers["content-type"].startswith("application/json")
    assert default_response.json() == {"detail": "Not Found"}

    html_accept_response = client.get(
        "/api/does-not-exist", headers={"accept": "text/html"}
    )
    assert html_accept_response.status_code == 404
    assert html_accept_response.headers["content-type"].startswith("application/json")
    assert html_accept_response.json() == {"detail": "Not Found"}

    bare_api_response = client.get("/api", headers={"accept": "text/html"})
    assert bare_api_response.status_code == 404
    assert bare_api_response.headers["content-type"].startswith("application/json")

    # Non-API paths are unaffected: the SPA shell still answers both the
    # mounted roots and an arbitrary client-side route deep link.
    operator_response = client.get("/operator/", headers={"accept": "text/html"})
    public_response = client.get("/", headers={"accept": "text/html"})
    deep_link_response = client.get("/watch/abc123", headers={"accept": "text/html"})
    assert operator_response.status_code == 200
    assert "Operator console" in operator_response.text
    assert public_response.status_code == 200
    assert "Resident portal" in public_response.text
    assert deep_link_response.status_code == 200
    assert "Resident portal" in deep_link_response.text


def test_a_freshly_installed_station_still_serves_its_operator_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """TESTER2 (request-0050c) reproduction, end to end at the HTTP layer.

    The supervisor's ``default_dependency_provider`` builds the control-plane
    child's env. On a station that is installed but not yet ACTIVATED it
    catches ``NativeStationNotActivatedError`` and hands the child an EMPTY
    env -- so ``CIVICCAST_OPERATOR_CONSOLE_DIST`` is never set at all and
    ``_mount_packaged_portals`` mounts nothing. The compiled portals, however,
    ship in the ``native-app-payload`` pack and are on disk from pack-staging
    time onward; nothing about serving them depends on activation.

    So: lay the real extract-shaped layout, ask the provider for the env the
    child would actually get, apply it, and hit the front door.
    """

    import civiccast

    root = tmp_path / "CivicCast"
    python = _miniature_installed_station(root)
    package_init = root / "runtime" / "Lib" / "site-packages" / "civiccast" / "__init__.py"

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(sys, "executable", str(python))
    # The running interpreter's OWN civiccast package is the installed one --
    # the source of truth the child's ``import civiccast`` will resolve to.
    monkeypatch.setattr(civiccast, "__file__", str(package_init))

    from civiccast.native.supervisor.service import default_dependency_provider

    child_env = default_dependency_provider().control_plane_env

    assert "CIVICCAST_OPERATOR_CONSOLE_DIST" in child_env, (
        "a station that is installed but not yet activated must still be told "
        "where its packaged operator console is"
    )
    assert Path(child_env["CIVICCAST_OPERATOR_CONSOLE_DIST"]).is_dir()
    assert Path(child_env["CIVICCAST_PUBLIC_PORTAL_DIST"]).is_dir()
    # Serving the front door must NOT claim the station is activated:
    # installer/service.py's _native_station_activated reads exactly this.
    assert "CIVICCAST_NATIVE_STATION" not in child_env

    for key, value in child_env.items():
        monkeypatch.setenv(key, value)

    client = TestClient(create_app())

    operator_response = client.get("/operator/", headers={"accept": "text/html"})
    assert operator_response.status_code == 200
    assert "Operator console" in operator_response.text


def test_the_packaged_portal_paths_resolve_on_the_real_extracted_layout(
    tmp_path: Path,
) -> None:
    """The served paths must be derived from the package the interpreter
    actually imports, and must EXIST on the layout a real install produces."""

    from civiccast.native.station_runtime import packaged_portal_environment

    root = tmp_path / "CivicCast"
    _miniature_installed_station(root)
    package_init = root / "runtime" / "Lib" / "site-packages" / "civiccast" / "__init__.py"

    env = packaged_portal_environment(package_file=package_init)

    operator = Path(env["CIVICCAST_OPERATOR_CONSOLE_DIST"])
    public = Path(env["CIVICCAST_PUBLIC_PORTAL_DIST"])
    assert operator.is_dir()
    assert public.is_dir()
    assert (operator / "index.html").is_file()
    assert (public / "index.html").is_file()


def test_a_missing_portal_build_directory_is_reported_at_error_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A configured-but-missing dist is a BROKEN install, not a routine
    warning: the station has been told where its front door is and it is not
    there. Reported at ERROR so it survives a default log level, while the app
    still starts (a control plane that answers /health with no console beats
    one that will not boot at all)."""

    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_DIST", str(tmp_path / "not-installed"))

    with caplog.at_level(logging.ERROR, logger="civiccast.app"):
        assert _configured_static_dir("CIVICCAST_OPERATOR_CONSOLE_DIST") is None

    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors, "a configured portal dist that does not exist must be reported at ERROR level"
    assert "CIVICCAST_OPERATOR_CONSOLE_DIST" in errors[0].getMessage()


def test_an_unset_portal_variable_is_reported_at_error_level_too(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The ORIGINAL silence: with the variable simply unset, the old code
    returned None with no log line at all, so a station that never mounted its
    operator console looked identical to a healthy one in the logs."""

    monkeypatch.delenv("CIVICCAST_OPERATOR_CONSOLE_DIST", raising=False)

    with caplog.at_level(logging.ERROR, logger="civiccast.app"):
        assert _configured_static_dir("CIVICCAST_OPERATOR_CONSOLE_DIST") is None

    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors, "an unset portal dist variable must not be silent"
    assert "CIVICCAST_OPERATOR_CONSOLE_DIST" in errors[0].getMessage()


def test_a_present_portal_directory_is_returned_without_complaint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    operator = _write_portal(tmp_path, "portal-operator", "<h1>Operator console</h1>")
    monkeypatch.setenv("CIVICCAST_OPERATOR_CONSOLE_DIST", str(operator))

    with caplog.at_level(logging.ERROR, logger="civiccast.app"):
        resolved = _configured_static_dir("CIVICCAST_OPERATOR_CONSOLE_DIST")

    assert resolved == str(operator.resolve())
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []
