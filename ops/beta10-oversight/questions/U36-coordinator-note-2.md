# U36 - coordinator note 2: the relaunch may replay the same program from its start

Evidence: `evidence\public-freeze-escalated-1523\`, `evidence\public-freeze-1555\`.
- Relaunch after the 15:24 escalation: source "City Council Regular Session - August 11, 2026.mp4", plan dir
  `public\prepared\9a975f75dd84\segment-0001.ts`. Relaunch after the 15:56 escalation: the SAME source and the SAME
  plan dir hash, the segment file rewritten at 15:58 (1.2 GB, ~100 s start preparation both times: 15:24:11 ->
  15:25:37 and 15:56:44 -> 15:58:24).
- If the in-point is identical both times, a relaunch restarts the program from the same point instead of where
  the schedule is, viewers see the same 30 minutes again, and (with U37's freeze at the end of that segment) the
  channel can loop. Establish the in-point of both relaunch plans (plan metadata / log / DB). Include in your
  relaunch-path work (decision 2(ii)): a relaunch must resolve the item and in-point from the schedule at the
  relaunch instant (with the tail floor), and must reuse an already-prepared identical segment instead of
  re-conforming it (why was a 1.2 GB segment for the same key re-written instead of reused?).
