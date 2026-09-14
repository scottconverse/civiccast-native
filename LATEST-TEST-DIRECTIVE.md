# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R8-4B387C.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R8-4B387C.ps1

Candidate: 3e117ff1fa9e06873ecec5b5b07f1360bc8b228d, build 34762831824,
Gate A PASS run 34772707033. Captions are OFF. The measured gate is exactly
four hours on DESKTOP-VBMA6O5.

R5 is invalidated at tester evidence commit
0c90c8bce3f0cbe36af9671a5bbea91116d832a6. R6 stopped in package preflight
before creating a mission root or changing the station because it required
PowerShell 7 on the Windows PowerShell 5 tester. R7 stopped later in read-only
adoption preflight at `directive-package-clean`: its Windows-to-Git path
conversion treated a lone backslash as a regular expression. R8 is the new
once-only mission. Its source anchor is
5c254228d2eda991dc61ce3d61633bafc68c3da1, its binding commit is
05f0225a8f0789010dceeb6c14f03a980611244c, and its harness manifest SHA-256
is 217d7f390602a3b23bc0680201fa6148d5025bb898237cbc5f5e2087aaac2401.

Execute the R8 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
