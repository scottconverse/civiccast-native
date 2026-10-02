# U59 round 5 - second occurrence: public 06:24:14 on C11 (2.000 s picture hole)

Round 4 ACCEPTED (00:07) and staged; C12 (your detector + U61) is being installed now (06:38). This is the
occurrence that happened on C11, BEFORE your detector was live, so the detector did not fire for it.

## Observed (coordinator)
- public, reload_id=16, commit 06:24:14. WARN bound exceeded spread=3.133 s: video_end=28424.333,
  audio_end=28427.467, trimmed=none, switch_running_time=28427.467, first_eos=video.
- Output: 2.000 s video gap between seg000014211 (last video pts 28426.867) and seg000014212 (first 28428.867);
  seg000014211 carries 184 audio packets over 4 s. Audio continuous.
- Pre-switch CTRL output polls (5 s windows): chain-in video +143, +156, +148, +148, +154, +144, +148, +168(6 s),
  +135, +124, +135, +152 while audio stayed +232..+236 - i.e. video ~25-27 fps for ~15 s at the end of the leg.
- The leg ran 2183.4 s (reload 15 committed at running 26244.033 = 05:47:51). Its plan was accepted 05:42:29,
  prepared 338.2 s, 2 pieces: the last 595 s of "City Council Regular Session - September 8, 2026.mp4" then
  "Senior Citizens Advisory Board - June 2026.mp4" from 0 for ~1588 s (coordinator INFERENCE from leg length and
  the next plan's title - verify from the daemon/preparer logs before relying on it). So the leg ended on a MID-FILE slice cut of
  the Senior Citizens June recording (the next plan, accepted 06:20:20, continues that title at 1800 s pieces).
- Fixture (copy, never live): fixtures\C11-public-0624\ - keeper segs 14152..14256, video-pts.txt, audio-pts.txt,
  gst-worker-excerpt.log, control-plane-public-excerpt.log. The 05:42 prepared plan files are already gone from
  ...\public\prepared\ (only newer plans remain); re-create the slice offline if you need it.
- C9 19:15 (government) was 23.0 fps for 21 s on the Sept 8 Council leg; this one is ~25-27 fps for ~15 s on a
  Senior Citizens June leg. 2 occurrences in ~110 changeovers.

## Work (no station action; C12 is going live with a new watched run - keep tests small, low priority, <= 10 min)
1. Is THIS stretch in the media? Find the Senior Citizens June source under ...\uploads\ and its conform in
   conform-cache (match media_duration_seconds). Scan both for video packet gaps / < 29.5 pkts/s windows around
   source offset ~1560-1590 s (the last ~25 s of the 1588 s slice). Also re-create the slice the preparer would
   have emitted (same recipe as the live preparer) and check its last 30 s for A/V balance.
2. If the media and slice are clean at the end: what is common to both legs? Compare the two occurrences
   (C9 government 19:15, C11 public 06:24) on: leg length, number of pieces in the plan, whether the leg ends on a
   mid-file cut, what else the box was doing (preparations running at that minute: control_plane lines
   "preparation ... took"/"queued" within +/- 6 min; caption tap "behind" lines), and the retiring leg's decoder.
   One occurrence each is thin - say what would distinguish your hypotheses and whether the C12 detector's WARN
   line would capture it; if the detector misses a field you now think matters, stage a round-4b patch on top of
   staging\U59d (engine fe5a5306) with RED/GREEN.
Report "Round 5" in reports\U59.md, plain English first, receipt last.
