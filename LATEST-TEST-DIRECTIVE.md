# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF4H-R6-C09F7E.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R6-C09F7E.ps1

Candidate: 3e117ff1fa9e06873ecec5b5b07f1360bc8b228d, build 34762831824,
Gate A PASS run 34772707033. Captions are OFF. The measured gate is exactly
four hours on DESKTOP-VBMA6O5.

R5 is invalidated at tester evidence commit
0c90c8bce3f0cbe36af9671a5bbea91116d832a6. R6 is a new once-only mission.
Its reviewed package is staged at directive commit
b4a8a10107cafcdc6a461349040406696ec1cadf, with source anchor
4518232b77e5f6cd8059fa55a5fbfa9b2ec33c2e, binding commit
bb501893db0a85a3fb973995455339b2dd9789f8, and harness manifest SHA-256
6d671e417ce561cb370d5b635bbb67c607845ac59c059a2db26ed5caf5bf3b00.

Execute the R6 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
