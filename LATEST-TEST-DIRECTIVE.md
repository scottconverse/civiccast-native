# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R7-E6D01E.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R7-E6D01E.ps1

Candidate: 3e117ff1fa9e06873ecec5b5b07f1360bc8b228d, build 34762831824,
Gate A PASS run 34772707033. Captions are OFF. The measured gate is exactly
four hours on DESKTOP-VBMA6O5.

R5 is invalidated at tester evidence commit
0c90c8bce3f0cbe36af9671a5bbea91116d832a6. R6 stopped in package preflight
before creating a mission root or changing the station because it required
PowerShell 7 on the Windows PowerShell 5 tester. R7 is the new once-only
mission. Its source anchor is
9b4c3201a950231d0a1a3584447480a99d87a1e9, its binding commit is
4b4be0b5e29ce3a4d377f4b750b033e4f4cb037c, and its harness manifest SHA-256
is 41203fb96115b72655d67a21338ed2ca428aceb7a1f915a642de1a6eb0938954.

Execute the R7 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
