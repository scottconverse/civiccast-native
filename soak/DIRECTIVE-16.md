# Retrieve the R3 stall logs without hashing open files

Directive 15 ran once and is preserved. Its read-only diagnostic stopped when
Windows refused Get-FileHash on an append-open worker log. It did not change the
station. This is a diagnostic collection failure, not another product result.

Execute AUTORUN-SEP12-FIXED-BETA-R3-FAILURE-DIAGNOSTIC-R2.ps1 once. R2 performs
the same bounded read-only collection but records file length and last-write time
without hashing the append-open logs. It does not call the CivicCast API, read or
publish tokens, start or stop channels, alter schedules, change tasks, replay a
soak, or remove any once-only marker.

Preserve every prior receipt and the three CivicCastSoak coordination tasks.
Do not restart a soak. beta.5 and beta.6 remain rejected; the next candidate is
beta.7 with a new source SHA and artifact identity.
