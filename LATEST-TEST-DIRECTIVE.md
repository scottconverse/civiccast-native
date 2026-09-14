# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R11-7C1698.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R11-7C1698.ps1

Candidate: 3e117ff1fa9e06873ecec5b5b07f1360bc8b228d, build 34762831824,
Gate A PASS run 34772707033. Captions are OFF. The measured gate is exactly
four hours on DESKTOP-VBMA6O5.

R5 is invalidated at tester evidence commit
0c90c8bce3f0cbe36af9671a5bbea91116d832a6. R6 stopped in package preflight
before creating a mission root or changing the station because it required
PowerShell 7 on the Windows PowerShell 5 tester. R7 stopped later in read-only
adoption preflight at `directive-package-clean`: its Windows-to-Git path
conversion treated a lone backslash as a regular expression. R8 stopped before
station mutation because it incorrectly required a currently executing disabled
Scheduled Task to report state Disabled; Windows correctly reports state Running
with Settings.Enabled=false. R9 stopped after publishing STARTED because the
outer launcher compared the adoption-updated receipt with its stale pre-adoption
identity. R10 passed that corrected remote-start gate, then stopped before
measurement because the physical job did not pass the exact invalidated R5 plan
IDs into its bounded schedule replacement path. R11 verifies the receipt-bound
R5 plan hash and its 180 unique schedule IDs, then permits cancellation only for
live overlaps in that exact set. Any unrelated row fails before cancellation.
Its source anchor is bb1f7e5c7354a9f7b13dca2f26f0012027ed0fc8, its binding commit is
38d6e565e70d15b9a866986a42339f5b249920c4, and its harness manifest SHA-256
is 49fb0381d224734d1392e4c67d2648d2465152c1edc0c7353ccded2635c37100.

Execute the R11 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
