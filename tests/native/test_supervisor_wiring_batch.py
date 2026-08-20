# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Supervisor wiring batch (audit findings A1-A6, 2026-07-31).

Grounded in INSTALLER truth, not in what the supervisor code happened to do:

* pg_ctl.exe lives at ``<INSTDIR>\\packs\\native-server-binaries\\payload\\bin\\
  pg_ctl.exe`` and nats-server.exe beside it (scripts/build_native_server_pack.py
  payload manifest; provision/__main__.py resolves ``initdb_path`` under the same
  ``payload\\bin`` convention).
* The postgres cluster is ``%PROGRAMDATA%\\CivicCast\\data\\pgdata`` and the
  provisioned NATS config (JetStream store at ``...\\data\\nats-store``) is
  ``%PROGRAMDATA%\\CivicCast\\config\\nats-server.conf``
  (provision/__main__.py:resolve_provision_paths).
* The service host is ``<INSTDIR>\\runtime\\pythonservice.exe`` running as
  LocalSystem with CWD System32 and a stock PATH -- the installer writes NO PATH
  changes, so every bare/relative child path is a FileNotFoundError or resolves
  against System32.

Each test here FAILED at HEAD 1ec943b0 before the fix it pins (run first at
HEAD; see the worker report), except the explicitly-marked regression pins.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from civiccast.native.models import GuardDecision
from civiccast.native.runtime_guard import GuardMonitorStatus
from civiccast.native.supervisor.config import SupervisorConfig
from civiccast.native.supervisor.core import Supervisor

_WINDOWS_PATH_TEST = pytest.mark.skipif(
    os.name != "nt", reason="requires native Windows path semantics"
)

# ---------------------------------------------------------------------------
# Shared fakes (no Win32, no subprocess, no socket)
# ---------------------------------------------------------------------------


@dataclass
class FakeHandle:
    pid: int
    kind: str = "argv"


@dataclass
class FakeCoreRunner:
    """core.ChildProcessRunner fake (mirrors test_supervisor_core's)."""

    spawned: list = field(default_factory=list)
    ctrl_break_pids: list[int] = field(default_factory=list)
    terminated_pids: list[int] = field(default_factory=list)
    opened_existing_pids: list[int] = field(default_factory=list)
    alive: dict[int, bool] = field(default_factory=dict)
    _next_pid: int = 1000

    def spawn(self, spec) -> FakeHandle:
        self._next_pid += 1
        self.spawned.append(spec)
        self.alive[self._next_pid] = True
        return FakeHandle(pid=self._next_pid)

    def open_existing(self, pid: int) -> FakeHandle:
        self.opened_existing_pids.append(pid)
        self.alive[pid] = True
        return FakeHandle(pid=pid)

    def is_alive(self, handle: FakeHandle) -> bool:
        return self.alive.get(handle.pid, False)

    def send_ctrl_break(self, handle: FakeHandle) -> None:
        self.ctrl_break_pids.append(handle.pid)

    def terminate(self, handle: FakeHandle) -> None:
        self.terminated_pids.append(handle.pid)
        self.alive[handle.pid] = False

    def graceful_stop(self, handle: FakeHandle) -> object:
        # Structural parity with the ChildProcessRunner seam (postmaster
        # containment-rollback path); these suites never drive that path.
        self.alive[handle.pid] = False
        return "argv"

    @property
    def spawned_names(self) -> list[str]:
        return [spec.name for spec in self.spawned]


class FakeGuard:
    def __init__(self, decision: GuardDecision) -> None:
        self.decision = decision
        self.status = GuardMonitorStatus(last_decision=decision)
        self.pre_child_start_calls = 0
        self.evaluate_once_calls = 0

    def pre_child_start(self) -> GuardDecision:
        self.pre_child_start_calls += 1
        return self.decision

    def evaluate_once(self) -> GuardDecision:
        self.evaluate_once_calls += 1
        self.status.last_decision = self.decision
        return self.decision


@dataclass
class FakeOutbox:
    fired: list[dict[str, str]] = field(default_factory=list)

    def fire(self, *, summary: str, detail: str) -> None:
        self.fired.append({"summary": summary, "detail": detail})


class FakeJobApi:
    def __init__(self) -> None:
        self.assigned_pids: list[int] = []

    def create_job(self, name: str) -> object:
        return object()

    def configure_kill_on_close_no_breakaway(self, handle: object) -> None:
        return None

    def assign_process(self, handle: object, pid: int) -> None:
        self.assigned_pids.append(pid)

    def is_process_in_job(self, handle: object, pid: int) -> bool:
        return pid in self.assigned_pids

    def is_process_in_any_job(self, pid: int) -> bool:
        return pid in getattr(self, "any_job_pids", set())

    def close_job(self, handle: object) -> None:
        return None

    def open_existing_job(self, name: str) -> object | None:
        return None

    def list_job_process_ids(self, handle: object) -> list[int]:
        return []

    def terminate_job(self, handle: object, exit_code: int) -> None:
        return None


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


def guard_decision(action: str, state_name: str | None) -> GuardDecision:
    return GuardDecision(
        action=action,  # type: ignore[arg-type]
        named_probe=None,
        message=f"test decision action={action} state_name={state_name}",
        retry_seconds=10 if action == "blocked_probe_unavailable" else None,
        state_name=state_name,
    )


def _fresh_postmaster_pid_reader(start: int = 90000) -> Callable[[], int | None]:
    counter = {"n": start}

    def reader() -> int | None:
        counter["n"] += 1
        return counter["n"]

    return reader


