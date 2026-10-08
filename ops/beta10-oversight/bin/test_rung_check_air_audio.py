# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U66 item 1: the rung hands the adjudicator the audio the capture heard.

C15 (2026-09-29 07:18) came back ruled at 3226.3 s for a window that was really
at 7121 s.  Part of why: `rung_check.adjudicate()` ran the adjudicator with no
`--air-audio`, so the only signal that could have contradicted the log's
position never ran.  The rung holds the capture's own snapshot segments -- the
audio the capture measured -- and can concatenate them itself.

These tests drive the real tool as a SUBPROCESS, because the tool is a script
whose dispatch is module-level code and the adjudicator is invoked as a child
process of it.  The adjudicator is replaced, in a copy of the tool's own
directory, by a stub that records the argv it was handed: that is the contract
this item adds, and it is asserted end to end, not by reading claims about it.

Nothing here reads the live station: the evidence, the segments and the scratch
tree are all built under tmp_path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOL = _HERE / "rung_check.py"

_CHANNEL = "education"
_WINDOW = 241.666667
#: The word the rung prints for a window the adjudicator excluded.
_EXCUSED = "EXCLUDED_QUIET_SOURCE"

#: A stub adjudicator: it writes the argv it was handed to `_STUB_ARGV` beside
#: itself and emits a minimal report, so the test can assert BOTH the call the
#: rung made and the line the rung printed from the answer it got back.
_STUB = '''\
# SPDX-License-Identifier: Apache-2.0
"""Stub loudness_window_adjudicate for the U66 item-1 test.  Records its argv."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
argv = sys.argv[1:]
(HERE / "stub-argv.json").write_text(json.dumps(argv), encoding="utf-8")

out = None
if "--out" in argv:
    out = argv[argv.index("--out") + 1]
line = 'education=EXCLUDED_QUIET_SOURCE asset="City Council Regular Session - August 11, 2026.mp4" pos=7121s(correlation)'
# The rung does not print the adjudicator's line: it re-renders the exclusion
# from the report's own fields (rung_check.excused), so the stub has to answer
# in the adjudicator's real report shape, not with a pre-baked sentence.
got = {
    "classification": "EXCLUDED_QUIET_SOURCE",
    "summary_line": line,
    "asset": {"display_name": "City Council Regular Session - August 11, 2026.mp4"},
    "position": {"position_s": 7121},
    "source": {"lift_limited_lufs": -35.0, "span_lufs": -35.9, "scorable_seconds": 197.0},
    "max_reachable_lufs": -35.0,
    "air": {"integrated_lufs": -21.9},
    "unreachable_seconds": 171.0,
    "unreachable_range_s": [140.0, 197.0],
    "min_unreachable_seconds": 60.0,
    "window_seconds": 241.666667,
}
report = {
    "tool": "loudness_window_adjudicate",
    "channels": {"education": got},
    "summary": [line],
}
if out:
    Path(out).write_text(json.dumps(report), encoding="utf-8")
print(line)
'''


def _tool_copy(tmp_path: Path) -> Path:
    """The tool plus a stub adjudicator beside it, so `adjudicate` finds the stub."""
    d = tmp_path / "tool"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_TOOL, d / "rung_check.py")
    (d / "loudness_window_adjudicate.py").write_text(_STUB, encoding="utf-8")
    return d / "rung_check.py"


def _segments(tmp_path: Path, bodies: list[bytes]) -> list[dict]:
    """Snapshot segments on disk, in the shape the capture writes them."""
    d = tmp_path / "data" / "egress" / _CHANNEL / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for i, body in enumerate(bodies):
        p = d / f"seg-{7609 + i}.ts"
        p.write_bytes(body)
        out.append(
            {
                "sequence": 7609 + i,
                "name": f"seg-{7609 + i}.ts",
                "snapshot_path": str(p),
                "bytes": len(body),
                "sha256": sha256(body).hexdigest(),
                "present": True,
                "capture_status": "complete",
                "extinf_seconds": 6.0,
            }
        )
    return out


