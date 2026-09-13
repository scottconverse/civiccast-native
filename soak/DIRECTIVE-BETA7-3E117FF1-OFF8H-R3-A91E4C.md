# Beta.7 `3e117ff1` physical tester 8h captions-OFF mission

Run only `soak/autorun/AUTORUN-BETA7-3E117FF1-OFF8H-R3-A91E4C.ps1`
once on `DESKTOP-VBMA6O5`. Its exact nonce is
`BETA7-3E117FF1-OFF8H-R3-A91E4C`. Preserve all earlier beta.5, beta.6, and
beta.7 evidence and all poller completion markers.

The candidate is exact source
`3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`, signed build `34762831824`,
whole-kit manifest SHA-256
`2af18a8f5bea094cdf7af248eae04be58501e8a390a3099450500819e38d8eb8`,
and installer SHA-256
`07fc5259514a3e98164869efbbd9c5bdfb7d83dfe6a96c61d15795c6ace77a97`.
The expected version is `1.0.0-beta.7`; Authenticode must be `Valid` and the
signer must be `Scott Converse`.

Gate A run `34772707033` passed all three lanes. Its clean-install,
cross-version-upgrade, and download-only artifacts are bound by exact artifact
IDs, artifact digests, and inner verdict hashes in `run-identity.json`.

The exact-candidate passing captions-OFF Sandbox run established
`elements=33` for public, education, and government; those numeric values are
bound in `run-identity.json`. The binding guard requires the exact candidate,
build, Gate A run, and three-lane evidence before any live action.

The mission performs a verified in-place upgrade, then one fresh physical run:
480 measured minutes captions OFF. Live captions are outside the beta release
gate; offline after-hours captions suffice.
It uses the corrected serialized R6 TSDuck acquisition logic and a 12-hour task
limit. It creates a fresh owned schedule and fails before cancellation if any
unapproved schedule row overlaps. It preserves `CivicCastSoak-Poll`,
`CivicCastSoak-Heartbeat`, and `CivicCastSoak-Boot`.