def make_core_supervisor(
    *,
    guard: FakeGuard | None = None,
    runner: FakeCoreRunner | None = None,
) -> tuple[Supervisor, FakeCoreRunner, FakeGuard]:
    from civiccast.native.supervisor.children import ControlPlaneHealthProbe

    guard = guard or FakeGuard(guard_decision("start", None))
    runner = runner or FakeCoreRunner()
    clock = FakeClock()
    sup = Supervisor(
        config=SupervisorConfig(),
        guard=guard,
        job_api=FakeJobApi(),
        runner=runner,
        alert_outbox=FakeOutbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: ControlPlaneHealthProbe(status_code=200, mode="normal"),
        clock=clock.now,
        sleep=clock.sleep,
        interlock_reader=lambda: "free",  # type: ignore[arg-type,return-value]
        rng=lambda: 0.5,
        postmaster_pid_reader=_fresh_postmaster_pid_reader(),
        program_data_root=r"C:\ProgramData",
        postgres_data_dir="pgdata",
    )
    return sup, runner, guard


# ---------------------------------------------------------------------------
# Layout fixture: the EXACT installed shape (installer ground truth above)
# ---------------------------------------------------------------------------


def _make_install_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Create <install_root> and <programdata root> mimicking a real install."""

    install_root = tmp_path / "Program Files" / "CivicCast (Native)"
    (install_root / "runtime").mkdir(parents=True)
    (install_root / "runtime" / "python.exe").write_bytes(b"")
    (install_root / "runtime" / "pythonservice.exe").write_bytes(b"")
    bin_dir = install_root / "packs" / "native-server-binaries" / "payload" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "pg_ctl.exe").write_bytes(b"")
    (bin_dir / "nats-server.exe").write_bytes(b"")

    pd_root = tmp_path / "ProgramData"
    (pd_root / "CivicCast" / "data" / "pgdata").mkdir(parents=True)
    (pd_root / "CivicCast" / "config").mkdir(parents=True)
    (pd_root / "CivicCast" / "config" / "nats-server.conf").write_text(
        'port: 4222\njetstream {\n  store_dir: "..."\n}\n', encoding="utf-8"
    )
    (pd_root / "CivicCast" / "logs").mkdir(parents=True)
    return install_root, pd_root


class _WiringGuard:
    status = GuardMonitorStatus(last_decision=None)


class _WiringOutbox:
    def fire(self, *, summary: str, detail: str) -> None:
        pass


def _build_service(layout=None, program_data_root: str | None = None):
    from civiccast.native.supervisor.service import build_production_service

    kwargs: dict[str, object] = {}
    if layout is not None:
        kwargs["layout"] = layout
    if program_data_root is not None:
        kwargs["program_data_root"] = program_data_root
    return build_production_service(
        logging.getLogger("test.wiring.batch"),
        guard=_WiringGuard(),  # type: ignore[arg-type]
        alert_outbox=_WiringOutbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: pytest.fail("probe must not run at wiring time"),  # type: ignore[arg-type,return-value]
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# A1 -- install_layout: the single source of truth for installed paths
# ---------------------------------------------------------------------------


def test_resolve_install_layout_matches_installer_ground_truth(tmp_path: Path) -> None:
    """Every layout path matches the verified installer conventions, resolved
    from the service host executable + the ProgramData root, all absolute."""

    from civiccast.native.supervisor.install_layout import resolve_install_layout

    install_root, pd_root = _make_install_tree(tmp_path)
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )

    assert layout.install_root == install_root
    assert layout.python_path == install_root / "runtime" / "python.exe"
    bin_dir = install_root / "packs" / "native-server-binaries" / "payload" / "bin"
    assert layout.server_bin_dir == bin_dir
    assert layout.pg_ctl_path == bin_dir / "pg_ctl.exe"
    assert layout.nats_server_path == bin_dir / "nats-server.exe"
    assert layout.postgres_data_dir == pd_root / "CivicCast" / "data" / "pgdata"
    assert layout.nats_config_path == pd_root / "CivicCast" / "config" / "nats-server.conf"
    assert layout.log_root == pd_root / "CivicCast" / "logs"
    # ffmpeg/ffprobe: native_activation.rs's validate_staged_runtime_layout
    # pins dependencies/ffmpeg/bin/ffmpeg.exe as a required staged file.
    ffmpeg_bin_dir = install_root / "dependencies" / "ffmpeg" / "bin"
    assert layout.ffmpeg_bin_dir == ffmpeg_bin_dir
    assert layout.ffmpeg_exe_path == ffmpeg_bin_dir / "ffmpeg.exe"
    assert layout.ffprobe_exe_path == ffmpeg_bin_dir / "ffprobe.exe"
    # Operator media: beside data\egress and data\nats-store, plain mkdir,
    # inherited DACL (not the PROTECTED SDDL credential-state-root posture).
    assert layout.upload_dir == pd_root / "CivicCast" / "data" / "uploads"
    for p in (
        layout.install_root,
        layout.python_path,
        layout.pg_ctl_path,
        layout.nats_server_path,
        layout.postgres_data_dir,
        layout.nats_config_path,
        layout.log_root,
        layout.ffmpeg_bin_dir,
        layout.ffmpeg_exe_path,
        layout.ffprobe_exe_path,
        layout.upload_dir,
    ):
        assert Path(p).is_absolute(), p


def test_resolve_install_layout_honors_programdata_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ProgramData side honors %PROGRAMDATA% (service.py:168 previously
    hardcoded C:\\ProgramData for the log root -- the divergence this closes)."""

    from civiccast.native.supervisor.install_layout import resolve_install_layout

    install_root, pd_root = _make_install_tree(tmp_path)
    monkeypatch.setenv("PROGRAMDATA", str(pd_root))
    layout = resolve_install_layout(executable=install_root / "runtime" / "python.exe")

    assert layout.postgres_data_dir == pd_root / "CivicCast" / "data" / "pgdata"
    assert layout.log_root == pd_root / "CivicCast" / "logs"


