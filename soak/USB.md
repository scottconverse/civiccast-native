# LPM delivery USB preparation

## Before format

- Recorded (UTC): `2026-08-27T19:44:50.0806058Z`
- Disk number: `1`
- USB bus confirmed: `true`
- Device: `USB SanDisk 3.2Gen1`
- Serial: `0401de8ff57a78779162`
- Drive letter: `D:`
- Capacity: `123,048,296,448 bytes`
- Filesystem: `exFAT`
- Label: `CIVICCAST`
- Exactly one USB disk present: `true`
- Contents matched old CivicCast work: `true`

Top-level contents before destruction:

- `beta-acceptance-TESTER3\`
- `station-kit-0097\`
- `System Volume Information\`
- `Claim-This-Machine.cmd`
- `Open-Operator-Console.cmd`
- `Open-Operator-Console.log`
- `Prepare-This-Machine.cmd`
- `Prepare-This-Machine.log`
- `Stage-CivicCast-Offline.cmd`

Capacity check against candidate kit (`26,851,361,224 bytes`): `PASS`.

## Format and candidate copy

- Elevated quick format started: `2026-08-27T19:45:26.0953372Z`
- Elevated quick format completed: `2026-08-27T19:45:33.2211504Z`
- Resulting filesystem: `NTFS`
- Resulting label: `CIVICCAST-TEST`
- Post-format capacity: `123,048,275,968 bytes`
- Post-format free space: `122,950,373,376 bytes`
- Format identity and result verification: `PASS`
- Candidate source: `C:\CivicCastSoak\kit13`
- Candidate USB destination: `D:\civiccast-kit-75cc13f`
- Candidate SHA: `75cc13f46a4682a3a9972d91656bd6d57eac9c07`
- Copy completed before verification: `15 files`, `26,851,361,224 bytes`
- SHA-256 verification resumed: `2026-08-27T20:09:52.2126076Z`
- SHA-256 verification completed: `2026-08-27T20:17:31.2401907Z`
- Source count/bytes: `15` / `26,851,361,224`
- USB count/bytes: `15` / `26,851,361,224`
- Hash mismatches after one allowed recopy: `0`
- Every file SHA-256 matched: `true`

Final USB preparation verdict: `PASS`.
