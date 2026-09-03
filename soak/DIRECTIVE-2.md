# DIRECTIVE-2 — HOLD the soak clock (2026-09-03 20:15Z)

Nothing for you to do. This is a coordinator note.

The kit you are installing (b78b9c7) has a GStreamer worker bug found by Gate A
at 19:56Z: the worker crashes on import and every channel would fall back to
ffmpeg. An 8-hour soak on ffmpeg proves the wrong thing, so AUTORUN-2 (start
channels) and AUTORUN-3 (verify + 8-hour verdict) are pulled off the queue until
the fixed kit is built. They are parked in `soak/held/`.

What happens next, automatically:
1. AUTORUN-1 finishes installing b78b9c7 (fine; it is a valid upgrade step).
2. The coordinator ships a fixed kit; a new AUTORUN-2 will fetch and install it
   over this one, then AUTORUN-3/4 start the three GStreamer channels and the
   8-hour clock.

Keep polling and heartbeating.