def test_build_production_service_emits_absolute_existing_layout_specs(
    tmp_path: Path,
) -> None:
    """A1 BLOCKER: the PRODUCTION builder must emit ONLY absolute installed-layout
    paths for every child spec, the stop-command specs, and the postmaster pid
    reader -- under LocalSystem (CWD System32, stock PATH) the HEAD wiring's bare
    ``pg_ctl``/``nats-server``/``python`` and relative ``pgdata`` are
    FileNotFoundError / System32-relative."""

    from civiccast.native.supervisor.install_layout import resolve_install_layout

    install_root, pd_root = _make_install_tree(tmp_path)
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )
    service = _build_service(layout=layout, program_data_root=str(pd_root))
    sup = service._supervisor

    pg = sup._spec_for("postgres")
    assert pg.argv[0] == str(layout.pg_ctl_path)
    assert pg.argv[pg.argv.index("-D") + 1] == str(layout.postgres_data_dir)

    nats = sup._spec_for("nats")
    assert nats.argv[0] == str(layout.nats_server_path)
    # The provisioned config (JetStream store) MUST be passed to the nats child;
    # HEAD spawned it with nats_config_path=None (no -c at all).
    assert "-c" in nats.argv
    assert nats.argv[nats.argv.index("-c") + 1] == str(layout.nats_config_path)

    cp = sup._spec_for("control_plane")
    assert cp.argv[0] == str(layout.python_path)

    # Stop-command specs are absolute too (the runner's postgres stop spec).
    stop_template = service._runner._postgres_stop_spec.graceful_stop_argv_template
    assert stop_template[0] == str(layout.pg_ctl_path)
    assert stop_template[stop_template.index("-D") + 1] == str(layout.postgres_data_dir)

    # read_postmaster_pid targets the ABSOLUTE cluster dir, not CWD-relative pgdata.
    (layout.postgres_data_dir / "postmaster.pid").write_text("4242\n", encoding="utf-8")
    assert sup._postmaster_pid_reader() == 4242


def test_build_production_service_resolves_layout_from_sys_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an injected layout the builder resolves from sys.executable +
    %PROGRAMDATA% -- the real SvcDoRun path under pythonservice.exe."""

    install_root, pd_root = _make_install_tree(tmp_path)
    monkeypatch.setattr(sys, "executable", str(install_root / "runtime" / "pythonservice.exe"))
    monkeypatch.setenv("PROGRAMDATA", str(pd_root))

    service = _build_service()
    sup = service._supervisor

    pg = sup._spec_for("postgres")
    bin_dir = install_root / "packs" / "native-server-binaries" / "payload" / "bin"
    assert pg.argv[0] == str(bin_dir / "pg_ctl.exe")
    assert pg.argv[pg.argv.index("-D") + 1] == str(pd_root / "CivicCast" / "data" / "pgdata")
    nats = sup._spec_for("nats")
    assert nats.argv[0] == str(bin_dir / "nats-server.exe")
    cp = sup._spec_for("control_plane")
    assert cp.argv[0] == str(install_root / "runtime" / "python.exe")


def test_log_root_honors_programdata_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """service.py's log root must honor %PROGRAMDATA% (HEAD hardcoded
    C:\\ProgramData at service.py:168)."""

    from civiccast.native.supervisor.service import child_log_path, configure_logging

    pd_root = tmp_path / "PD"
    monkeypatch.setenv("PROGRAMDATA", str(pd_root))

    logger = configure_logging()
    try:
        assert (pd_root / "CivicCast" / "logs" / "supervisor.log").exists()
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    assert child_log_path("postgres") == pd_root / "CivicCast" / "logs" / "postgres.log"


# ---------------------------------------------------------------------------
# A7 -- media wiring: the control-plane child's only working on-air path (the
# installer rehearsal flow) needs CIVICCAST_UPLOAD_DIR set and ffmpeg/ffprobe
# resolvable off a stock LocalSystem PATH the installer never modifies.
# ---------------------------------------------------------------------------


def _stage_ffmpeg(install_root: Path) -> Path:
    """Stage ffmpeg.exe + ffprobe.exe at the ``native_activation.rs``-pinned
    ``dependencies\\ffmpeg\\bin`` convention. Returns the bin dir."""

    bin_dir = install_root / "dependencies" / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffmpeg.exe").write_bytes(b"")
    (bin_dir / "ffprobe.exe").write_bytes(b"")
    return bin_dir


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_build_control_plane_media_env_prepends_ffmpeg_dir_and_preserves_inherited_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CRITICAL detail: _file_backed_popen_factory composes env as
    ``{**os.environ, **spec.env}`` -- a bare PATH key in spec.env REPLACES
    the inherited PATH rather than extending it. build_control_plane_media_env
    must therefore return the FULL prepended string (ffmpeg dir + os.pathsep +
    the inherited PATH), never a bare directory."""

    from civiccast.native.supervisor.install_layout import resolve_install_layout
    from civiccast.native.supervisor.service import build_control_plane_media_env

    install_root, pd_root = _make_install_tree(tmp_path)
    ffmpeg_bin_dir = _stage_ffmpeg(install_root)
    monkeypatch.setenv("PATH", r"C:\Windows\System32;C:\Windows")
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )

    media_env = build_control_plane_media_env(layout)

    assert media_env["PATH"] == f"{ffmpeg_bin_dir};C:\\Windows\\System32;C:\\Windows"
    # The inherited PATH survives INTACT, not replaced.
    assert r"C:\Windows\System32" in media_env["PATH"]
    assert r"C:\Windows" in media_env["PATH"]


