# U26 - coordinator answer (2026-09-25 03:30 MDT)

## F3(b) stays absolute. Option A is refused, and here is the evidence
Your section 2 says U13's 270 s wedge was measured on the built-in live `SourceLeg`. The coordinator's log of U13
(OVERSIGHT-LOG, 2026-09-24 19:32) records it as: "immediate (non-deferred) slate->program commit wedged in
`_dispose_confirmed_old_leg` (release_request_pad on the live **12-subchain** slate leg)", i.e. the slate FILL
PLAN shape, the same one you ran once in phase B. One clean sample does not outweigh a measured wedge rate of
roughly 1 in 8 on that shape. Verify this against `reports\U13.md` and correct your report. F3(b) is the
coordinator's engineering call (not an owner decision) and it stays.

## Decision: fix the cause - the station should not go to slate at all for a tiny schedule gap (Option D)
Both live cases went program -> slate -> program within about 0.1 s ("a scheduled program is due" 0.08 s after
FALLBACK_SLATE at 02:58:19). So the slate filled a gap of well under a second between two scheduled items, and the
deferred reload (the trusted path: 505 deferred commits, no wedge) was spent going INTO the slate instead of into
the next program.
1. From the live evidence (the schedule/plan logs, `plan_end_at`, the automation's rollover lines at 02:13 and
   02:58, and the database schedule if you need it, read-only), measure the actual gap between the end of the
   ending item and the start of the next item in both cases, and say where it comes from (slot rounding,
   container duration vs scheduled duration, etc.).
2. Implement: when the rollover/replan builds the next plan and the gap to the next scheduled item is at most
   `_SCHEDULE_GAP_ABSORB_SECONDS` (choose and justify, start from 30 s, matching your tail floor), the plan goes
   straight to that next item (starting it at the boundary, early by at most the gap) with NO slate fill between;
   the switch stays a deferred reload at the current item's end. Real gaps (> threshold) keep today's behaviour
   (slate fill, then F3(b)'s restart detour for the immediate cut).
3. Red then green at the unit level, and rerun your off-live harness in its DEFERRED form: program A (20 s) ->
   next item scheduled 0.5 s after A's end -> show one worker pid throughout, no slate, no exit.
4. Keep `21d9a715` (tail floor); say how the two constants interact.
5. Gates as in the brief. Small commits, never amend. Do not stage a backport.

Option B (clip the slate fill to the next item's start and defer) is NOT in scope now; name it in doubts if Option
D leaves a case it would cover.
