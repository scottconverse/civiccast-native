# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gate A T4 (run 33781833394, kit e1acfe6): the GStreamer playout worker launched,
lived ~10s, exited non-zero, and the daemon reported it as ``FFmpeg child exited
non-zero`` with no trace of the worker's own stderr -- so the operator (and the gate)
saw an ffmpeg problem that did not exist and no reason at all.

Two contracts pinned here:

1. A non-zero child exit names the ENGINE that actually ran, and folds the child's
   redacted stderr tail into ``last_error``.
2. The CPU-decode policy is enforced from the REGISTRY, not from a hand-maintained
   name list -- the list omitted ``d3d12h264dec``, which the shipped Windows runtime
   registers at rank 258, above ``avdec_h264``'s 256, so decodebin kept autoplugging
   a GPU decoder on a box with no working GPU decode path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from civiccast.egress.daemon import EgressDaemon
from civiccast.egress.encoder_strategy import EncoderStartRequest, EncoderStartResult
from civiccast.egress.gst.decode_policy import (
    CPU_DECODE_FEATURE_RANK,
    demote_hardware_decoders,
)
from civiccast.egress.models import (
    EgressCommand,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
    redact_source_uri,
    redact_uris_in_text,
)
from civiccast.egress.store import InMemoryEgressStore


class _FakeProcess:
    def __init__(self, *, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0


class _WorkerStrategy:
    """A GStreamer-named strategy whose child writes a real stderr log, then dies."""

    name = "gstreamer-playout-worker"
    supports_live_swap = True
    supports_content_reload = True

    def __init__(self, processes: list[_FakeProcess], stderr_text: str) -> None:
        self._processes = processes
        self._stderr_text = stderr_text

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        process = self._processes.pop(0)
        log_dir = request.work_dir / request.channel_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / "gst-worker.stderr.log"
        stderr_path.write_text(self._stderr_text, encoding="utf-8")
        return EncoderStartResult(
            process=process,
            concat_plan_path=request.work_dir / "playout-graph.json",
            stdout_path=log_dir / "gst-worker.stdout.log",
            stderr_path=stderr_path,
            args=("worker",),
        )

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def reload_content(  # pragma: no cover
        self, channel_id: str, work_dir: Path, request: EncoderStartRequest
    ) -> bool:
        return False


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _source_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "source-a.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Council meeting",
                path=str(source),
                duration_seconds=1,
                source_ref="asset-council",
            )
        ],
    )


def _start_command() -> EgressCommand:
    return EgressCommand(
        channel_id="gov",
        action="start",
        issued_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        issued_by="operator",
        command_id="cmd-start",
    )


_STALL_LINE = "CTRL stall: no output for 10s - quitting for daemon restart"


def test_crash_relaunch_names_the_gstreamer_engine_and_carries_the_worker_stderr_tail(
    tmp_path: Path,
    caplog: Any,
) -> None:
    """Gate A run 33781833394's control_plane-app.log said 'FFmpeg child exited
    non-zero; relaunching encoder.' for a child that was the GStreamer worker, and
    said nothing about why. Both halves are fixed here."""
    store = InMemoryEgressStore()
    store.upsert_config(_config())
    store.enqueue_command(_start_command())
    dying = _FakeProcess(pid=2556)
    strategy = _WorkerStrategy(
        [dying, _FakeProcess(pid=2557)],
        stderr_text=f"some earlier chatter\n{_STALL_LINE}\n",
    )
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: _source_plan(tmp_path),
        encoder_strategy=strategy,
    )

    assert daemon.process_once("gov") == 1
    assert store.read_state("gov").state == "ON_AIR"

    dying.returncode = 1  # the worker exits non-zero, exactly as it did in the gate run
    with caplog.at_level(logging.INFO, logger="civiccast.egress.daemon"):
        daemon.process_once("gov")

    # The relaunch's own successful start clears last_error again, so read the
    # STARTING transition the daemon logs -- which is the exact line Gate A run
    # 33781833394 captured in control_plane-app.log.
    starting = [line for line in caplog.messages if "-> STARTING" in line]
    assert starting, "the crash relaunch must log its STARTING transition"
    line = starting[0]  # the crash-relaunch transition itself
    assert "FFmpeg" not in line, "the child was the GStreamer worker, not ffmpeg"
    assert "GStreamer playout worker child exited non-zero" in line
    assert _STALL_LINE in line, "the worker's own stderr tail must reach the operator"