def _evidence(tmp_path: Path, segments: list[dict], **chan_over: object) -> Path:
    chan = {
        "status": "FAIL",
        "captured_at_utc": "2026-09-29T07:18:00+00:00",
        "captured_duration_seconds": _WINDOW,
        "segment_count": len(segments),
        "segments": segments,
        # The capture's structural signs, so the window is one the adjudicator may
        # excuse rather than a short/continuity-broken capture no source can paper
        # over -- `excusable` refuses on either of those.
        "continuity": {"status": "PASS"},
        "audio_window": {
            "status": "FAIL",
            "integrated_lufs": -21.9,
            "within_target": False,
            "duration_seconds": _WINDOW,
            "target_lufs": -16.0,
            "tolerance_lufs": 1.0,
            "detail": "window integrated -21.9 LUFS over 241.7s (target -16 +/- 1)",
        },
    }
    chan.update(chan_over)
    p = tmp_path / "loudness-09.json"
    p.write_text(
        json.dumps(
            {
                "tool": "rung_loudness_capture",
                "target_lufs": -16.0,
                "tolerance_lufs": 1.0,
                "blocking_reasons": [],
                "channels": {
                    _CHANNEL: chan,
                    "government": {"status": "PASS"},
                    "public": {"status": "PASS"},
                },
            }
        ),
        encoding="utf-8",
    )
    return p


def _run(tool: Path, evidence: Path, scratch: Path, tmp_path: Path) -> str:
    env = dict(os.environ)
    env["CIVICAST_AIR_AUDIO_DIR"] = str(scratch)
    env["TEMP"] = str(tmp_path)  # the adjudicator's own report lands under here
    env["TMP"] = str(tmp_path)
    # The test invokes its repo-local script with fixture paths as separate argv values.
    got = subprocess.run(  # noqa: S603
        [sys.executable, str(tool), "loudness", str(evidence)],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        shell=False,
    )
    assert got.returncode == 0, got.stderr
    return got.stdout.strip()


def _stub_argv(tool: Path) -> list[str]:
    raw = (tool.parent / "stub-argv.json").read_text(encoding="utf-8")
    return json.loads(raw)


# ---------------------------------------------------------------------------


def test_captured_segments_are_concatenated_and_passed_as_air_audio(tmp_path: Path) -> None:
    """RED before item 1: the adjudicator was invoked with no `--air-audio`."""
    tool = _tool_copy(tmp_path)
    bodies = [b"SEGMENT-ONE-" * 100, b"SEGMENT-TWO-" * 100, b"SEGMENT-THREE-" * 100]
    evidence = _evidence(tmp_path, _segments(tmp_path, bodies))
    scratch = tmp_path / "air"

    printed = _run(tool, evidence, scratch, tmp_path)

    argv = _stub_argv(tool)
    assert "--air-audio" in argv, argv
    given = argv[argv.index("--air-audio") + 1]
    ch, path = given.split("=", 1)
    assert ch == _CHANNEL
    # The concatenation is the capture's own bytes, in sequence order.
    assert Path(path).read_bytes() == b"".join(bodies)
    assert Path(path).parent == scratch
    # ... and the rung printed the answer the adjudicator gave it.
    assert f"education={_EXCUSED}" in printed, printed
    assert "pos=7121s" in printed


def test_failed_adjudicator_cannot_reuse_stale_exclusion(tmp_path: Path) -> None:
    tool = _tool_copy(tmp_path)
    (tool.parent / "loudness_window_adjudicate.py").write_text(
        "import sys\nsys.exit(1)\n", encoding="utf-8"
    )
    evidence = _evidence(tmp_path, _segments(tmp_path, [b"AAA" * 50]))
    stale_dir = tmp_path / "cc-loud-adj"
    stale_dir.mkdir()
    stale_report = {
        "channels": {
            _CHANNEL: {
                "classification": _EXCUSED,
                "asset": {"display_name": "stale source"},
                "position": {"position_s": 7121},
                "source": {
                    "lift_limited_lufs": -35.0,
                    "span_lufs": -35.9,
                    "scorable_seconds": 197.0,
                },
                "max_reachable_lufs": -35.0,
                "air": {"integrated_lufs": -21.9},
                "unreachable_seconds": 171.0,
                "unreachable_range_s": [140.0, 197.0],
                "min_unreachable_seconds": 60.0,
                "window_seconds": _WINDOW,
            }
        }
    }
    (stale_dir / "loudness-09.adjudicated.json").write_text(
        json.dumps(stale_report), encoding="utf-8"
    )

    printed = _run(tool, evidence, tmp_path / "air", tmp_path)

    assert f"education={_EXCUSED}" not in printed, printed
    assert "education=FAIL(adjudicator gave no answer)" in printed, printed


