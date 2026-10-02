# U48 (U45 session) - rung instrument fix: a transient playlist read error was scored as a loudness FAIL

OBSERVED, `evidence\rung-8h-post-u44-20260926-123748\loudness-01.json` public: status FAIL, blocking_reasons
`playlist unreadable: [Errno 13] Permission denied: ...live-hls\public\playlist.m3u8`, captured 188.0 s of 240,
audio_window "capture structurally invalid; no loudness verdict issued". The relay replaces playlist.m3u8 atomically;
a read racing the replace on Windows gets EACCES. Then rung_check/adjudicator printed
`public=FAIL(only 0s of 188s missed ... the station did not correct it)` - wrong: there was no loudness measurement.

## Work (oversight + measurement scripts only; no product code, no install, no station restart)
1. `C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds\scripts\capture_emitted_hls_audio_proof.py` and
   `verify_beta10_live_hls_media.py`: every read of playlist.m3u8 (and of a segment) retries on PermissionError /
   FileNotFoundError up to 20 times, 100 ms apart, then fails as today. Open, read fully, close at once (no held
   handle - see the Live-station read rule in PROJECT-BRIEF.md). Unit tests for the retry (simulated EACCES x3 then
   success -> success; x25 -> the existing failure).
2. `bin\rung_check.py` + adjudicator: a channel whose capture has no loudness measurement (blocking_reasons or no
   integrated_lufs) is `INSTRUMENT_ERROR(<reason>)`, never a loudness FAIL; the rung verdict treats it as FAIL of the
   instrument (it still fails the rung - no evidence is not a pass) but the line must say INSTRUMENT_ERROR. Re-run on
   the file above -> `public=INSTRUMENT_ERROR(...)`; on pre-u44 loudness-01/-02 -> unchanged output.
3. Replace files atomically (the running rung calls these per run). Report `reports\U48.md`.
