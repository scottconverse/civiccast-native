# soak8-e1acfe6 Latest Test Directive

Current: `soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R5-E27A91.md`

Autorun: `soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R5-E27A91.ps1`

Candidate: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`, build `34762831824`,
Gate A PASS run `34772707033`.
This is a fresh once-only retry after R4 installed and verified beta.7, then failed before measurement because its stop gate raced the enabled auto-start policy. R5 first preserves and verifies each full channel config while setting `enabled=true` and `auto_start=false`, then keeps issuing terminal stops until all three channels remain exact `STOPPED` with no worker PID for a four-second quiet window. It uses the corrected R6 TSDuck acquisition window. The exact-candidate captions-OFF topology is bound to `[33]`
for all three channels from preserved passing Sandbox evidence. Gate A is
bound to the exact three passing lane artifacts. Live captions are outside the
beta release gate; offline after-hours captions suffice.

The failed R3 and R4 missions, their completion markers, state, and evidence remain preserved. Previous directives are not active orders.
