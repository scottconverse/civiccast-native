# Beta.7 `3e117ff1` dedicated physical tester mission

Status: **R11 ONCE-ONLY PHYSICAL MISSION; BETA.7 REMAINS UNPUBLISHED**. R5 is
invalid evidence. It contained false-pass paths, a stale auto-start race, an
impossible transport cadence, and a TSDuck `skip` plugin call that does not
exist on the tester. R6 stopped in preflight before it created a mission root,
changed a schedule, or started a channel because its package test required
PowerShell 7 (`pwsh`), which is not installed on `DESKTOP-VBMA6O5`. R11 keeps
the dual-runtime package proof as an explicit coordinator-side test and runs
tester preflight in the tester's current Windows PowerShell 5 runtime. The
tester-live upgrade and task-start paths are forbidden from requesting the
coordinator-only dual-runtime mode. R11 may run exactly once from its
manifest-bound package and the verified R5 invalidation receipt. Preserve its
result whether it passes or fails; any corrected rerun requires a new mission
nonce.

R7 also stopped before creating a mission root, schedule, task, or channel. Its
installed-byte adoption reached `directive-package-clean` and then used a lone
backslash as a PowerShell regular expression while converting a Windows path to
a Git path. R11 uses literal string replacement and executes that exact source
assignment as a regression fixture under Windows PowerShell 5 and PowerShell 7.

Gate A run `34772707033` passed all three lanes,
and `run-identity.json` binds each lane's artifact ID, artifact digest, and inner
verdict hash. This mission does not claim an exact-candidate Sandbox topology
artifact that the package cannot prove. It binds the preserved physical
historical Blackwell baseline archive where healthy programme reloads were
`elements=146` and failed clean-exit runs committed `33`, `56`, or `74`. Because
caption/tap topology can differ by host configuration, the current captions-OFF
tester must record its caption/tap configuration and re-establish a complete
`146`-element transaction on every channel before measured time. A mismatch is
a preflight/configuration failure and never a four-hour product verdict.
Live captions are outside this beta gate; offline after-hours captions suffice.

Known immutable identity:

- source: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`
- successful signed build: `34762831824`
- whole-kit manifest SHA-256: `2af18a8f5bea094cdf7af248eae04be58501e8a390a3099450500819e38d8eb8`
- installer SHA-256: `07fc5259514a3e98164869efbbd9c5bdfb7d83dfe6a96c61d15795c6ace77a97`
- version: `1.0.0-beta.7`
- expected Authenticode status/signer: `Valid` / `Scott Converse`
- Gate A PASS run: `34772707033`
- nonce: `BETA7-3E117FF1-OFF4H-R11-7C1698`

The mission adopts the exact beta.7 installation already byte-verified by R5,
after independently rechecking the running version, service path, candidate
runtime hashes, R5 invalidation receipt, and signed-kit identity. It does not
spend another hour reinstalling identical bytes. It creates a fresh schedule
and runs 240 measured minutes captions OFF.

The physical driver first requires 30 continuous seconds of ON_AIR state with
the same live worker PIDs. It then uses the 30-second TSDuck probe that passed
on all three R5 channels. It does not call the unavailable `skip` plugin. Admission and eight
serialized measured rounds per channel use explicit feasible offsets from 0
through 210 minutes. Measured sync, transport, and continuity errors remain
zero tolerance.

Embargo rows are excluded from airtime overlap checks, matching the product
API. Only live premiere intervals conflict. Every new schedule row is fetched
back and must exactly match the published five-minute R11-owned plan. Final
cleanup and evidence publication are part of acceptance; either failure makes
the job fail. The three `CivicCastSoak-*` coordination tasks are required and
preserved.
