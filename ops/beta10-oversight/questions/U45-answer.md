# U45 - owner answered: option 1 (your option 2). Build it into the rung's loudness scoring.

Scott's decision (final): the -16 +/- 1 LUFS 240 s window criterion stays for program speech. A window is NOT a fail
when the station is already at its maximum lift on quiet/low-speech source it cannot legally correct; every such window
is listed in the rung report with its numbers.

## Work (oversight tooling only - no product code, no install, no station restart)
1. Write `bin\loudness_window_adjudicate.py`: input = a rung `loudness-NN.json` + the control-plane log; for each FAIL
   channel window: find the aired asset and the asset position (your U45 alignment method, automated), measure the
   SOURCE integrated loudness over that span (copy-based, station ffmpeg, BELOW_NORMAL, one at a time - READ the
   Live-station read rule in PROJECT-BRIEF.md: never open live-hls with ffmpeg), and classify:
   `EXCLUDED_QUIET_SOURCE` iff source_lufs + g_max_db (read from the installed loudness_ride.RideParams) < target - tol
   (i.e. even the maximum lift cannot reach -17); else `FAIL`. Output JSON + a one-line summary per window.
2. Wire it into `bin\rung_check.py loudness` so a FAIL window is re-scored by the adjudicator and the rung verdict uses
   the adjudicated status; the line in rung.log names every EXCLUDED window with asset, position, source LUFS, air LUFS.
3. Prove it: on `evidence\rung-8h-pre-u44-20260926-101439\loudness-01.json` public -> EXCLUDED_QUIET_SOURCE with the
   numbers you measured; on a synthetic JSON where the source is loud enough -> FAIL stays FAIL. Report `reports\U45.md`
   (append Part II). Do not touch the running rung process.
