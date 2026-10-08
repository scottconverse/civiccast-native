"""U37 X4 -- GROUND-TRUTH A/B of the real prepared-media deferred program->program
reload, with the tree under test selectable.

The earlier harnesses (x1/x2) scored the engine's own `[mux-in ...]` counters,
which are all PRE-commit: a finite clip EOSes right after the committed switch,
so no post-commit interval row ever appears and the "no COLLAPSE" verdict those
harnesses print is vacuous.  This one scores the recorded mux output `out.ts`
instead -- the bytes that actually aired -- parsed with the pure-Python 188-byte
TS/PES parsers in tsraw.py, with no GStreamer pipeline in the loop.

A video stream whose running time steps FORWARD by more than a second (the
re-dating: `rt_new = rt_old + applied_offset`) or steps BACKWARD (the stale
outgoing tail buffer clipped under the new segment) is the U37 defect.

The outgoing graph shape is selectable (`--caps base|production`, `--captions
on|off`, `--repeats N`) so the SAME scorer can be pointed at the live playout
shape (1280x720@30 + openh264enc + the caption-embed leg), which is the shape
that reproduces the live A/V end offset (`ends=[video=...,audio=...]`).

Usage:
  python x4.py --outgoing PATH --incoming PATH [--tree PATH] [--runs N]
               [--caps base|production] [--captions on|off] [--repeats N]
               [--after-intervals N] [--tag NAME]
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

SCRATCH = Path(r"C:\Users\scott\AppData\Local\Temp\u37")
RUNTIME = r"C:\Program Files\CivicCast (Native)\runtime"
WT = Path(r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-u37")

argv = sys.argv[1:]


def opt(name: str, default: str | None = None) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else default


TREE = Path(str(opt("--tree", str(WT))))

# SPELLING MATTERS: the runtime probes `CIVICCAST_GSTREAMER_RUNTIME_ROOT` (double
# C).  The single-C variant silently no-ops and the worker dies on `import gi`.
os.environ.setdefault("CIVICCAST_GSTREAMER_RUNTIME_ROOT", RUNTIME)
# The worker subprocess resolves `civiccast` through the venv's editable .pth
# (a plain path line, not a finder), so PYTHONPATH outranks it -- this is what
# makes the SAME harness drive the base revision's engine.
os.environ["PYTHONPATH"] = str(TREE)

sys.path.insert(0, str(TREE))
sys.path.insert(0, str(TREE / "tests" / "egress"))
sys.path.append(str(SCRATCH))  # tsraw lives here; append so it cannot shadow stdlib

_runtime_python = Path(RUNTIME) / "dependencies" / "gstreamer" / "python"
if not _runtime_python.is_dir():
    raise SystemExit(
        f"ABORT: {_runtime_python} is missing -- every worker would die at "
        "engine.py's `import gi` and _reap would then hang on the unconnected pipe."
    )

import test_gst_engine_wsl  # noqa: E402
import tsraw  # noqa: E402

_engine_src = TREE / "civiccast" / "egress" / "gst" / "engine.py"
print(f"# tree={TREE}")
print(
    f"# engine_src={_engine_src} sha256="
    f"{__import__('hashlib').sha256(_engine_src.read_bytes()).hexdigest()[:16]} "
    f"bytes={_engine_src.stat().st_size}"
)
print(f"# PYTHONPATH={os.environ['PYTHONPATH']} (the worker inherits this)")

_PID_VIDEO = 0x41
_PID_AUDIO = 0x42

# x2.py's `build()` verbatim, minus the sys.path side effects: the live playout
# shape is `filesrc ! decodebin ! videoconvert ! videoscale ! videorate !
# capsfilter(1280x720@30)` per subchain, the production encoder chain, and the
# caption-embed leg downstream of it.
_E = test_gst_engine_wsl.graphmod.ElementSpec
_CAPS = {"base": test_gst_engine_wsl._CAPS, "production": test_gst_engine_wsl._PRODUCTION_CAPS}


def _reload_graph(
    clip: Path, *, caps: str, captions: bool, repeats: int, **ignored
):  # `debug` is a launch-time knob, not graph shape
    program = test_gst_engine_wsl.graphmod.PlaylistLeg(
        label="program",
        subchains=tuple(
            (
                _E("filesrc", props={"location": str(clip)}),
                _E("decodebin"),
                _E("videoconvert"),
                _E("videoscale"),
                _E("videorate"),
                _E("capsfilter", props={"caps": _CAPS[caps]}),
            )
            for _ in range(repeats)
        ),
        audio_tail=(
            _E("audioconvert"),
            _E("audioresample"),
            _E("capsfilter", props={"caps": test_gst_engine_wsl._ACAPS}),
        ),
    )
    base = test_gst_engine_wsl._av_demo_graph(nsrc=2)
    enc = (
        base.encoder
        if caps == "base"
        else test_gst_engine_wsl.graphmod.encode_chain_specs(
            width=1280,
            height=720,
            fps=30,
            bitrate_kbps=6000,
            gop=60,
            encoder=test_gst_engine_wsl._H264_ENCODER,
        )
    )
    return test_gst_engine_wsl.graphmod.PlayoutGraph(
        sources=(program, base.sources[1]),
        encoder=enc,
        audio_encoder=base.audio_encoder,
        mux=base.mux,
        sinks=base.sinks,
        captions=test_gst_engine_wsl.graphmod.caption_embed_leg_live() if captions else None,
    )


def _ends(text: str) -> str:
    """The engine's own measurement of the outgoing leg's per-stream end."""
    m = re.search(r"ends=\[video=([\d.]+),audio=([\d.]+)\]", text)
    if not m:
        return "ends=<engine printed none>"
    v, a = float(m.group(1)), float(m.group(2))
    return f"ends=[video={v:.3f},audio={a:.3f}] gap(a-v)={a - v:+.3f}s"


def _gt(path: Path) -> dict[int, dict]:
    """Per-PID PES PTS ground truth straight out of the recorded mux output."""
    data = path.read_bytes()
    pmt_pid = None
    for sec in tsraw.psi_sections(data, 0):
        if len(sec) >= 12 and sec[0] == 0x00:
            pmt_pid = ((sec[10] & 0x1F) << 8) | sec[11]
            break
    streams = tsraw.pmt_pids(data, pmt_pid) if pmt_pid is not None else {}
    pts: dict[int, list[int]] = {pid: [] for pid in streams}
    for pid, pusi, payload in tsraw.packets(data):
        if pid in pts and pusi:
            v = tsraw.pes_pts(payload)
            if v is not None:
                pts[pid].append(v)
    out: dict[int, dict] = {}
    for pid, values in sorted(pts.items()):
        uniq = sorted(set(values))
        steps = sorted(
            ((uniq[i] - uniq[i - 1], uniq[i - 1], uniq[i]) for i in range(1, len(uniq))),
            reverse=True,
        )
        out[pid] = {
            "n": len(values),
            "uniq": len(uniq),
            "regress": sum(1 for i in range(1, len(values)) if values[i] < values[i - 1]),
            "first": uniq[0] / 90000 if uniq else float("nan"),
            "last": uniq[-1] / 90000 if uniq else float("nan"),
            "maxstep": steps[0][0] / 90000 if steps else 0.0,
            "maxstep_at": (steps[0][1] / 90000, steps[0][2] / 90000) if steps else None,
        }
    return out


def run_once(
    idx: int, outgoing: Path, incoming: Path, run_dir: Path, after: int, shape: dict
) -> str:
    run_dir.mkdir(parents=True, exist_ok=True)
    out_ts = run_dir / "out.ts"
    if out_ts.exists():
        out_ts.unlink()

    graph = test_gst_engine_wsl._paced_filesink_graph(_reload_graph(outgoing, **shape), out_ts)
    reload_path = run_dir / f"rollover{test_gst_engine_wsl.reloadpolicy.DEFERRED_SWITCH_SUFFIX}"
    reload_path.write_text(
        test_gst_engine_wsl.graphmod.graph_to_json(_reload_graph(incoming, **shape)),
        encoding="utf-8",
    )
    assert test_gst_engine_wsl.reloadpolicy.reload_switch_is_deferred(str(reload_path))

    env_extra = {"CIVICAST_STALL_TIMEOUT_S": "600"}
    if shape["debug"]:
        # x2 ran with `basetsmux:7`, which slows the mux thread and widens the
        # window in which an outgoing-tail buffer is still queued on its sink pad
        # when the rebased segment lands.  Two of x2's twelve runs hit the defect.
        env_extra["GST_DEBUG"] = shape["debug"]
        env_extra["GST_DEBUG_FILE"] = str(run_dir / "gst-debug.log")
        env_extra["GST_DEBUG_NO_COLOR"] = "1"

    proc, control, log = test_gst_engine_wsl._launch_worker(
        run_dir,
        graph,
        out_ts,
        env_extra=env_extra,
    )
    rc = None
    try:
        test_gst_engine_wsl._wait_for_log(log, "CTRL first-output:", timeout=30.0)
        test_gst_engine_wsl._send(control, f"reload {reload_path}")
        committed = True
        try:
            test_gst_engine_wsl._wait_for_log(log, "CTRL reload committed", timeout=120.0)
        except Exception as exc:
            print(f"  # COMMIT NEVER HAPPENED: {exc}")
            committed = False
        text = log.read_text(encoding="utf-8", errors="replace")
        commit_at = text.index("CTRL reload committed") if committed else len(text)
        deadline = time.monotonic() + 10.0 * (after + 2)
        while time.monotonic() < deadline:
            text = log.read_text(encoding="utf-8", errors="replace")
            if text[commit_at:].count("[mux-in ") >= after or proc.poll() is not None:
                break
            time.sleep(0.25)
        if proc.poll() is not None:
            rc = proc.returncode
            print(f"  # worker had already exited on its own (rc={rc}); no stop ack expected")
        else:
            try:
                test_gst_engine_wsl._send(control, "stop")
                rc = proc.wait(timeout=30)
            except Exception as exc:
                print(f"  # stop not acked: {type(exc).__name__}: {exc}")
                rc = proc.poll()
    except BaseException:
        # A worker that died before it ever connected leaves the pipe server with
        # nobody to talk to; kill it first so _reap cannot block on the seam.
        if proc.poll() is None:
            proc.kill()
        raise
    finally:
        test_gst_engine_wsl._reap(proc)

    text = log.read_text(encoding="utf-8", errors="replace")
    print(
        f"===== run {idx} rc={rc} committed={committed} out={out_ts.name}"
        f" size={out_ts.stat().st_size if out_ts.exists() else 0}"
    )
    print("  " + _ends(text))
    for line in text.splitlines():
        if "diagnostic" in line or line.startswith("CTRL reload:") or "WARN" in line:
            print("  " + line[:220])

    gt = _gt(out_ts)
    red = False
    for pid, name in ((_PID_VIDEO, "video"), (_PID_AUDIO, "audio")):
        r = gt.get(pid)
        if r is None:
            print(f"  GT {name}: ABSENT from the recorded output")
            if pid == _PID_VIDEO:
                red = True
            continue
        at = r["maxstep_at"]
        print(
            f"  GT {name:<5} n={r['n']:<5} uniq={r['uniq']:<5} regress={r['regress']:<3} "
            f"first={r['first']:.9f} last={r['last']:.9f} maxstep={r['maxstep']:.6f}s"
            + (f"  {at[0]:.9f} -> {at[1]:.9f}" if at else "")
        )
        if pid == _PID_VIDEO and (r["maxstep"] > 1.0 or r["regress"] > 0):
            red = True
    return "COLLAPSE" if red else "ok"


def main() -> int:
    outgoing = Path(str(opt("--outgoing")))
    incoming = Path(str(opt("--incoming")))
    runs = int(opt("--runs", "1") or 1)
    after = int(opt("--after-intervals", "6") or 6)
    tag = opt("--tag", "x4") or "x4"
    run_root = SCRATCH / tag
    shape = {
        "caps": str(opt("--caps", "base")),
        "captions": (opt("--captions", "off") or "off") == "on",
        "repeats": int(opt("--repeats", "1") or 1),
        "debug": opt("--debug", "") or "",
    }
    print(f"# outgoing={outgoing.name} incoming={incoming.name} runs={runs} tag={tag}")
    print(f"# shape={shape}")
    verdicts = [
        run_once(i, outgoing, incoming, run_root / f"run{i}", after, shape)
        for i in range(1, runs + 1)
    ]
    print(f"# verdicts({tag}): {verdicts}")
    n_red = sum(1 for v in verdicts if v == "COLLAPSE")
    print(f"# src-collapse runs: {n_red}/{len(verdicts)}")
    return 1 if n_red else 0


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_rc)