def test_build_control_plane_media_env_skips_and_logs_once_without_both_binaries(
    tmp_path: Path,
) -> None:
    """Missing ffmpeg or ffprobe -> an EMPTY dict (never raises) plus exactly
    one log line naming the missing directory -- mirrors
    build_ollama_spec_provider's skip pattern."""

    import logging

    from civiccast.native.supervisor.install_layout import resolve_install_layout
    from civiccast.native.supervisor.service import build_control_plane_media_env

    install_root, pd_root = _make_install_tree(tmp_path)
    # ffmpeg.exe present, ffprobe.exe absent -- still a skip (BOTH required).
    bin_dir = install_root / "dependencies" / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffmpeg.exe").write_bytes(b"")
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    logger = logging.getLogger("test.media_env.skip")
    logger.addHandler(_Capture())
    logger.setLevel(logging.DEBUG)

    media_env = build_control_plane_media_env(layout, logger=logger)

    assert media_env == {}
    assert len(records) == 1, "one clear line, not one per call"
    assert str(layout.ffmpeg_bin_dir) in records[0]


def test_build_control_plane_media_env_skips_with_neither_binary(tmp_path: Path) -> None:
    from civiccast.native.supervisor.install_layout import resolve_install_layout
    from civiccast.native.supervisor.service import build_control_plane_media_env

    install_root, pd_root = _make_install_tree(tmp_path)
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )

    assert build_control_plane_media_env(layout) == {}


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_build_production_service_merges_ffmpeg_path_into_control_plane_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: when both binaries are staged, the control-plane child spec
    actually carries the ffmpeg-prepended PATH, and CIVICCAST_UPLOAD_DIR (set
    unconditionally by children.control_plane_child_spec) resolves under the
    fabricated ProgramData root.

    NOTE (finding, not a red herring): unlike CIVICCAST_EGRESS_WORK_DIR --
    which core.Supervisor._spec_for threads through explicitly
    (``default_egress_work_dir(program_data_root=self._program_data_root)``)
    -- control_plane_child_spec's ``upload_dir`` param is never passed by
    _spec_for (out of this package's file scope), so CIVICCAST_UPLOAD_DIR
    always resolves via default_upload_dir()'s OWN %PROGRAMDATA% env-var
    read, not the ``program_data_root`` kwarg threaded elsewhere in this
    build. This is safe in PRODUCTION only because
    ``service.default_dependency_provider`` derives BOTH values from the
    exact same ``os.environ.get("PROGRAMDATA", ...)`` read, so they can never
    diverge there -- but it means a caller who explicitly passes a
    ``program_data_root`` that differs from the real %PROGRAMDATA% env var
    (as this test does) gets an upload dir resolved against the REAL env var,
    not the caller's override. Monkeypatching PROGRAMDATA here mirrors that
    production invariant rather than papering over it.
    """

    from civiccast.native.supervisor.install_layout import resolve_install_layout

    install_root, pd_root = _make_install_tree(tmp_path)
    ffmpeg_bin_dir = _stage_ffmpeg(install_root)
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.setenv("PROGRAMDATA", str(pd_root))
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )
    service = _build_service(layout=layout, program_data_root=str(pd_root))
    sup = service._supervisor

    cp = sup._spec_for("control_plane")
    assert cp.env["PATH"].startswith(str(ffmpeg_bin_dir))
    assert r"C:\Windows\System32" in cp.env["PATH"]
    assert cp.env["CIVICCAST_UPLOAD_DIR"] == str(pd_root / "CivicCast" / "data" / "uploads")

    cp_maintenance = sup._spec_for("control_plane", maintenance=True)
    assert cp_maintenance.env["PATH"].startswith(str(ffmpeg_bin_dir))
    assert cp_maintenance.env["CIVICCAST_UPLOAD_DIR"] == str(
        pd_root / "CivicCast" / "data" / "uploads"
    )


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_build_production_service_leaves_control_plane_path_untouched_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without staged ffmpeg/ffprobe, build_production_service must not inject
    ANY PATH key -- degraded media handling, never a crash, never a bare
    directory clobbering whatever PATH the caller's control_plane_env (or the
    inherited environment) would otherwise carry."""

    from civiccast.native.supervisor.install_layout import resolve_install_layout

    install_root, pd_root = _make_install_tree(tmp_path)
    monkeypatch.setenv("PROGRAMDATA", str(pd_root))
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )
    service = _build_service(layout=layout, program_data_root=str(pd_root))
    sup = service._supervisor

    cp = sup._spec_for("control_plane")
    assert "PATH" not in cp.env
    # CIVICCAST_UPLOAD_DIR is unconditional -- set regardless of ffmpeg staging.
    assert cp.env["CIVICCAST_UPLOAD_DIR"] == str(pd_root / "CivicCast" / "data" / "uploads")


