# U49 (U45/U48 session) - on-air true-peak overshoot: find the stage that adds it, fix it, prove it

U48 delivered and audited. Coordinator note: I tightened `bin\rung_check.py` so CAPTION_QUIET needs a fresh OK worker
receipt AND an integer cue count (absent evidence now FAILs). Do not undo that.

## Observed (emitted HLS, capture_emitted_hls_audio_proof.py, true_peak_dbfs; limit +0.1)
| run | education | government | public |
|---|---|---|---|
| pre-u44 loudness-02 | **+0.4** | -0.9 | -0.7 |
| post-u46 loudness-01 | -0.1 | -1.3 | **+0.5** |
| post-u44 loudness-01 | **+0.7** | -1.2 | n/a |
| post-u44 loudness-02 | -0.0 | -0.8 | -0.6 |
Integrated loudness in all of these is within -16 +/- 1. The prepared (conform-cache) files were already fixed for
AAC overshoot (loudness-compensated pad round + trim correction, U4x) - so the overshoot is being added AFTER prep:
the playout ride gain (loudness_ride, g_max 18 dB), mixing/switching, or the live AAC encode.

## Work
1. Locate the stage. Measure true peak (ffmpeg ebur128 peak=true, 4x oversampled) on, for one channel that overshot:
   (a) the conform-cache `.ts` of the item that was airing, (b) the worker's pre-encode PCM if you can tap it offline with
   the real worker pipeline on a copy of that item (NO live-station taps; Live-station read rule in PROJECT-BRIEF.md
   applies - copy finished segments to %TEMP% before opening), (c) the emitted segments. Report the three numbers.
2. Fix at the stage that adds it. Expected shape: a true-peak limiter (ceiling -1.0 dBTP pre-encode, lookahead) after the
   ride gain and before the AAC encoder, so the encoder's inter-sample overshoot lands under +0.1. Do not change the
   loudness target or the ride's g_max. Loudness must stay -16 +/- 1.
3. RED first: a test that drives the real worker pipeline (or the smallest real element chain) with a fixture that
   overshoots today, asserting emitted true peak <= +0.1 dBTP and integrated within -16 +/- 1; show it fail on HEAD,
   pass on the fix. Include a CPU cost note (3 channels on this box).
4. Stage for install as usual: `staging\U49\candidate\...` + `installed-base.sha256` lines `<sha> *civiccast/<rel>`
   hashed from the LIVE installed files. No install, no service restart - the coordinator installs.
Report `reports\U49.md`, receipt line at the end.
