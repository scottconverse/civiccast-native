# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-3E117FF1-OFF8H-R16-7B9E52.md

Autorun: soak/autorun/AUTORUN-BETA7-3E117FF1-OFF8H-R16-7B9E52.ps1

Run the exact beta.7 candidate's final eight-hour captions-OFF physical soak on
`DESKTOP-VBMA6O5`. Candidate source is
`3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`; build run `34762831824` and Gate A
run `34772707033` passed. R15's completed four-hour product evidence has been
independently recovered and graded PASS; its historical job receipt remains
FAIL because the old collector misread normal log rotation.

R16 preserves the product gate and adds rotation-aware log collection. Its
source anchor is `e84b7a3a43e17b851476549df1d55ba87406dff5`, binding commit is
`8eec10107839e76e1bffa5a2fe5eaec728501481`, and harness manifest SHA-256 is
`b839d948fa21be1d3054bbe3561c240f81be204b968685e9ab3d9e9a6acb7baf`.

The order must run once, measure 480 minutes after admission, keep captions OFF,
run sixteen serialized transport rounds, and return success only after its exact
STARTED receipt is published and remotely verified. Preserve all evidence.