def test_child_stderr_tail_is_bounded_and_redacts_ingest_credentials(tmp_path: Path) -> None:
    """A GStreamer error message QUOTES the ingest URI mid-line, and that URI can carry
    an SRT passphrase (ENG-003).

    Review catch on this PR's first revision: the secret line must be INSIDE the
    returned tail, or the test proves nothing. The original version buried it behind
    200 filler lines, so the 8-line tail never contained it and the assertion passed
    against `redact_source_uri`, which does not redact a URI embedded in text at all.
    """
    store = InMemoryEgressStore()
    daemon = EgressDaemon(
        store,
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
    )
    log_path = tmp_path / "err.log"
    log_path.write_text(
        "".join(f"filler line {index}\n" for index in range(200))
        # LAST line -- inside the 8-line tail, which is the whole point.
        + "ERROR failed to open srt://headend.example:9000?passphrase=hunter2seekrit\n",
        encoding="utf-8",
    )
    daemon._stderr_logs["gov"] = log_path

    tail = daemon._child_stderr_tail("gov")
    assert tail is not None
    assert "ERROR failed to open" in tail, "the secret line must be INSIDE the tail"
    assert "hunter2seekrit" not in tail
    # `redact_source_uri` percent-encodes the marker through urlencode, so the stored
    # form is `passphrase=%3Credacted%3E` -- the repo-wide shape (test_contracts.py,
    # test_gst_bridge.py). Match case-insensitively on the word itself.
    assert "redacted" in tail.lower(), "something must visibly mark the removal"
    assert "headend.example" in tail, "the host is diagnostic and must survive"
    assert len(tail) <= 600
    assert "filler line 199" in tail, "the TAIL is what matters, not the head"


def test_child_stderr_tail_redacts_userinfo_credentials_mid_line(tmp_path: Path) -> None:
    """The other credential shape: ``rtmps://user:pass@host`` quoted inside an error
    line. ``redact_source_uri`` drops userinfo silently, which reads as "there was no
    credential here"; in free text the scanner leaves a visible marker instead."""
    daemon = EgressDaemon(
        InMemoryEgressStore(),
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
    )
    log_path = tmp_path / "err.log"
    log_path.write_text(
        "gstreamer rtmp2sink: connect to rtmps://civiccast:sup3rsecret@live.example/app "
        "refused after 3 tries\n",
        encoding="utf-8",
    )
    daemon._stderr_logs["gov"] = log_path

    tail = daemon._child_stderr_tail("gov")
    assert tail is not None
    assert "sup3rsecret" not in tail
    assert "civiccast:sup3rsecret" not in tail
    assert "<redacted>@live.example" in tail
    assert "refused after 3 tries" in tail, "the diagnostic text must survive"


def test_child_exit_error_still_says_ffmpeg_for_the_ffmpeg_strategy(tmp_path: Path) -> None:
    """Naming the engine must not rename the ffmpeg path -- that message is correct
    there and operators/runbooks match on it."""

    class _Ffmpeg:
        name = "ffmpeg-concat"

    daemon = EgressDaemon(
        InMemoryEgressStore(),
        work_dir=tmp_path,
        source_plan_provider=lambda _channel_id: None,
        encoder_strategy=_Ffmpeg(),  # type: ignore[arg-type]
    )
    assert daemon._child_exit_error("gov", suffix="relaunching encoder.") == (
        "FFmpeg encoder child exited non-zero; relaunching encoder."
    )


# -- CPU-decode policy ---------------------------------------------------------------


class _FakeFeature:
    def __init__(self, name: str, klass: str, rank: int) -> None:
        self._name = name
        self._klass = klass
        self.rank = rank

    def get_name(self) -> str:
        return self._name

    def get_metadata(self, key: str) -> str:
        return self._klass if key == "klass" else ""

    def get_rank(self) -> int:
        return self.rank

    def set_rank(self, rank: int) -> None:
        self.rank = rank