def test_build_production_service_does_not_create_the_upload_dir(tmp_path: Path) -> None:
    """INVESTIGATION FINDING: build_production_service is PURE wiring with NO
    real filesystem I/O -- test_build_production_service_wires_program_data_root_for_egress_workdir
    and test_build_production_service_factory_assembles_deps_and_calls_build
    (this same test module's file) both pin that invariant with a
    deliberately nonexistent ``Z:\\`` drive, and an early version of this
    change's eager ``layout.upload_dir.mkdir(...)`` broke both. The upload
    dir gets the SAME non-treatment ``CIVICCAST_EGRESS_WORK_DIR`` already
    gets: the supervisor sets the env var (children.control_plane_child_spec,
    unconditionally) but never touches the directory itself.
    civiccast/egress/automation.py's build_channel_automation creates the
    egress dir lazily, INSIDE the control-plane child process, at actual app
    startup (``resolved_work_dir.mkdir(parents=True, exist_ok=True)``); the
    upload dir's equivalent app-side creation already exists too
    (civiccast/schedule/router.py's ``incoming_dir.mkdir(parents=True,
    exist_ok=True)`` at upload time -- ``parents=True`` creates the base dir
    as a side effect). "Follow that same mechanism" means follow it
    completely, including the "supervisor never touches this path" half."""

    from civiccast.native.supervisor.install_layout import resolve_install_layout

    install_root, pd_root = _make_install_tree(tmp_path)
    layout = resolve_install_layout(
        executable=install_root / "runtime" / "pythonservice.exe",
        program_data_root=pd_root,
    )
    assert not layout.upload_dir.exists()

    _build_service(layout=layout, program_data_root=str(pd_root))

    assert not layout.upload_dir.exists(), (
        "build_production_service must never touch the filesystem for the "
        "upload dir -- same posture as the egress work dir"
    )


# ---------------------------------------------------------------------------
# A2 -- pre-activation station gate must not kill the service
# ---------------------------------------------------------------------------


def _station_not_activated_error_type():
    """Worker B (station_runtime.py) introduces NativeStationNotActivatedError
    (subclassing NativeStationConfigurationError). Code against that name; until
    B's change lands in this tree, install an equivalent stub on the module so
    the provider's catch is exercised against the contract name."""

    import civiccast.native.station_runtime as station_runtime

    existing = getattr(station_runtime, "NativeStationNotActivatedError", None)
    if existing is not None:
        return existing, False

    class NativeStationNotActivatedError(station_runtime.NativeStationConfigurationError):
        pass

    return NativeStationNotActivatedError, True


def _fake_runtime_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = tmp_path / "inst" / "runtime"
    runtime.mkdir(parents=True)
    exe = runtime / "pythonservice.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))


def test_provider_pre_activation_station_starts_in_pre_activation_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2 BLOCKER: on a fresh (installed-but-not-activated) station the provider
    must catch NativeStationNotActivatedError, log, and proceed WITHOUT the
    ACTIVATED station env overlay -- HEAD propagated it out of SvcDoRun and the
    service died on every fresh install.

    Chain L (TESTER2 request-0050c) narrows what "without" means. The degrade
    used to hand the child a completely EMPTY env, which also threw away the
    packaged portal paths and the setup nonce -- neither of which depends on
    activation (the portals arrive with the native-app-payload pack; the nonce
    is persisted at D4 provision time). That is why a station that installed
    cleanly, ran, and answered /health still 404'd /operator/. The overlay must
    now carry those and STILL withhold every activated-station marker."""

    import civiccast.native.station_runtime as station_runtime

    exc_type, stubbed = _station_not_activated_error_type()
    if stubbed:
        monkeypatch.setattr(
            station_runtime, "NativeStationNotActivatedError", exc_type, raising=False
        )

    def raising_env(python_path, *, program_data_root=None):
        raise exc_type("station-set.json is missing (not yet activated)")

    monkeypatch.setattr(station_runtime, "station_environment_for_python", raising_env)
    monkeypatch.setattr(station_runtime, "read_persisted_setup_nonce", lambda: "nonce-from-d4")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    _fake_runtime_python(tmp_path, monkeypatch)

    from civiccast.native.supervisor.service import default_dependency_provider

    deps = default_dependency_provider()  # must NOT raise

    assert deps.control_plane_env["CIVICCAST_OPERATOR_CONSOLE_DIST"]
    assert deps.control_plane_env["CIVICCAST_PUBLIC_PORTAL_DIST"]
    assert deps.control_plane_env["CIVICCAST_SETUP_NONCE"] == "nonce-from-d4"
    # No activated-station markers, and none of the captions/GStreamer wiring
    # that genuinely does require an activated station.
    assert "CIVICCAST_NATIVE_STATION" not in deps.control_plane_env
    assert "CIVICCAST_NATIVE_STATION_MANIFEST" not in deps.control_plane_env
    assert "CIVICCAST_WHISPER_MODEL_PATH" not in deps.control_plane_env


def test_provider_corrupt_station_config_still_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression pin (passes at HEAD too): a CORRUPT activated station
    (NativeStationConfigurationError that is NOT the not-activated subclass)
    must still fail loudly -- the pre-activation catch must be narrow."""

    import civiccast.native.station_runtime as station_runtime

    def raising_env(python_path, *, program_data_root=None):
        raise station_runtime.NativeStationConfigurationError("activation receipt tampered")

    monkeypatch.setattr(station_runtime, "station_environment_for_python", raising_env)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    _fake_runtime_python(tmp_path, monkeypatch)

    from civiccast.native.supervisor.service import default_dependency_provider

    with pytest.raises(station_runtime.NativeStationConfigurationError):
        default_dependency_provider()


