# U42 - coordinator answer: engineering call, not a product question. Build E via A/B as encoder variants inside the guard. Plus the 300 s full-asset timeouts.

Your stage accounting is accepted (s4 -1.500, s5 -1.490, s6 +0.783; state-dependent AAC excursion, left channel only).
Codec settings are an engineering call and mine. Decisions:

1. **Guard re-emit varies the ENCODER, not only the ceiling, when the hard bound is missed.** When the kept attempt's
   decoded peak is above `TP_GUARD_MAX_PEAK_DBFS`, re-encode ONLY the AAC + mux from the same already-limited PCM
   (s5; no re-render, no re-convergence), in this order, stopping at the first that meets the bound:
   (a) `-b:a 256k`, (b) `-b:a 256k -aac_coder fast`. Measure each exactly as today and feed all attempts to the
   existing keep-best selector (unchanged ordering: loudness gates, then lowest decoded peak, then lowest TP). If
   every attempt misses the bound, ship the best with the existing ERROR line. The profile default (192) is NOT
   changed; nominal emission is unchanged, so the panel's nominal numbers stand. Name each attempt's encoder
   settings in the WARNING/ERROR text. The bound stays +0.1 dBFS, enforced by selection, reported when unmet.
2. **Prove the air path tolerates a 256 kbps audio artifact inside a 192 kbps profile.** Show from code (file:line)
   what happens to the artifact's audio on air (copied into the mux, or decoded and re-encoded) and add a test that
   an artifact with the variant bitrate prepares, validates and is accepted by the same checks as a nominal one.
   If anything downstream rejects or mis-handles it, STOP with the evidence.
3. **The full-asset timeouts** (log lines 19035, 19464 "unknown duration, allowed 300s to conform", 20328, and the
   pre-install 14674/16230 loudnorm measurement on 2.5 h assets): find why the warm path runs with an unknown
   duration and the flat 300 s bound instead of U29's scaled warm bound, fix it so the duration is probed and the
   bound scales (ride included - BIG measured 369 s nominal + guard <= 240 s), tests red then green. The air path
   keeps its bound unchanged.
4. Then items 2-4 of `U25-continue-13.md`: red/green (unit test pinning the encoder-variant order with the
   adverse shape; one real-ffmpeg test re-encoding the anchored 1212 s prefix PCM - or a shorter slice that still
   reproduces the excursion - showing the bound met by variant (a) or (b)); re-run the full-asset path on the
   Senior Citizens asset end to end with the station ffmpeg first on PATH (bound met; loudness gates pass; elapsed
   within the new scaled bound); gates after checking no other `pytest tests/egress` is running; small commits on
   `beta10-u25fix`; stage `staging\U42` like U40 (base = live preparer.py `676A0076...`, loudness_ride.py
   `57B9A387...`; candidate == HEAD; no __pycache__). Do not install. Report in `reports\U42.md` (append a section).
Keep the evidence runs lean: one ffmpeg at a time, no panel re-run beyond the Senior Citizens asset.
