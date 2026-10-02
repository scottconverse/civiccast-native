# 8h2 incident 00:37 - two channels off programme (government ~3 min black slate, education ~5 min filler slate)

## Government - in-worker slate (black), ~00:37:30 -> 00:40:30 (~3 min)
- 00:34:55 changeover (CLEAN) put a 155 s plan on air. Automation issued the next rollover at 00:35:19 "as soon as the previous
  plan settled" (lead model 690 s for an 1800 s asset). Prep queued 00:35:22 (cold, 1 segment).
- Plan EOS ~00:37:30 with no reload in flight: "holding the slate" (worker chain-in video=0; keeper frame black).
- Automation "rollover horizon past due by 2s/63s/124s but the seamless reload is still settling; waiting".
- Prep done 00:40:24.981 (302.8 s); accepted switch_at_end_of_current=False; committed; changeover 00:40:30 scored HOLE
  (relay_invalid_ts_new=7, ~0.149 s audio; video max 0.033 s).
- Cause: short plan (155 s) followed by a cold 1800 s prep (~300 s). No warm/look-ahead covered it. The C14 design has no
  earlier dispatch point when the plan on air is shorter than the prep time.

## Education - planned FILLER slate, 00:37:22 -> 00:42:07 (+ ~13 s stream restart gap, programme frames from ~00:42:20)
- 00:28:38 rollover: "no asset duration available for the boundary; the timeout-derived floor stands", target=**filler**.
  So the 00:30:13 prepared plan (93 s prep) was the slate "CivicCast is preparing the channel." (keeper frame confirms).
- 00:37:22 changeover CLEAN - onto the filler. Daemon FALLBACK_SLATE 00:37:25; automation "a scheduled program is due" 00:37:25;
  plan resolved to a 23.5 s tail of the closing scheduled item -> dropped -> next item (1800 s) prep queued 00:37:28.
- Prep 276.9 s done 00:42:05; worker deliberately killed to leave filler (issue #157 design); relay cleared live-hls (9 files);
  new worker ON_AIR 00:42:07, first keeper segment 00:42:21; frame shows "NSF NCAR Explorer Series: The Day After Tomorrow".
- loudness #2 (00:42:22) education INSTRUMENT_ERROR (playlist missing during the restart) - instrument, not a loudness result.
- Cause (suspected, NOT yet confirmed): the automation planned filler at a boundary where a scheduled item still had 23.5 s to
  run - i.e. it had no asset duration for the boundary item and fell back to filler instead of the next programme.
  Needs code reading of civiccast/egress/automation.py (fill-target selection when asset duration is unavailable).

## Verdict impact
Slate on air on 2 channels for ~3 and ~5 min. Under the beta.10 bar this rung cannot PASS. Public unaffected (00:37:17 CLEAN).

## Code pointer (coordinator, 00:45)
Installed automation.py (C14) ~L2288-2311: the rollover asks the boundary provider for the plan at plan_end_at; force_fallback
(target=filler) is set when that plan is None/empty, OR when fresh_end <= plan_end_at and fresh_seconds < planned_seconds
("A final schedule window commonly resolves to the same item with less time remaining ... roll seamlessly onto filler").
At 00:28:38 the boundary answer at 00:37:22 was the closing item's 23.5 s remainder (the 554 s plan ended 23.5 s before its
schedule item did). Whichever branch fired, the automation chose filler over "drop the short tail and plan the NEXT item" -
the rule the daemon itself applies at 00:37:28. Fix direction: apply the same short-tail-skip in the boundary provider /
rollover so a sub-lead tail resolves to the next programme, never filler. To brief as a coder unit (U63).
Why did the 554 s plan end 23.5 s early vs its schedule item? Open - likely the max_segment_seconds split or conform trim.
