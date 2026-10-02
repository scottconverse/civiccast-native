# C14 second 8 h rung (8h2) — FAIL, ended early at ~2h58m for the C15 (U63) install

Rung `8h2-post-c14`, started 2026-09-28 23:59:06, service pid 28832 throughout (no restart until the C15 install
at ~02:57-02:58). Ended early by coordinator decision: the rung could not PASS after the 00:37 slate incident,
and the fix (U63) was audited and ready. Evidence up to the install is kept as-is.

## Results (23:59:06 -> ~02:57)
| Gate | Result |
|---|---|
| Captions / timing / playback verify | 17 / 17 OK |
| Loudness 240 s windows | 5 / 6 all-PASS; #2 (00:42:22) education INSTRUMENT_ERROR (playlist missing during the deliberate worker restart), government/public PASS |
| Changeovers | 20 CLEAN + 1 HOLE (government 00:40:30 slate->programme, relay_invalid_ts_new=7, ~0.149 s audio) |
| Slate on air | **FAIL** — government ~00:37:30->00:40:30 (in-worker black slate); education 00:37:22->00:42:07 filler slate + ~13 s worker restart. See INCIDENT-0037-SLATE.md |
| Aborted reloads | 1 — public 00:17:23 aborted:error on a 0.2 s lead tail, self-healed (retry accepted 00:17:26), no on-air effect |
| Forced switches / pace < 0.94 / lag WARN | 0 / 0 / 0 |
| Disk (C:) | 35 -> 21 (01:16, 4.4 h public warm) -> 25-33 GB |

## Coordinator slip in this rung
- 00:05:02-00:06:01 segment_keeper killed by the previous rung's end-of-rung kill-by-KeepDir; restarted by hand
  (pid 30820). No changeover fell in the gap.

## Follow-up
U63 (fix A: boundary tail/empty answer re-resolved to the next programme; fix B: look-ahead warms the boundary a
short plan steps onto) audited 02:56 and installed as C15. Fresh 8 h rung on C15 follows.