def test_a_snapshot_that_is_already_swept_is_simply_left_out(tmp_path: Path) -> None:
    """Best-effort by design: the capture tree prunes; a missing chunk is skipped."""
    tool = _tool_copy(tmp_path)
    segments = _segments(tmp_path, [b"AAA" * 50, b"BBB" * 50, b"CCC" * 50])
    Path(segments[1]["snapshot_path"]).unlink()
    evidence = _evidence(tmp_path, segments)

    _run(tool, evidence, tmp_path / "air", tmp_path)

    given = _stub_argv(tool)
    path = given[given.index("--air-audio") + 1].split("=", 1)[1]
    assert Path(path).read_bytes() == (b"AAA" * 50) + (b"CCC" * 50)


def test_no_snapshot_on_disk_means_no_air_audio_at_all(tmp_path: Path) -> None:
    """Fail-closed: with nothing to concatenate the adjudicator gets no path, so
    it cannot be told a window it never heard either."""
    tool = _tool_copy(tmp_path)
    segments = _segments(tmp_path, [b"AAA" * 50])
    Path(segments[0]["snapshot_path"]).unlink()
    evidence = _evidence(tmp_path, segments)

    _run(tool, evidence, tmp_path / "air", tmp_path)

    assert "--air-audio" not in _stub_argv(tool)


def test_an_instrument_error_channel_pulls_no_air_audio(tmp_path: Path) -> None:
    """A channel with no measurement is not adjudicable -- and must not be."""
    tool = _tool_copy(tmp_path)
    evidence = _evidence(
        tmp_path,
        _segments(tmp_path, [b"AAA" * 50]),
        audio_window={"status": "FAIL", "detail": "capture failed: no audio window"},
    )

    printed = _run(tool, evidence, tmp_path / "air", tmp_path)

    # The adjudicator was never run at all: a channel with no measurement has no
    # window to excuse, so the rung does not pay for its ffmpeg passes -- and
    # cannot be handed audio it has no ruling for.
    assert not (tool.parent / "stub-argv.json").exists()
    assert "education=INSTRUMENT_ERROR(" in printed


def test_a_pass_channel_is_never_concatenated(tmp_path: Path) -> None:
    """The rung only pays for the channels it has to adjudicate."""
    tool = _tool_copy(tmp_path)
    evidence = _evidence(tmp_path, _segments(tmp_path, [b"AAA" * 50]), status="PASS")

    _run(tool, evidence, tmp_path / "air", tmp_path)

    assert not (tmp_path / "air").exists()
    assert not (tool.parent / "stub-argv.json").exists()


def test_the_same_window_reuses_its_concat_and_drops_the_previous_one(tmp_path: Path) -> None:
    """The rung re-runs against the same evidence every ~30 min; re-concatenating
    the same bytes wastes a pass, and keeping the PREVIOUS window's concat would
    leave a stale file that looks like this window's evidence."""
    tool = _tool_copy(tmp_path)
    scratch = tmp_path / "air"
    evidence = _evidence(tmp_path, _segments(tmp_path, [b"AAA" * 50]))

    _run(tool, evidence, scratch, tmp_path)
    first = Path(_stub_argv(tool)[_stub_argv(tool).index("--air-audio") + 1].split("=", 1)[1])
    stamp = first.stat().st_mtime_ns

    _run(tool, evidence, scratch, tmp_path)
    second = Path(_stub_argv(tool)[_stub_argv(tool).index("--air-audio") + 1].split("=", 1)[1])
    assert second == first
    assert second.stat().st_mtime_ns == stamp  # reused, not rewritten
    assert list(scratch.glob(f"{_CHANNEL}-*.aac.ts")) == [first]

    # A different window (different segment digests) replaces it, and the old
    # file does not survive to be read as this window's evidence.
    other = _evidence(tmp_path, _segments(tmp_path, [b"ZZZ" * 50]))
    _run(tool, other, scratch, tmp_path)
    third = Path(_stub_argv(tool)[_stub_argv(tool).index("--air-audio") + 1].split("=", 1)[1])
    assert third != first
    assert list(scratch.glob(f"{_CHANNEL}-*.aac.ts")) == [third]
