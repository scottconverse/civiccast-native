# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R13-A73C91.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R13-A73C91.ps1

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
barrier timed out and left the channel configs disabled. R12 repaired that
barrier and reached complete controlled programme changes on all three
channels. It then falsely failed because it treated beta.5's `elements=146`
graph size as universal. The exact beta.7 captions-OFF evidence instead proves
healthy `elements=132` twelve-segment slate graphs and healthy `elements=33`
one-segment programme graphs, with complete preroll and handoff receipts plus
continued output. R13 binds that R12 evidence hash and corrects only the stale
topology rule while retaining worker-exit, missing-preroll, output-stall,
wrong-source, missing-PID, `56`/`74`, and transport failures.

R13's source anchor is dedc03471a492a973efd73eb34d903dded2ee5ed, its binding
commit is 8bd7bbb236bdf4a6602bd30b44c5f2b31f0677d1, and its harness manifest
SHA-256 is 56dea7b20562bad3a9ad8ef81c9103408310c47dc8f961c66623f7cadcb233c6.

Execute the R13 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
