# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""TSDuck-based headend compliance probe tests (cable automation CA-7).

The fixture ``fixtures/tsduck-analyze-clean-cbr.json`` is a REAL TSDuck
3.44 ``analyze --json`` report captured on this machine from a CA-6-shaped
stream (libx264 5 Mbps + AC-3 192k, ``-muxrate 8000k``, pkt_size=1316 over
UDP loopback) — the parser is pinned to the genuine shape, not a guess.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from civiccast.egress import compliance as compliance_mod
from civiccast.egress.compliance import (
    ComplianceProbeResult,
    TsduckStatus,
    build_compliance_probe_args,
    evaluate_tsduck_report,
    locate_tsduck,
    managed_tsduck_dir,
    probe_device,
    run_compliance_probe,
)
from civiccast.egress.models import EgressConfig, EgressSinkSpec

FIXTURE = Path(__file__).parent / "fixtures" / "tsduck-analyze-clean-cbr.json"


def _report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _headend_config(channel_id: str = "public") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[
            EgressSinkSpec(
                kind="udp-ts",
                label="Cable headend",
                uri="udp://239.255.0.1:5000",
                extra_output_args=["-muxrate", "8000k"],
            )
        ],
    )


def test_locate_tsduck_prefers_env_then_path(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = tmp_path / "tsp.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("CIVICCAST_TSDUCK_PATH", str(tmp_path))

    status = locate_tsduck(version_runner=lambda _path: "tsp: TSDuck ... version 3.44-4676")

    assert status.installed is True
    assert status.path == str(fake)
    assert "3.44" in (status.version or "")


def test_locate_tsduck_missing_is_honest(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("PATH", "")

    status = locate_tsduck()

    assert status.installed is False
    assert status.path is None
    assert "tsduck.io" in status.install_hint


def test_locate_tsduck_finds_managed_pull_install(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A CivicCast pull-on-demand install lands under CIVICCAST_TSDUCK_HOME and is
    # found without any CIVICCAST_TSDUCK_PATH / PATH wiring.
    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))
    managed_bin = tmp_path / "home" / "TSDuck" / "bin"
    managed_bin.mkdir(parents=True)
    fake = managed_bin / "tsp.exe"
    fake.write_bytes(b"")

    status = locate_tsduck(version_runner=lambda _path: "tsp: TSDuck ... version 3.44-4676")

    assert status.installed is True
    assert status.path == str(fake)
    assert "3.44" in (status.version or "")


def test_locate_tsduck_managed_beats_path(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))
    managed_bin = tmp_path / "home" / "TSDuck" / "bin"
    managed_bin.mkdir(parents=True)
    (managed_bin / "tsp.exe").write_bytes(b"")
    # A tsp also exists on PATH; the managed pull must take precedence.
    monkeypatch.setattr(
        compliance_mod.shutil, "which", lambda _name: str(tmp_path / "path" / "tsp.exe")
    )

    status = locate_tsduck(version_runner=lambda _p: "tsp version 3.44-4676")

    assert status.installed is True
    assert status.path == str(managed_bin / "tsp.exe")


def test_locate_tsduck_env_beats_managed(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    env_dir = tmp_path / "byo"
    env_dir.mkdir()
    (env_dir / "tsp.exe").write_bytes(b"")
    monkeypatch.setenv("CIVICCAST_TSDUCK_PATH", str(env_dir))
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))
    managed_bin = tmp_path / "home" / "TSDuck" / "bin"
    managed_bin.mkdir(parents=True)
    (managed_bin / "tsp.exe").write_bytes(b"")

    status = locate_tsduck(version_runner=lambda _p: "tsp version 3.44-4676")

    assert status.installed is True
    assert status.path == str(env_dir / "tsp.exe")


