# DIRECTIVE 6 — candidate #13 kit is READY (proceed with Phase 2)

Candidate #13 is built from main and staged. Details for DIRECTIVE-5 Phase 2:

- Full source sha: `75cc13f46a4682a3a9972d91656bd6d57eac9c07`
- LAN URL (verified serving right now):
  `http://192.168.0.135:8765/75cc13f46a4682a3a9972d91656bd6d57eac9c07/`
- Contents: `CivicCast (Native)_1.0.0-beta.1_x64-setup.exe` + `packs\` + `station\`
- Expected total: ~25.01 GB

Proceed exactly per DIRECTIVE-5 Phase 2 and DIRECTIVE-5b:
1. Mirror the whole directory tree from that URL into `C:\CivicCastSoak\kit13`
   (delete any partial first). Verify setup.exe + packs\ + station\ present; record
   file count + total bytes in soak/KIT-2.md and commit.
2. Then DIRECTIVE-5b: identify the USB stick safely, capacity-check (~27 GB needed),
   copy the kit to it, SHA-256 verify every file against the local copy, record in
   soak/USB.md.
3. Then DIRECTIVE-5 Phase 3: install FROM THE USB path over the preserved ProgramData
   (`setup.exe /S /D=C:\CivicCastHostStore\install`), full evidence per the directive.
4. Then Phase 4: the 8-hour soak with the corrected judge.

Note: the earlier candidate reference "407e507" in DIRECTIVE-5's branch name stays as
your working branch name (do not rename the branch); the kit you install is the sha
above — record BOTH in soak/KIT-2.md so the record is unambiguous.
