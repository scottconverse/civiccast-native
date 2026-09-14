# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R12-DB2617.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R12-DB2617.ps1

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
R11 cancelled the 21 remaining R5 rows, then its supervisor-restart shutdown
barrier timed out and left the channel configs disabled. R12 removes that
barrier, recovers enabled command handling with auto-start off while preserving
the complete configs, and uses the earlier proven repeated-stop quiet window.
Its source anchor is e54752b01a537e61315bf957f1136986719189ec, its binding commit is
54acd54ded0cab93813bb55467e167e8c8f8e911, and its harness manifest SHA-256
is d1ddedf06fcf874ff81351c8986b1e75f74b3f85fe3a8f5ba4f072b6ff000731.

Execute the R12 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
