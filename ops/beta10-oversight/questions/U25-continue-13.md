# U25 - coordinator: LIVE defect in the full-asset ride path after install (00:19, beta10-int 521438fe)

OBSERVED on the station (`C:\ProgramData\CivicCast\logs\control_plane-app.log`), same asset, two paths:

- 00:22:12 WINDOW path, `Senior Citizens Advisory Board - June 2026.mp4` in=3186.8s dur=1800s:
  round 0 at -1.50 dBTP ceiling -> -0.80 dBTP emitted, peak -0.98 dBFS, loudness ok. Kept. Normal.
- 00:37:42 FULL-ASSET path (warm), same asset:
  round 0 at -1.50 dBTP ceiling -> **+2.60 dBTP emitted, peak +0.78 dBFS** (over the +0.1 bound);
  round 1 at -5.40 dBTP -> -1.90 dBTP, peak -1.89 dBFS, **loudness gate failed**; kept round 0 with an ERROR.

A 4.1 dB overshoot of a -1.5 dBTP brickwall ceiling is not AAC codec overshoot (your panel: <= ~1 dB). On the same
source the window path is fine, so something specific to the full-asset path is applying gain after the limiter,
bypassing it, or measuring/limiting a different signal than it emits (candidates to rule in/out with measurements,
not argument: a gain/trim stage after the limiter; the incumbent loudnorm or volume filter still in the full-asset
filter graph; limiter lookahead/state reset across chunk boundaries of a long file; a sample-rate/channel-layout
conversion after limiting; the correction trim applied after the render on this path only).

## Work (in `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-u25fix` - branch `beta10-u25fix` @ `521438fe`, already created by the coordinator; create and sync its own `.venv`)
1. Reproduce on the real asset (find it via the station DB read-only / media library path) through the full-asset
   path with the station ffmpeg first on PATH (build the env in Python, as U40 did). Print the peak and TP after each
   stage of the chain to locate where +4 dB appears. Report the root cause with file:line.
2. Fix it so the full-asset path behaves like the window path (same ceiling -> same class of emitted TP). Tests red
   then green, including a unit test that pins the stage order and one real-ffmpeg test on a synthetic signal that
   reproduces the overshoot at the old code.
3. Re-run the full-asset path on this asset + the 7-cell panel's BIG cell: loudness gates + hard bound must pass.
4. Gates (check no other `pytest tests/egress` is running first): full egress suite, ruff, mypy on changed files.
   Small commits, never amend. Then stage `staging\U42` exactly as U40 staged (base = live preparer.py
   `676A0076...` and loudness_ride.py `57B9A387...` if touched; candidate == HEAD; no __pycache__). Do not install.
Report in `reports\U42.md`. STOP only if the root cause is outside the ride (then report numbers).
