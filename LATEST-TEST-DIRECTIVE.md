# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R9-9DF212.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R9-9DF212.ps1

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
with Settings.Enabled=false. R9 is the new once-only mission. Its source anchor
is 43569b4de7661bb02933cf60a1393af605c6a742, its binding commit is
2509b241115f7bfa9dcc63c4f58710e3c83e9366, and its harness manifest SHA-256
is 03fdccc568ce02485ef89f13f89fe8ea807cbe5c5800d0b1b2c89126cbccf073.

Execute the R9 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
