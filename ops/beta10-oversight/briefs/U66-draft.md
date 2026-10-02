# U66 (DRAFT, dispatch after U65) - rung loudness adjudicator: position must not come from a multi-part log guess

Oversight tooling (bin/rung_check.py, bin/loudness_window_adjudicate.py), not station code.
Incident: C15 loudness #9 (07:18) - T2 log position 3226.3 s, true 7206 s (U64 + coordinator re-measure); no --air-audio
was passed so T1 never ran; even with air audio, REF_WINDOW_S=900 around a T2 that is ~3900 s off would not find it.

Work:
1. rung_check.adjudicate(): for each non-PASS channel, concat that channel's captured snapshot segments (loudness json
   `segments[].snapshot_path`, while they still exist) to one audio file and pass `--air-audio CH=path`.
2. adjudicator T1: if the +/-900 s correlation fails, retry against the WHOLE asset (cached ebur128 series, idle
   priority) before falling back to T2. Correlate on the loud part of the window if the quiet part will not lock
   (U64 notes a quiet head correlates badly: disjoint-slice agreement is the acceptance test).
3. If T1 still fails and the channel aired the same asset across more than one plan rollover before the window
   (T2 > ~1800 s or rollover lines for that asset), classify BORDERLINE "position unresolved: multi-part asset, log
   position unreliable" - a human reads it; never FAIL or EXCLUDE on T2 alone in that case.
4. Tests: replay loudness-09.json with the August 11 source -> must land at ~7121 s and EXCLUDED_QUIET_SOURCE;
   a synthetic single-part case must still use T2 unchanged.
