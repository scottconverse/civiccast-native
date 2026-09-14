# Invalidate beta.7 R5 physical test

Target: `DESKTOP-VBMA6O5`

Invalid mission: `BETA7-3E117FF1-OFF4H-R5-E27A91`

R5 is not release evidence. Independent review found both false-pass and
guaranteed-false-fail defects after it had started. This once-only order stops
and disables the R5 task, proves its process is gone, invalidates the remote
job record, cancels only schedule rows bound to R5's own run identity and
published plan, and leaves all three owned channels enabled, stopped, and with
`auto_start=false`.

No replacement soak is authorized by this directive. A separately reviewed
mission with a new nonce is required.
