# CivicCast clean-box preparation

- Completed UTC: `2026-08-27T01:55:04.9802020Z`
- Pre-cleanup `C:\ProgramData\CivicCast`: 1,729 files, 9,161,918,067 bytes
- Pre-cleanup `C:\CivicCastHostStore`: 10,645 files, 9,261,267,708 bytes
- Pre-cleanup `C:\Program Files\CivicCast (Native)`: 1 file, 84,865 bytes
- Deleted scheduled task: `CivicCastTester3DirectivePoller`
- Remaining `CivicCast*` scheduled tasks: none
- `C:\ProgramData\CivicCast` exists after cleanup: `false`
- `C:\CivicCastHostStore` exists after cleanup: `false`
- `C:\Program Files\CivicCast (Native)` exists after cleanup: `false`
- Verification: **PASS**

The evidence archive was pushed before deletion in commit `70f7da5`. `C:\CivicCastSoak` and non-CivicCast paths were not cleanup targets.
