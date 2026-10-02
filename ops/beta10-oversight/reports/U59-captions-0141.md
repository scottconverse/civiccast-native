# U59 — report

**Unit stopped at a question, per standing constraint: the brief's premise is falsified by
measurement.** Full evidence and the decision request: `questions\U59.md`.

Coder, native-Windows beta.10 line. Worktree `civiccast-ds-u25fix` @ `43ab8ba5`, clean, untouched
by this unit. Session 2026-09-27 01:41–01:50 station local.

## Commits

**None.** No code was changed anywhere. `bin\rung_check.py` md5
`c975c22226af11a1ee17ef5eb21889e7` (30617 bytes) at the start of the unit and at the end of it.
No atomic replace was run. The worktree has no new commits because the unit produced none.

## What the brief asked, and what happened

Work 1: add a `CAPTIONS_LOST` rule to `caption_outage()` / the CAPTION_QUIET path — when the
window is ≥ 50 s and decoded 0 cues, count ASR cues inside the window; ≥ 2 ⇒
`BAD <ch>:caption_decode_back=FAIL(CAPTIONS_LOST: asr emitted N cues in the window, 0 reached
the video)`.

Work 2: show it RED on `verify-09`, GREEN after; list which earlier CAPTION_QUIET verifies flip.

Work 3: atomic replace, report, receipt last.

**Work 1's precondition measures 0, so Work 2's RED→GREEN cannot exist.** Measured with the
tool's own U55 helpers, on the real evidence:

```
win counters = 466253.244 -> 466313.244   win clocks = 01:34:27 -> 01:35:27
                     (reproduces the verify's own emitted_first/last_utc to the second)
span >= 50s? True        ASR_in_window = 0        briefed predicate fires (>=2)? False
nearest ASR cue before: 01:32:51   nearest after: 01:38:04   => a 312.77 s ASR-silent hole
```

The ASR's `public/active.vtt` has a 312.77 s cue-free hole (01:32:51 → 01:38:04) covering the
window entirely; only 2 of its 994 inter-cue gaps exceed 60 s and 988 are ≤ 10 s, so this is an
anomaly, not quiet material. The file is live and monotonic (986 cues, then 995, minutes apart,
ending within a minute of the read), so the hole is not a stale or rewritten copy.

## Proof commands and raw results

```
$ .../civiccast-ds/.venv/Scripts/python.exe bin/rung_check.py verify \
      evidence/rung-8h-post-c4-20260927-000847/verify-09.json
OK public:CAPTION_QUIET(FAIL over 60s, 0 cue(s); the worker reported received=8 in 60s, 6.462s ago)   [exit=0]

$ .../python.exe "$TEMP/u59_sweep.py"      # all 91 verify files, 11 run folders, 14.8 s
-> fixtures\U59\sweep.txt   (captured 2026-09-27T01:41:33-06:00)
   9 CAPTION_QUIET channel-entries in 4 run folders; ASR_in_window = 0 for ALL 9
   1 of 9 mappable (verify-09, coverage=covered); the other 8 OUT-OF-RANGE
   FLIP COUNT UNDER THE BRIEFED RULE: 0

$ .../python.exe "$TEMP/u59_nss.py"         # the tool's own two entry points, real evidence
caption_outage() -> (False, '')
no_speech_source() -> None                  # blocked by the fresh receipt, rung_check.py:534-539

$ .../python.exe "$TEMP/u59_bypass.py"      # receipt status changed in memory only; no file written
with the receipt gate neutralised (IN MEMORY, no file written):
  no_speech_source() -> asr gap 01:32:51-01:38:04, 313s; the ASR emitted no cue across the 60s window

$ .../python.exe bin/rung_check.py verify .../verify-02.json
OK public:NO_SPEECH_SOURCE(asr gap 00:15:10-00:22:24, 434s; the ASR emitted no cue across the 60s window)
```

That last pair is the heart of the question: the tool's U55 machinery **already** reads
`verify-09`'s window as ASR-silent, and the same machinery already fired on the other 433.84 s
hole in tonight's own run (`verify-02`) — and printed **OK**, not BAD. No rule keyed on ASR
silence can produce the `BAD` this brief wants.

## What I did NOT do

* No edit to `bin\rung_check.py`, no test added, no atomic replace (§Commits above).
* No station action: no service start/stop/restart, nothing written under
  `C:\ProgramData\CivicCast` or `C:\Program Files`, no long-lived reader opened on `live-hls`.
* Nothing written outside the worktree and the two oversight subfolders. Probes in `$TEMP`; one
  artifact written, `fixtures\U59\sweep.txt`.
* No push, no tag, no merge, no staging.
* U58's fault (why the chain went silent at 01:32:51) is not investigated here.

## What I could not verify

The brief's own observation that the ASR VTT "kept emitting cues" during the outage is
contradicted by the artifact on disk, twice (01:41 and 01:48). I could not resolve it: the file's
01:36 state is not preserved anywhere on disk (no `.vtt` snapshot exists outside the live three
and unrelated 2026-09-14 podcast captions). If that observation is right, the file was rewritten
after the fact, and Work 1 should be implemented as written — I said so in the question file and
asked for the bytes.

## Doubts

* If the ASR was starved by the same upstream stall that emptied the video, its silence is a
  second symptom rather than an independent witness, and the "better witness" framing in the
  brief does not hold for this event.
* Even if the briefed rule shipped, it changes no verdict on any filed evidence — it would be a
  live-only tightening for the (real, different) injector-backlog class.
* The rung cannot re-judge a filed verify once the ASR session ends: the VTT it would judge
  against is a live file that only holds the current session. Snapshotting the VTT beside each
  `verify-NN.json` is the durable fix, and it is a rung-script change owned by the coordinator.

```
proved: the briefed predicate measures 0 on its own target — ASR_in_window = 0 for verify-09 and
        for all 9 CAPTION_QUIET items in the tree; 0 flips; window counters mapped through the
        tool's own anchor reproduce the verify's emitted_first/last_utc to the second; the
        tool's own no_speech_source() reads the same window as "the ASR emitted no cue across
        the 60s window" once the fresh-receipt gate is neutralised in memory · rung_check.py
        byte-identical (md5 c975c22226af11a1ee17ef5eb21889e7) · no code change, no station action
lane: Micro (measurement-only; no artifact changed, no behaviour changed)
```
