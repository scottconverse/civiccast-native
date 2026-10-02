# U42 - coordinator: installed 03:59; the variants help but do not reach the bound on the worst cell. Part III.

OBSERVED live after install (04:04:40), `Senior Citizens Advisory Board - June 2026.mp4` window in=23.7412 dur=1800:
round 0 aac 192k -1.50 -> +3.10 dBTP, peak +2.85; round 1 192k -5.90 -> peak -1.28, loudness FAILED;
round 2 aac 256k -1.50 -> +1.70 dBTP, peak +1.74; round 3 256k fast -1.50 -> +0.90 dBTP, peak +0.86. Kept round 3, ERROR.
So on this material the AAC round trip adds ~+4.3 dB to a -1.5 dBFS limited signal - far beyond the ~1 dB class.

Hypothesis to MEASURE (not argue): the encoder band-limits (its lowpass / psychoacoustic HF removal), and band-
limiting a brickwall-limited signal that carries strong HF (clicks, sibilance, clipped source) rebuilds the peaks the
limiter removed. The standard fix is to band-limit BEFORE the limiter so the limiter sees what the encoder keeps.

## Work (same worktree `civiccast-ds-u25fix`, branch `beta10-u25fix` @ 9fc85688; station ffmpeg first on PATH)
1. On this cell's s5 PCM (in=23.7412 dur=1800) measure: the encoder's effective cutoff at 192k/256k (spectrum of
   the decoded artifact vs s5), and the peak after applying only that lowpass to s5 (no encode). If the lowpass alone
   reproduces most of the overshoot, the hypothesis holds.
2. If it holds: put a lowpass at (or just under) the encoder's cutoff for the emitted bitrate in the ride chain
   BEFORE `alimiter` (inside the 192 kHz oversampled section), measure all three live cells (this one; Senior full
   asset; Sustainability in=2469.72 dur=1800) at 192k nominal: loudness gates + hard bound. Report the table incl.
   render time. If the nominal 192k attempt meets the bound on all three, keep the variants as a backstop.
   If it does not hold: STOP with the measurements and your best alternative (measured).
3. The change alters the ride's audio, so bump the ride's cache version constant (e.g. `loudnorm-v3-ride` ->
   `-v4-ride`) so every artifact re-prepares under it. Tests red then green (unit: stage order pins the lowpass
   before the limiter; real-ffmpeg: a synthetic HF-rich limited signal that overshoots at the old chain meets the
   bound at the new one). Gates after checking no other `pytest tests/egress` is running. Small commits.
   Stage `staging\U43` like U42 (bases = live preparer.py `403C8C78...`, loudness_ride.py `798923B3...`;
   candidate == HEAD; no __pycache__). Do not install. Append Part III to `reports\U42.md`.
Keep runs lean: one ffmpeg at a time, BELOW_NORMAL priority (the station is live).