def test_demote_hardware_decoders_covers_the_bundled_d3d12_family(monkeypatch: Any) -> None:
    """The measured Gate A T4 root cause: on the e1acfe6 kit's own GStreamer closure
    ``d3d12h264dec`` registers at rank 258 -- above ``d3d11h264dec`` (257, which the
    name list DID demote) and above ``avdec_h264`` (256). decodebin therefore kept
    picking a GPU decoder while the engine's stated policy said CPU decode. The
    registry sweep demotes by klass, so it cannot go stale when the runtime gains a
    plugin nobody added to the list."""
    monkeypatch.delenv("CIVICCAST_GST_ALLOW_HARDWARE_DECODE", raising=False)
    features = [
        _FakeFeature("d3d12h264dec", "Codec/Decoder/Video/Hardware", 258),
        _FakeFeature("d3d11h264dec", "Codec/Decoder/Video/Hardware", 0),
        _FakeFeature("avdec_h264", "Codec/Decoder/Video", 256),
        _FakeFeature("mfh264enc", "Codec/Encoder/Video/Hardware", 259),
    ]
    demoted = demote_hardware_decoders(features)

    assert demoted == ["d3d12h264dec"]
    ranks = {feature.get_name(): feature.rank for feature in features}
    assert ranks["d3d12h264dec"] == 0, "the GPU decoder must lose autoplug"
    assert ranks["avdec_h264"] == 256, "the software decoder is untouched"
    assert ranks["mfh264enc"] == 259, "ENCODERS are out of scope -- only decoders"


def test_hardware_decode_opt_in_disables_the_sweep(monkeypatch: Any) -> None:
    monkeypatch.setenv("CIVICCAST_GST_ALLOW_HARDWARE_DECODE", "1")
    feature = _FakeFeature("d3d12h264dec", "Codec/Decoder/Video/Hardware", 258)
    assert demote_hardware_decoders([feature]) == []
    assert feature.rank == 258


def test_feature_rank_env_list_names_every_bundled_hardware_decoder_family() -> None:
    """Belt to the sweep's suspenders: the env list runs BEFORE Gst.init and is what
    keeps a GPU decoder from being chosen during registry scan on runtimes where the
    sweep's registry object is not reachable. It must name the d3d12 family the
    shipped Windows closure bundles (gstd3d12.dll)."""
    names = {entry.split(":")[0] for entry in CPU_DECODE_FEATURE_RANK.split(",")}
    assert {"d3d12h264dec", "d3d12h265dec", "d3d11h264dec", "d3d11h265dec"} <= names
    assert all(entry.endswith(":0") for entry in CPU_DECODE_FEATURE_RANK.split(","))


# -- the mid-line URI scanner itself -------------------------------------------------


@pytest.mark.parametrize(
    ("line", "must_not_contain", "must_contain"),
    [
        (
            "ERROR failed to open srt://h.example:9000?passphrase=hunter2seekrit",
            "hunter2seekrit",
            "redacted",
        ),
        (
            "rtmp2sink: connect to rtmps://civiccast:sup3rsecret@live.example/app refused",
            "sup3rsecret",
            "<redacted>@live.example",
        ),
        (
            "ERROR source rtsp://admin:letmein@cam.local/stream1 timed out",
            "letmein",
            "<redacted>@cam.local",
        ),
        (
            "publish to rtmp://ingest.example/app?streamkey=abc123 failed",
            "abc123",
            "redacted",
        ),
        (
            "GET https://docs.example/help?token=leakme. retry",
            "leakme",
            "redacted",
        ),
    ],
)
def test_redact_uris_in_text_scrubs_credentials_embedded_mid_line(
    line: str, must_not_contain: str, must_contain: str
) -> None:
    """The hole this scanner closes: every one of these lines passes through
    ``redact_source_uri`` COMPLETELY UNCHANGED.

    Precision that matters, and that a first draft of this test got wrong: a URI at
    position 0 IS handled by ``redact_source_uri`` -- ``urlsplit`` finds the authority
    fine. The hole is a URI that is not the whole string, which is what a child process
    actually writes ("ERROR failed to open <uri>"). Every fixture below is therefore
    genuinely mid-line, and the guard assertion proves each one is really unhandled
    today rather than assuming it.
    """
    assert must_not_contain in redact_source_uri(line), (
        "guard: if redact_source_uri ever handles mid-line URIs, this scanner's "
        "reason for existing has changed and this test should be revisited"
    )
    scrubbed = redact_uris_in_text(line)
    assert must_not_contain not in scrubbed
    assert must_contain in scrubbed


@pytest.mark.parametrize(
    "line",
    [
        "plain log line with no uri at all",
        r"C:\ProgramData\CivicCast\data\egress\government\slate.ts is missing",
        "filesrc location=/var/lib/civiccast/slate.ts",
        "udp://127.0.0.1:19003 opened",  # no credential to remove
    ],
)
def test_redact_uris_in_text_leaves_credential_free_text_alone(line: str) -> None:
    """A redactor that mangles ordinary diagnostic text costs more than it saves --
    the whole point of the tail is that an operator can read it."""
    assert redact_uris_in_text(line) == line
