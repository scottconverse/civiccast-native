# Beta.7 `3e117ff1` dedicated physical tester mission

Status: **READY FOR ISSUANCE**. Gate A run `34772707033` passed all three lanes,
and `run-identity.json` binds each lane's artifact ID, artifact digest, and inner
verdict hash. The passing captions-OFF Sandbox result is bound as numeric `[33]`
for all three channels. Live captions are outside the beta release gate;
offline after-hours captions suffice.

Known immutable identity:

- source: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`
- successful signed build: `34762831824`
- whole-kit manifest SHA-256: `2af18a8f5bea094cdf7af248eae04be58501e8a390a3099450500819e38d8eb8`
- installer SHA-256: `07fc5259514a3e98164869efbbd9c5bdfb7d83dfe6a96c61d15795c6ace77a97`
- version: `1.0.0-beta.7`
- expected Authenticode status/signer: `Valid` / `Scott Converse`
- Gate A PASS run: `34772707033`
- nonce: `BETA7-3E117FF1-OFF8H-R3-A91E4C`

The mission downloads only from the exact SHA-scoped LAN kit root, verifies
every manifest entry and installed runtime, performs an in-place upgrade,
creates a fresh schedule, and runs 480 measured minutes captions OFF.

The physical driver is the corrected R6 transport implementation: an untrimmed
acquisition diagnostic is retained outside the verdict, while clean admission
and each measured probe discard five seconds inside the same 35-second TSDuck
process and grade the remaining 30 seconds. Measured errors remain zero
tolerance. Probes are serialized.

No schedule IDs are pre-authorized for cancellation. Any overlapping live row
therefore fails the mission before the driver cancels or publishes anything.
The three `CivicCastSoak-*` coordination tasks are required and preserved.