def test_provider_program_data_root_resolves_single_civiccast_egress_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider's program_data_root feeds children.default_egress_work_dir,
    which appends \\CivicCast\\data\\egress ITSELF -- HEAD passed
    <pd>\\CivicCast and produced <pd>\\CivicCast\\CivicCast\\data\\egress."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")

    from civiccast.native.supervisor.children import default_egress_work_dir
    from civiccast.native.supervisor.service import default_dependency_provider

    deps = default_dependency_provider()
    egress = default_egress_work_dir(program_data_root=deps.program_data_root)

    assert egress == r"C:\ProgramData\CivicCast\data\egress"
    assert egress.count("CivicCast") == 1


# ---------------------------------------------------------------------------
# A3 -- a guard-blocked start must stay retryable and visible
# ---------------------------------------------------------------------------


def test_boot_guard_blocked_control_plane_is_retried_and_recovers() -> None:
    """A3: a guard-blocked boot start left control_plane 'stopped' at HEAD;
    _needs_restart never retries 'stopped', so the supervisor sat RUNNING
    forever with a dead station. The blocked start must remain retryable on the
    tick loop and recover once the guard clears."""

    guard = FakeGuard(guard_decision("refuse", None))  # non-start verdict at boot
    sup, runner, guard = make_core_supervisor(guard=guard)

    sup.start()
    assert sup.state == "starting"
    assert "control_plane" not in runner.spawned_names
    # Retryable -- NOT the deliberately-down 'stopped' that _needs_restart skips.
    assert sup.child_state("control_plane") != "stopped"

    # Blocked ticks keep retrying (withheld, nothing spawned) without wedging.
    sup.tick(now=1.0)
    assert "control_plane" not in runner.spawned_names
    assert sup.state == "starting"

    # The guard clears -> a later tick brings the control plane up to serving.
    guard.decision = guard_decision("start", None)
    sup.tick(now=2.0)
    assert sup.state == "ready"
    assert runner.spawned_names.count("control_plane") == 1


def test_guard_blocked_start_is_visible_in_status_snapshot() -> None:
    """A3: the blocked start must be visible in the supervisor's status output
    (the control pipe's ``status`` read tier), not silent."""

    guard = FakeGuard(guard_decision("refuse", None))
    sup, _runner, guard = make_core_supervisor(guard=guard)
    sup.start()

    snap = sup.status_snapshot()
    cp = next(c for c in snap.children if c.name == "control_plane")
    assert cp.blocked_detail is not None
    assert "guard" in cp.blocked_detail

    # And it CLEARS once the start succeeds.
    guard.decision = guard_decision("start", None)
    sup.tick(now=2.0)
    snap = sup.status_snapshot()
    cp = next(c for c in snap.children if c.name == "control_plane")
    assert cp.blocked_detail is None


# ---------------------------------------------------------------------------
# A4 -- alerting must never kill the supervisor
# ---------------------------------------------------------------------------


def test_alerting_outbox_fire_never_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4: an alert INSERT failing (schema-less/degraded DB) must be logged and
    swallowed -- at HEAD it propagated tick -> run -> SvcDoRun and crashed the
    service exactly when an alert mattered."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    import civiccast.alerting.store as store_mod

    def raising_record(session, **kwargs):
        raise RuntimeError("no such table: alert_conditions")

    monkeypatch.setattr(store_mod, "record_alert_condition", raising_record)

    from civiccast.native.supervisor.service import default_dependency_provider

    deps = default_dependency_provider()
    deps.alert_outbox.fire(summary="restart storm", detail="boom")  # must NOT raise


