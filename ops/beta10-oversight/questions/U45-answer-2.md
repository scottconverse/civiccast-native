# U45 - coordinator: tighten the exclusion predicate (coordinator call, final)

Verified: rung_check on `rung-8h-pre-u44.../loudness-01.json` -> public EXCLUDED_QUIET_SOURCE (src45min -37.27,
srcspan -26.64, maxreach -19.27, air -17.6); loudness-02 PASS. Good work.

Problem: the predicate keys on the QUIETEST 45 s source window. One quiet 45 s moment would excuse a whole 240 s window
whose other 195 s the station could have corrected. The owner's rule is "not a fail only when the station could not
have fixed it". New predicate:
- For each second of the 240 s window, take the 45 s source window centred on it (the ride's own window), and mark the
  second UNREACHABLE iff source_45s_lufs + g_max_db < target - tol.
- EXCLUDED_QUIET_SOURCE iff UNREACHABLE seconds >= 60 (a quarter of the window) - report the count in the line.
- Otherwise FAIL stands.
Re-prove on loudness-01 (expect EXCLUDED with the count, your U45 Part I measured ~119 s at g_max) and on the synthetic
loud case (FAIL). The running rung calls rung_check.py per loudness run - replace the files atomically (write temp,
rename) and do not touch the rung process. Append to `reports\U45.md`.
