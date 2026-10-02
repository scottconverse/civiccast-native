# U45 - coordinator answer 3: deliver, with the measured count deciding and the range printed

Decisions (final):
1. The verdict uses the count at the MEASURED alignment position (62/240 here -> EXCLUDED_QUIET_SOURCE). No UNRESOLVED
   verdict.
2. The line always prints `unreach=<n>/<scorable>s (range <lo>-<hi>, need 60)`. When the range straddles 60, append
   `BORDERLINE` to the line; the coordinator reviews every BORDERLINE window by hand in the 30-min report.
3. Threshold stays 60 s of the SCORABLE seconds' 240-s basis as ordered (unscorable edges: count them in the line, do
   not rescale - revisit only if one bites).
Deliver `%TEMP%\u45p3\new\*` into `bin\` atomically (temp + rename; the running rung calls rung_check per loudness run),
re-run on loudness-01 (expect EXCLUDED ... unreach=62/240 ... BORDERLINE) and loudness-02/-03 (unchanged), print the new
bin\ hashes, append to reports\U45.md. Nothing else.
