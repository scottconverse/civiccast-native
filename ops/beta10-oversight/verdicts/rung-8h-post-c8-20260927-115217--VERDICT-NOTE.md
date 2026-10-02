
## Coordinator stop - 2026-09-27 12:42 (-06:00): stopped CLEAN-so-far to install C9 (U56g) - not a failure
Ran 11:52:17 -> 12:42. Engine C8 = 17a8bd88 (+ graph 309ffac7, pipeline e3d7767a).
- verify: all OK (see rung.log). loudness: 2/2 PASS.
- changeovers: 3/3 CLEAN (12:21:59 public, 12:21:59 education, 12:22:04 government; all picture-late incoming; video 0.033, audio 0.021-0.024, relay 0).
Reason for stop: U56g bounds the reload FALLBACK branch (seen live 3x in ~360 changeovers: fallback=yes, mode=immediate),
which on C8 bytes airs up to 2.13 s of retiring audio past the switch. The 8 h acceptance run must be on the final bytes.