def test_locate_tsduck_non_runnable_is_not_installed(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))
    managed_bin = tmp_path / "home" / "TSDuck" / "bin"
    managed_bin.mkdir(parents=True)
    (managed_bin / "tsp.exe").write_bytes(b"")

    def explode(_path: str) -> str:
        raise OSError("not a valid executable")

    # A tsp that cannot run its --version is honestly NOT installed (no false-ready).
    assert locate_tsduck(version_runner=explode).installed is False
    # Empty version output is likewise treated as not-runnable.
    assert locate_tsduck(version_runner=lambda _p: "   ").installed is False


def test_locate_tsduck_finds_the_shipped_native_server_pack_tsp(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """Root cause of the Gate A "TSDuck (tsp) not found" log line even
    though tsp.exe genuinely shipped: locate_tsduck never looked at the
    native-server-binaries pack's own payload/tsduck/bin/tsp.exe. Simulates
    a real install by pointing sys.executable at
    <install_root>/runtime/pythonservice.exe (the same shape
    resolve_install_layout's own ground-truth tests use) with no
    CIVICCAST_TSDUCK_PATH, no managed pull-on-demand install, and nothing on
    PATH -- the shipped pack must still be found."""

    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))  # empty; no managed pull

    install_root = tmp_path / "install"
    exe = install_root / "runtime" / "pythonservice.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))

    shipped_bin = install_root / "packs" / "native-server-binaries" / "payload" / "tsduck" / "bin"
    shipped_bin.mkdir(parents=True)
    shipped_tsp = shipped_bin / "tsp.exe"
    shipped_tsp.write_bytes(b"")

    status = locate_tsduck(version_runner=lambda _path: "tsp: TSDuck ... version 3.44-4676")

    assert status.installed is True
    assert status.path == str(shipped_tsp)
    assert "3.44" in (status.version or "")