def test_alerting_outbox_session_factory_failure_never_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4: even opening the Session can fail on a degraded DB -- still contained."""

    from civiccast.native.supervisor.service import _AlertingOutbox

    def broken_factory():
        raise RuntimeError("connection refused")

    outbox = _AlertingOutbox(broken_factory, "test-host")
    outbox.fire(summary="s", detail="d")  # must NOT raise


# ---------------------------------------------------------------------------
# A5 -- the stop chain survives a failing per-child stop
# ---------------------------------------------------------------------------


@dataclass
class RaisingStopRunner:
    """Service-layer runner whose graceful_stop raises for chosen pids -- the
    LocalSystem reality at HEAD: a bare 'pg_ctl'/'nats-server' stop command is
    FileNotFoundError, or a hung one is TimeoutExpired."""

    raise_for: dict[int, BaseException] = field(default_factory=dict)
    events: list[tuple[str, int]] = field(default_factory=list)
    alive: dict[int, bool] = field(default_factory=dict)

    def graceful_stop(self, handle: FakeHandle) -> str:
        if handle.pid in self.raise_for:
            raise self.raise_for[handle.pid]
        self.events.append(("graceful", handle.pid))
        return handle.kind

    def is_alive(self, handle: FakeHandle) -> bool:
        return self.alive.get(handle.pid, False)

    def terminate(self, handle: FakeHandle) -> None:
        self.events.append(("terminate", handle.pid))
        self.alive[handle.pid] = False


@dataclass
class FakeServiceSupervisor:
    child_handles: dict[str, FakeHandle]
    graceful_stop_calls: int = 0

    def handles(self) -> dict[str, FakeHandle]:
        return dict(self.child_handles)

    def graceful_stop(self) -> None:
        self.graceful_stop_calls += 1


def _make_stop_chain_service(runner) -> tuple[object, FakeServiceSupervisor]:
    from civiccast.native.supervisor.service import SupervisorService

    handles = {
        "postgres": FakeHandle(pid=101, kind="argv"),
        "nats": FakeHandle(pid=102, kind="argv"),
        "control_plane": FakeHandle(pid=103, kind="ctrl_break_event"),
    }
    supervisor = FakeServiceSupervisor(child_handles=handles)
    clock = FakeClock()
    service = SupervisorService(
        supervisor=supervisor,  # type: ignore[arg-type]
        runner=runner,
        config=SupervisorConfig(),
        clock=clock.now,
        sleep=clock.sleep,
    )
    return service, supervisor


def test_stop_chain_survives_file_not_found_and_stops_every_child() -> None:
    """A5: a FileNotFoundError from one child's graceful stop must fall through
    to terminate for THAT child and continue the loop -- at HEAD it escaped
    graceful_stop_all inside run()'s finally, skipping the remaining children."""

    runner = RaisingStopRunner(
        raise_for={102: FileNotFoundError("nats-server not found on stock PATH")},
        alive={101: False, 102: True, 103: False},
    )
    service, supervisor = _make_stop_chain_service(runner)

    results = service.graceful_stop_all()  # must NOT raise

    by_name = {r.name: r for r in results}
    assert set(by_name) == {"postgres", "nats", "control_plane"}
    # The failing child fell through to terminate...
    assert ("terminate", 102) in runner.events
    assert by_name["nats"].outcome == "terminated"
    # ...the OTHERS still got their graceful actions...
    assert ("graceful", 103) in runner.events
    assert ("graceful", 101) in runner.events
    # ...and the state transition + Job Object backstop still ran.
    assert supervisor.graceful_stop_calls == 1


def test_stop_chain_survives_timeout_expired_from_a_stop_command() -> None:
    """A5: subprocess.TimeoutExpired from a hung stop command is contained the
    same way (terminate that child, keep the chain going)."""

    runner = RaisingStopRunner(
        raise_for={101: subprocess.TimeoutExpired(cmd=["pg_ctl", "stop"], timeout=10)},
        alive={101: True, 102: False, 103: False},
    )
    service, supervisor = _make_stop_chain_service(runner)

    results = service.graceful_stop_all()

    by_name = {r.name: r for r in results}
    assert by_name["postgres"].outcome == "terminated"
    assert ("terminate", 101) in runner.events
    assert supervisor.graceful_stop_calls == 1


# ---------------------------------------------------------------------------
# A6 -- NATS readiness is the JetStream publish+ack round-trip, not TCP accept
# ---------------------------------------------------------------------------


def test_provider_nats_probe_is_the_jetstream_publish_ack_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A6: D6 says 'TCP accept is explicitly NOT readiness'. The provider's
    nats_probe must perform the JetStream publish+ack round-trip -- at HEAD it
    was a bare socket connect."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    import civiccast.native.supervisor.service as service_module

    calls: list[tuple[str, float]] = []

    def fake_roundtrip(url: str, timeout_seconds: float) -> bool:
        calls.append((url, timeout_seconds))
        return True

    monkeypatch.setattr(service_module, "_jetstream_publish_ack", fake_roundtrip)

    deps = service_module.default_dependency_provider()

    assert deps.nats_probe() is True
    assert len(calls) == 1
    assert calls[0][0] == "nats://127.0.0.1:4222"


def test_provider_nats_probe_propagates_the_roundtrip_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G2 contract update: ``nats_probe`` itself must NOT catch and swallow a
    raised exception into a bare ``False`` -- that redundant catch is exactly
    what destroyed the exception TEXT before it ever reached
    ``check_nats_ready``'s ``ReadinessResult.detail`` (see
    ``test_supervisor_service.py``'s ``test_g2_nats_probe_wrapper_preserves_
    exception_detail``). The fail-closed BOUNDARY moved one layer up to
    ``check_nats_ready`` (children.py), which still fails closed on any
    exception -- proven separately, not here (this probe is a raw seam, not
    the readiness gate)."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    import civiccast.native.supervisor.service as service_module

    def raising_roundtrip(url: str, timeout_seconds: float) -> bool:
        raise ConnectionError("nats down")

    monkeypatch.setattr(service_module, "_jetstream_publish_ack", raising_roundtrip)

    deps = service_module.default_dependency_provider()

    with pytest.raises(ConnectionError, match="nats down"):
        deps.nats_probe()


