# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Prove the hermetic state fixture redirects, and that its guard fails closed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.support.hermetic_state import (
    REDIRECTED_ENV_VARS,
    changed_entries,
    hermetic_environment,
    real_state_roots,
    snapshot,
)


def test_every_redirected_variable_points_inside_tmp_path(tmp_path: Path) -> None:
    for name in REDIRECTED_ENV_VARS:
        value = os.environ.get(name)
        assert value, f"{name} should be set by the autouse hermetic fixture"
        assert Path(value).is_relative_to(tmp_path), f"{name}={value} escapes {tmp_path}"


def test_product_default_resolvers_land_under_tmp_path(tmp_path: Path) -> None:
    from civiccast.certs.readiness import default_cert_root
    from civiccast.egress.automation import default_egress_work_dir
    from civiccast.egress.compliance import managed_tsduck_dir
    from civiccast.installer.contribution_install import managed_contribution_dir
    from civiccast.installer.station_state import _default_storage_root, station_state_path
    from civiccast.installer.storage import default_storage_dir
    from civiccast.subscribe.secrets import _secret_file_path

    resolved = {
        "station_state_path": station_state_path(),
        "storage_root": _default_storage_root(),
        "managed_storage": default_storage_dir(),
        "egress_work_dir": default_egress_work_dir(),
        "tsduck_home": managed_tsduck_dir(),
        "contribution_home": managed_contribution_dir(),
        "cert_root": default_cert_root(),
        "subscribe_secrets": _secret_file_path(os.environ),
    }
    escaped = {name: path for name, path in resolved.items() if not path.is_relative_to(tmp_path)}
    assert escaped == {}, f"defaults still resolve outside tmp_path: {escaped}"


def test_hermetic_environment_is_self_consistent(tmp_path: Path) -> None:
    env = hermetic_environment(tmp_path)
    assert set(env) == set(REDIRECTED_ENV_VARS)
    for value in env.values():
        assert Path(value).is_relative_to(tmp_path)


def test_real_state_roots_come_from_the_given_environment() -> None:
    env = {
        "LOCALAPPDATA": r"C:\Users\op\AppData\Local",
        "USERPROFILE": r"C:\Users\op",
        "HOME": "/home/op",
        "XDG_DATA_HOME": "/home/op/.local/share",
    }
    roots = real_state_roots(env)
    assert Path(r"C:\Users\op\AppData\Local") / "CivicCast" in roots
    assert Path("/home/op/.local/share") / "civiccast" in roots
    home_root = (
        Path(r"C:\Users\op") / ".civiccast" if os.name == "nt" else Path("/home/op") / ".civiccast"
    )
    assert home_root in roots
    assert real_state_roots({}) == ()


def test_snapshot_diff_reports_create_modify_and_delete(tmp_path: Path) -> None:
    root = tmp_path / "real"
    root.mkdir()
    keep = root / "keep.txt"
    keep.write_text("same")
    doomed = root / "doomed.txt"
    doomed.write_text("bye")
    before = snapshot([root, tmp_path / "absent"])

    assert changed_entries(before, snapshot([root])) == []

    (root / "new.db").write_text("created")
    doomed.unlink()
    keep.write_text("rewritten, longer")
    after = snapshot([root])

    assert changed_entries(before, after) == sorted([str(root / "new.db"), str(doomed), str(keep)])


def test_guard_fails_a_test_that_writes_real_state(request: pytest.FixtureRequest) -> None:
    """End-to-end: an unmarked test writing under the real root fails at teardown.

    Runs a throwaway pytest session in a subprocess whose "real" profile is a
    directory under this test's tmp_path, using a verbatim copy of the root
    conftest, so the guard is exercised exactly as the suite installs it.
    """

    request.config.pluginmanager.import_plugin("pytester")
    pytester: pytest.Pytester = request.getfixturevalue("pytester")
    fake_profile = pytester.mkdir("fake-profile")
    fake_local = fake_profile / "AppData" / "Local"
    fake_local.mkdir(parents=True)
    pytester.makeconftest((Path(__file__).parent / "conftest.py").read_text(encoding="utf-8"))
    pytester.makepyfile(
        test_offender=f"""
        import os
        from pathlib import Path

        def test_writes_into_the_real_profile():
            real = Path({str(fake_local)!r}) / "CivicCast"
            real.mkdir(parents=True, exist_ok=True)
            (real / "civiccast.sqlite3").write_text("oops")

        def test_writes_into_tmp_path(tmp_path):
            (Path(os.environ["LOCALAPPDATA"]) / "CivicCast").mkdir(parents=True)
            assert Path(os.environ["LOCALAPPDATA"]).is_relative_to(tmp_path)
        """
    )
    env_override = {"LOCALAPPDATA": str(fake_local)}
    if os.name == "nt":
        env_override["USERPROFILE"] = str(fake_profile)
    else:
        env_override["HOME"] = str(fake_profile)
    env_override["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = _run_with_env(pytester, env_override)
    # The offender's call phase passes; the guard fires at teardown, which pytest
    # reports as an error on that same test -- so 2 passed AND 1 error.
    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(
        ["*touched the operator's real CivicCast state*", "*civiccast.sqlite3*"]
    )


def _run_with_env(pytester: pytest.Pytester, env: dict[str, str]) -> pytest.RunResult:
    """``runpytest_subprocess`` has no env argument; the child inherits the parent's."""

    saved = {name: os.environ.get(name) for name in env}
    os.environ.update(env)
    try:
        return pytester.runpytest_subprocess(
            "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "no:mutmut", "-c", os.devnull, "-q"
        )
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
