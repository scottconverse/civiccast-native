"""changeover_hole_watch.py - after each seamless reload commit, measure the picture across the switch.

Read-only.  Polls each channel's gst-worker.stderr.log for a new 'stage=committed' line; 75 s later
(the keeper lags the live playlist by ~3 segments) plain-copies the newest 40 keeper segments from
%TEMP%\\cc-caption-keep\\<ch>\\ and scans every segment's own video/audio packet PTS for the largest
intra-segment step.  A healthy 30 fps step is ~3001 ticks; anything > 2 frames is a hole.  Never opens
live-hls.  Prints one line per changeover: 'HOLE ...' or 'CLEAN ...'.
"""
import os, re, shutil, subprocess, sys, tempfile, time

EGRESS = r"C:\ProgramData\CivicCast\data\egress"
KEEP = os.path.join(os.environ["TEMP"], "cc-caption-keep")
FFPROBE = r"C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe"
CHANNELS = ("public", "government", "education")
DELAY_S, COPY_N = 60, 200
VIDEO_HOLE_S, AUDIO_HOLE_S = 0.070, 0.050


def committed_count(ch):
    try:
        with open(os.path.join(EGRESS, ch, "logs", "gst-worker.stderr.log"), "rb") as f:
            return f.read().count(b"stage=committed")
    except OSError:
        return 0


def pts(path, stream):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", stream, "-show_entries",
                          "packet=pts_time", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return sorted(float(x.split(",")[0]) for x in out.split() if x and x.split(",")[0] != "N/A")


def max_step(ts):
    return max(((b - a), a - ts[0]) for a, b in zip(ts, ts[1:])) if len(ts) > 1 else (0.0, 0.0)


def scan(ch, tag):
    src = os.path.join(KEEP, ch)
    names = sorted(n for n in os.listdir(src) if re.match(r"seg\d+\.ts$", n))[-COPY_N:]
    dst = tempfile.mkdtemp(prefix=f"cohw-{ch}-{tag.replace(':', '')}-")
    for n in names:
        shutil.copy2(os.path.join(src, n), dst)
    worst_v, worst_a = (0.0, 0.0, ""), (0.0, 0.0, "")
    # C11 06:24 lesson: a hole can straddle a segment boundary, so also measure the step from each
    # segment's last packet to the next segment's first packet (reported as "<prev>|<next>").
    prev_v = prev_a = None
    for n in names:
        p = os.path.join(dst, n)
        vt, at = pts(p, "v:0"), pts(p, "a:0")
        v, a = max_step(vt), max_step(at)
        if v[0] > worst_v[0]:
            worst_v = (v[0], v[1], n)
        if a[0] > worst_a[0]:
            worst_a = (a[0], a[1], n)
        if vt and prev_v and vt[0] - prev_v[1] > worst_v[0]:
            worst_v = (vt[0] - prev_v[1], 0.0, f"{prev_v[0]}|{n}")
        if at and prev_a and at[0] - prev_a[1] > worst_a[0]:
            worst_a = (at[0] - prev_a[1], 0.0, f"{prev_a[0]}|{n}")
        prev_v = (n, vt[-1]) if vt else prev_v
        prev_a = (n, at[-1]) if at else prev_a
    bad = worst_v[0] > VIDEO_HOLE_S or worst_a[0] > AUDIO_HOLE_S
    # C5 (U56c): the engine's own switch-point line for this changeover, if it printed one.
    shorter = ""
    try:
        with open(os.path.join(EGRESS, ch, "logs", "gst-worker.stderr.log"), "rb") as f:
            body = f.read()
        hits = re.findall(rb"switch-at-shorter-leg [^\r\n]*", body)
        # which outgoing stream EOS'd first at this changeover (U56 round 6 lead)
        firsts = re.findall(rb"outgoing EOS observed stream=(\w+) \(1/2", body)
        if firsts:
            shorter_first = f" | first_eos={firsts[-1].decode()}"
        else:
            shorter_first = ""
        if hits:
            m = re.search(rb"trimmed=(\S+) spread=(\S+).*bound_exceeded=(\S+)", hits[-1])
            shorter = " | " + (m.group(0).decode() if m else hits[-1][:160].decode(errors="replace")) + shorter_first
    except OSError:
        pass
    # C6 (U56d): the relay's own view of a rewind -- ffmpeg logs 'Invalid timestamps' for every
    # backward packet it receives; count the new ones since this channel's previous changeover.
    rewind = ""
    total = relay_invalid_count(ch)
    if total is not None:
        new = total - RELAY_SEEN.get(ch, total)
        if new < 0:  # the relay log rotated or restarted: everything in it is new
            new = total
        RELAY_SEEN[ch] = total
        rewind = f" | relay_invalid_ts_new={new} (~{new * 0.021333:.3f}s audio)"
    return (f"{'HOLE' if bad else 'CLEAN'} {ch} commit@{tag} segs={names[0][3:-3]}-{names[-1][3:-3]} "
            f"video_max={worst_v[0]:.3f}s in {worst_v[2]} at +{worst_v[1]:.3f} "
            f"audio_max={worst_a[0]:.3f}s in {worst_a[2]}{shorter}{rewind}")


RELAY_SEEN = {}


def relay_invalid_count(ch):
    total, found = 0, False
    logs = os.path.join(EGRESS, ch, "logs")
    try:
        names = [n for n in os.listdir(logs) if n.startswith("hls-relay.") and n.endswith(".stderr.log")]
    except OSError:
        return None
    for n in names:
        try:
            with open(os.path.join(logs, n), "rb") as f:
                total += f.read().count(b"Invalid timestamps")
                found = True
        except OSError:
            pass
    return total if found else None


def main():
    end = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 1740)
    seen = {c: committed_count(c) for c in CHANNELS}
    for c in CHANNELS:
        t = relay_invalid_count(c)
        if t is not None:
            RELAY_SEEN[c] = t
    due = []
    while time.time() < end or due:
        for c in CHANNELS:
            k = committed_count(c)
            if k > seen[c]:
                seen[c] = k
                due.append((time.time() + DELAY_S, c, time.strftime("%H:%M:%S")))
        for item in [d for d in due if d[0] <= time.time()]:
            due.remove(item)
            try:
                print(scan(item[1], item[2]), flush=True)
            except Exception as exc:  # report, never die silently
                print(f"ERROR {item[1]} commit@{item[2]}: {exc!r}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