def test_jetstream_publish_ack_publishes_to_probe_stream_and_reads_the_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The concrete round-trip: connect -> jetstream -> ensure probe stream ->
    publish -> ack.seq. Proven against a fake nats-py provider module."""

    import types

    published: list[tuple[str, bytes]] = []
    streams: list[str] = []
    closed: list[bool] = []

    class _Ack:
        seq = 7

    class _Js:
        async def add_stream(self, name: str, subjects: list[str]) -> None:
            streams.append(name)

        async def publish(self, subject: str, payload: bytes, timeout=None) -> _Ack:
            published.append((subject, payload))
            return _Ack()

    class _Client:
        def jetstream(self, timeout=None) -> _Js:
            return _Js()

        async def close(self) -> None:
            closed.append(True)

    async def _connect(url: str, **kwargs) -> _Client:
        assert url.startswith("nats://")
        return _Client()

    monkeypatch.setitem(sys.modules, "nats", types.SimpleNamespace(connect=_connect))

    from civiccast.native.supervisor.service import _jetstream_publish_ack

    ok = _jetstream_publish_ack("nats://127.0.0.1:4222", 2.0)

    assert ok is True
    assert len(published) == 1
    assert streams, "the probe stream must be ensured before the publish"
    assert closed == [True], "the connection must be closed even on success"


def test_jetstream_publish_ack_without_a_seq_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ack with no sequence is NOT a completed publish+ack round-trip."""

    import types

    class _Js:
        async def add_stream(self, name: str, subjects: list[str]) -> None:
            pass

        async def publish(self, subject: str, payload: bytes, timeout=None) -> object:
            return object()  # no .seq

    class _Client:
        def jetstream(self, timeout=None) -> _Js:
            return _Js()

        async def close(self) -> None:
            pass

    async def _connect(url: str, **kwargs) -> _Client:
        return _Client()

    monkeypatch.setitem(sys.modules, "nats", types.SimpleNamespace(connect=_connect))

    from civiccast.native.supervisor.service import _jetstream_publish_ack

    assert _jetstream_publish_ack("nats://127.0.0.1:4222", 2.0) is False


def test_jetstream_publish_ack_survives_pythonservice_set_wakeup_fd_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service-host regression proven live in a Windows Sandbox service run
    (supervisor.log): inside pythonservice.exe's supervision thread,
    ``threading.current_thread() is threading.main_thread()`` passes even
    though the OS does not treat that thread as the process's true main
    thread. The OLD implementation called ``asyncio.run(...)``, which builds
    the default ``ProactorEventLoop`` on Windows; ``BaseProactorEventLoop.
    __init__`` (asyncio/proactor_events.py) calls ``signal.set_wakeup_fd(...)``
    whenever that (fooled) Python-level thread-identity check is True. The
    C-level check inside ``set_wakeup_fd`` itself is stricter and raises
    ``ValueError: set_wakeup_fd only works in main thread of the main
    interpreter`` -- so every readiness probe attempt raised, the fail-closed
    gate returned not_ready forever, and NATS never went ready.

    This reproduces WITHOUT pythonservice.exe: pytest's own test thread
    genuinely IS ``threading.main_thread()`` (the guard is satisfied
    honestly, not fooled), so the OLD ``asyncio.run(...)`` path exercises the
    exact same ``BaseProactorEventLoop.__init__`` line and calls the patched,
    raising ``set_wakeup_fd`` -- proving the defect at HEAD without a service
    host. The fix constructs a ``SelectorEventLoop`` directly, which never
    touches ``signal`` machinery, so the patched raise is never reached and
    the round-trip succeeds.
    """

    import types

    def _raise_set_wakeup_fd(*_args: object, **_kwargs: object) -> int:
        raise ValueError("set_wakeup_fd only works in main thread of the main interpreter")

    monkeypatch.setattr(signal, "set_wakeup_fd", _raise_set_wakeup_fd)

    class _Ack:
        seq = 9

    class _Js:
        async def add_stream(self, name: str, subjects: list[str]) -> None:
            pass

        async def publish(self, subject: str, payload: bytes, timeout=None) -> _Ack:
            return _Ack()

    class _Client:
        def jetstream(self, timeout=None) -> _Js:
            return _Js()

        async def close(self) -> None:
            pass

    async def _connect(url: str, **kwargs: object) -> _Client:
        return _Client()

    monkeypatch.setitem(sys.modules, "nats", types.SimpleNamespace(connect=_connect))

    from civiccast.native.supervisor.service import _jetstream_publish_ack

    assert _jetstream_publish_ack("nats://127.0.0.1:4222", 2.0) is True


# ---------------------------------------------------------------------------
# Chain H1: the acquisition download root must be a first-class part of the
# resolved install layout, and the local-AI store search must include it --
# the first-run GUI can no longer write `<install_root>\packs\local-ai-model`.
# ---------------------------------------------------------------------------


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_install_layout_carries_the_per_machine_acquisition_roots() -> None:
    from civiccast.native.supervisor.install_layout import resolve_install_layout

    layout = resolve_install_layout(
        executable=r"C:\Program Files\CivicCast (Native)\runtime\python.exe",
        program_data_root=r"C:\ProgramData",
    )
    assert layout.acquired_packs_root == Path(r"C:\ProgramData\CivicCast\packs")
    assert layout.acquired_local_ai_models_dir == Path(
        r"C:\ProgramData\CivicCast\packs\local-ai-model\models"
    )


def test_the_ollama_store_search_includes_the_writable_acquisition_root_last() -> None:
    from civiccast.native.supervisor.install_layout import (
        ollama_model_store_candidates,
        resolve_install_layout,
    )

    layout = resolve_install_layout(
        executable=r"C:\Program Files\CivicCast (Native)\runtime\python.exe",
        program_data_root=r"C:\ProgramData",
    )
    assert ollama_model_store_candidates(layout) == (
        layout.ollama_models_dir,
        layout.local_ai_pack_models_dir,
        layout.acquired_local_ai_models_dir,
    )