def test_locate_tsduck_managed_beats_shipped_pack(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The shipped pack is only a FALLBACK: an existing managed pull-on-demand
    install must still win, same precedence as it already has over PATH."""

    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))
    managed_bin = tmp_path / "home" / "TSDuck" / "bin"
    managed_bin.mkdir(parents=True)
    managed_tsp = managed_bin / "tsp.exe"
    managed_tsp.write_bytes(b"")

    install_root = tmp_path / "install"
    exe = install_root / "runtime" / "pythonservice.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    shipped_bin = install_root / "packs" / "native-server-binaries" / "payload" / "tsduck" / "bin"
    shipped_bin.mkdir(parents=True)
    (shipped_bin / "tsp.exe").write_bytes(b"")

    status = locate_tsduck(version_runner=lambda _p: "tsp version 3.44-4676")

    assert status.installed is True
    assert status.path == str(managed_tsp)


def test_locate_tsduck_shipped_pack_absent_falls_through_to_path(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """No CIVICCAST_TSDUCK_PATH, no managed install, no shipped pack on disk
    (e.g. a dev interpreter, not a real install) -- PATH is still checked,
    unchanged precedence/behavior for a BYO tsp on PATH."""

    monkeypatch.delenv("CIVICCAST_TSDUCK_PATH", raising=False)
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "home"))  # empty
    monkeypatch.setattr(sys, "executable", str(tmp_path / "dev-venv" / "python.exe"))
    on_path = tmp_path / "path" / "tsp.exe"
    on_path.parent.mkdir(parents=True)
    on_path.write_bytes(b"")
    monkeypatch.setattr(compliance_mod.shutil, "which", lambda _name: str(on_path))

    status = locate_tsduck(version_runner=lambda _p: "tsp version 3.44-4676")

    assert status.installed is True
    assert status.path == str(on_path)


def test_managed_tsduck_dir_env_override(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CIVICCAST_TSDUCK_HOME", str(tmp_path / "custom"))
    assert managed_tsduck_dir() == tmp_path / "custom"


@pytest.mark.skipif(
    os.name != "nt",
    reason="nt branch only; monkeypatching os.name='nt' breaks pathlib off Windows",
)
def test_managed_tsduck_dir_windows_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CIVICCAST_TSDUCK_HOME", raising=False)
    monkeypatch.setattr(compliance_mod.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    assert managed_tsduck_dir() == tmp_path / "AppData" / "Local" / "CivicCast" / "tsduck"


@pytest.mark.skipif(
    os.name == "nt",
    reason="XDG branch is non-Windows only; monkeypatching os.name='posix' breaks pathlib on Windows",
)
def test_managed_tsduck_dir_xdg_default(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CIVICCAST_TSDUCK_HOME", raising=False)
    monkeypatch.setattr(compliance_mod.os, "name", "posix")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert managed_tsduck_dir() == tmp_path / "xdg" / "civiccast" / "tsduck"


def test_probe_args_multicast_joins_group_and_unicast_binds_port(tmp_path: Path) -> None:
    report = tmp_path / "r.json"
    multicast = build_compliance_probe_args(
        destination_uri="udp://239.255.0.1:5000", seconds=10, json_report_path=report
    )
    # Verified against tsp 3.44 on this machine: the ip input takes the
    # group:port for multicast but binds the bare port for unicast
    # ("address ... is not multicast" otherwise).
    assert multicast[:3] == ["-I", "ip", "239.255.0.1:5000"]
    # A generous socket receive buffer follows the input spec so the bounded
    # live capture does not drop datagrams and invent continuity errors.
    assert multicast[3] == "--buffer-size"
    assert int(multicast[4]) >= 1_000_000
    assert multicast[5:9] == ["-P", "until", "--seconds", "10"]
    assert ["-P", "analyze", "--json", "--output-file", str(report)] == multicast[9:14]
    assert multicast[-2:] == ["-O", "drop"]

    unicast = build_compliance_probe_args(
        destination_uri="udp://10.0.0.9:5000", seconds=10, json_report_path=report
    )
    assert unicast[:3] == ["-I", "ip", "5000"]
    assert unicast[3] == "--buffer-size"


def test_probe_args_set_generous_receive_buffer_by_default(tmp_path: Path) -> None:
    """Regression for the 2026-06-13 soak false-RED: the probe must set a large
    SO_RCVBUF so a busy host does not drop UDP datagrams and report spurious
    continuity discontinuities on a clean stream."""
    args = build_compliance_probe_args(
        destination_uri="udp://10.0.0.9:5000", seconds=10, json_report_path=tmp_path / "r.json"
    )
    idx = args.index("--buffer-size")
    assert int(args[idx + 1]) >= 16 * 1024 * 1024


def test_probe_args_receive_buffer_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_TSDUCK_RCVBUF_BYTES", "33554432")
    args = build_compliance_probe_args(
        destination_uri="udp://10.0.0.9:5000", seconds=10, json_report_path=tmp_path / "r.json"
    )
    idx = args.index("--buffer-size")
    assert args[idx + 1] == "33554432"

    # A bogus value falls back to the safe default, never to a tiny buffer.
    monkeypatch.setenv("CIVICCAST_TSDUCK_RCVBUF_BYTES", "0")
    args = build_compliance_probe_args(
        destination_uri="udp://10.0.0.9:5000", seconds=10, json_report_path=tmp_path / "r.json"
    )
    idx = args.index("--buffer-size")
    assert int(args[idx + 1]) >= 16 * 1024 * 1024


def test_evaluate_clean_cbr_report_passes_every_check() -> None:
    result = evaluate_tsduck_report(_report(), expected_muxrate_kbps=8000)

    assert result.verdict == "pass"
    checks = {check.check: check for check in result.checks}
    assert checks["cbr-mux-rate"].status == "pass"
    # The real capture measured exactly 8,000,000 b/s against -muxrate 8000k.
    assert "8000000" in checks["cbr-mux-rate"].detail
    assert checks["ts-sync"].status == "pass"
    assert checks["continuity"].status == "pass"
    assert checks["pat-pmt"].status == "pass"
    assert checks["pcr-present"].status == "pass"
    assert checks["single-program"].status == "pass"


def test_evaluate_flags_bitrate_drift_and_continuity_errors() -> None:
    report = _report()
    report["ts"]["pcr-bitrate"] = 6_000_000  # far from 8 Mbps
    report["pids"][2]["packets"]["discontinuities"] = 41

    result = evaluate_tsduck_report(report, expected_muxrate_kbps=8000)

    assert result.verdict == "fail"
    checks = {check.check: check for check in result.checks}
    assert checks["cbr-mux-rate"].status == "fail"
    assert checks["continuity"].status == "fail"
    assert "41" in checks["continuity"].detail


def test_evaluate_flags_multi_program_and_missing_pcr() -> None:
    report = _report()
    report["ts"]["services"]["total"] = 2
    report["ts"]["pids"]["pcr"] = 0

    result = evaluate_tsduck_report(report, expected_muxrate_kbps=8000)

    checks = {check.check: check for check in result.checks}
    assert checks["single-program"].status == "fail"
    assert checks["pcr-present"].status == "fail"


def test_run_probe_writes_last_result_and_honest_not_claimed(tmp_path: Path) -> None:
    def fake_runner(args: list[str]) -> int:
        # The runner seam stands in for tsp: write the real fixture where
        # the args say the report goes.
        out = Path(args[args.index("--output-file") + 1])
        out.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        return 0

    result = run_compliance_probe(
        _headend_config(),
        seconds=10,
        work_dir=tmp_path,
        tsduck=TsduckStatus(installed=True, path="tsp", version="3.44", install_hint=""),
        runner=fake_runner,
    )

    assert result.verdict == "pass"
    assert result.channel_id == "public"
    assert result.destination == "udp://239.255.0.1:5000"
    assert any("TR 101 290" in line for line in result.not_claimed)
    assert any("field" in line.lower() for line in result.not_claimed)
    last = tmp_path / "public" / "compliance-last.json"
    assert last.exists()
    assert json.loads(last.read_text(encoding="utf-8"))["verdict"] == "pass"


def test_run_probe_without_tsduck_is_not_run_never_fake(tmp_path: Path) -> None:
    result = run_compliance_probe(
        _headend_config(),
        seconds=10,
        work_dir=tmp_path,
        tsduck=TsduckStatus(
            installed=False, path=None, version=None, install_hint="Install from tsduck.io"
        ),
        runner=lambda args: 0,
    )

    assert result.verdict == "not-run"
    assert "tsduck.io" in result.detail.lower() or "install" in result.detail.lower()


def test_run_probe_without_udp_ts_sink_raises(tmp_path: Path) -> None:
    config = EgressConfig(
        channel_id="public",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )
    with pytest.raises(ValueError, match="udp-ts"):
        run_compliance_probe(
            config,
            seconds=10,
            work_dir=tmp_path,
            tsduck=TsduckStatus(installed=True, path="tsp", version="3.44", install_hint=""),
            runner=lambda args: 0,
        )


def test_run_probe_runner_failure_is_a_fail_verdict(tmp_path: Path) -> None:
    result = run_compliance_probe(
        _headend_config(),
        seconds=10,
        work_dir=tmp_path,
        tsduck=TsduckStatus(installed=True, path="tsp", version="3.44", install_hint=""),
        runner=lambda args: 1,  # tsp exited nonzero, no report written
    )

    assert result.verdict == "fail"
    assert result.detail


def test_device_probe_reports_per_port_reachability() -> None:
    attempts: list[tuple[str, int]] = []

    def fake_connect(host: str, port: int, timeout_s: float) -> bool:
        attempts.append((host, port))
        return port == 443

    result = probe_device("headend.example", ports=[80, 443], connector=fake_connect)

    assert attempts == [("headend.example", 80), ("headend.example", 443)]
    assert result.host == "headend.example"
    reachable = {p.port: p.reachable for p in result.ports}
    assert reachable == {80: False, 443: True}
    assert result.any_reachable is True


def test_compliance_result_round_trips_json() -> None:
    result = evaluate_tsduck_report(_report(), expected_muxrate_kbps=8000)
    as_json = result.model_dump_json()
    assert ComplianceProbeResult.model_validate_json(as_json).verdict == result.verdict
