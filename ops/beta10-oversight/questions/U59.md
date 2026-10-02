# U59 — the briefed witness measures 0 on its own target

**Premise falsified; stopping for a decision before any code change.**

Coder, native-Windows beta.10 line. Worktree `civiccast-ds-u25fix` @ `43ab8ba5`, clean.
Tool under judgement: `bin\rung_check.py` (oversight folder), md5
`c975c22226af11a1ee17ef5eb21889e7`, 30617 bytes — **not modified by this unit**.
Brief: `questions\U55-answer-2.md` (the U59 brief is filed there, not under `briefs\`).
Session time: 2026-09-27 01:41–01:48 station local (`date -Iseconds` = `2026-09-27T01:43:21-06:00`).

## 0. The one-line answer

Work 1's rule — *"count ASR cues emitted inside the window. If >= 2 ASR cues fall inside it,
the line is `BAD ... CAPTIONS_LOST`"* — measures **0 ASR cues** in `verify-09`'s window, so it
changes nothing there; and it measures 0 for **every one of the 9 CAPTION_QUIET items in the
whole evidence tree**, so it changes nothing anywhere. Work 2's RED→GREEN is unreachable with
the ASR as the witness. Worse, **no rule keyed on ASR silence can print BAD at all** (§6): both
of the tool's silence words sit on the OK side of the line, and the silence witness is *already*
being read correctly by U55's own machinery for exactly this window — the receipt is what
overrides it. The real decision is therefore not "wire up the ASR witness" but "**may a 30-segment
0-cue decode outrank a fresh worker receipt?**", which is a product call, not a wiring change.

## 1. RED, reproduced

```
$ "C:/Users/scott/Documents/Codex/2026-09-16/re/civiccast-ds/.venv/Scripts/python.exe" \
    bin/rung_check.py verify evidence/rung-8h-post-c4-20260927-000847/verify-09.json
OK public:CAPTION_QUIET(FAIL over 60s, 0 cue(s); the worker reported received=8 in 60s, 6.462s ago)
exit=0
```

Identical to the line quoted in the brief. This is `caption_outage()` returning `(False, '')`
(`rung_check.py:603`) — no outage sign is recognised, so the CAPTION_QUIET branch
(`rung_check.py:604-606`) is taken and the ASR is never consulted at all.

## 2. The mapping is sound, and it measures 0

Called the tool's own U55 helpers against the real evidence (probe in `$TEMP`, nothing written
to the station or the worktree — `fixtures\U59\` holds the sweep output; see §9 for the probe
source):

```
tap_dir      = C:\ProgramData\CivicCast\data\caption-tap\public
vtt_path     = C:\ProgramData\CivicCast\data\egress\public\captions\active.vtt | exists: True | bytes: 109646
anchor       = 1790028214.1188793
win counters = 466253.244 -> 466313.244 (span 60.0s)
win clocks   = 01:34:27 -> 01:35:27
emitted_utc  = 2026-09-27T07:34:27.362605+00:00 -> 2026-09-27T07:35:26.089381+00:00
block        = status FAIL cue_count 0 span 60.0 segs 30
receipt      = OK | the worker reported received=8 in 60s, 6.462s ago
vtt cues     = 986
ASR_in_window= 0 (predicate: start < hi and end > lo)
nearest before: 01:32:51 counter 466157.230 (96.01s before win)
nearest after : 01:38:04 counter 466470.000 (156.76s after win)
ASR gap       = 312.77s  (01:32:51 -> 01:38:04)
briefed predicate fires (>=2)? False
span >= 50s? True
```

The anchor is not a guess: mapping the window's counters through it reproduces the verify's own
`caption_window.emitted_first_utc` / `emitted_last_utc` to the second (07:34:27.362605Z and
07:35:26.089381Z; station local = UTC−6, so 01:34:27 and 01:35:26). Both of Work 1's guards are
satisfied (span 60.0 s ≥ 50 s; block decoded 0 cues) — and then the count it keys on is 0.

## 3. Why: a 312.77 s ASR-silent hole sits over exactly this window, and it is real, not a rewrite

The ASR's `active.vtt` for `public` is a **live, currently-growing** file. Read three times inside
this session: 986 cues / 109646 bytes, then 995 cues / 110774 bytes. Gap statistics of the file as
of the last read:

```
file=...\egress\public\captions\active.vtt bytes=110774 cues=995
span: 460910.240 -> 466764.970 (1.63 h)
largest cue-free gaps:
     433.84s  from counter 461496.160 to 461930.000
     312.77s  from counter 466157.230 to 466470.000
      21.54s  from counter 464018.850 to 464040.390
      10.46s  from counter 463919.920 to 463930.380
      10.22s  from counter 464359.940 to 464370.160
gaps > 60s: 2
gaps <= 10s: 988 of 994
```

So of 994 inter-cue gaps, 988 are ≤ 10 s and only 2 exceed 60 s. The window's hole is one of the
two — it is an anomaly, not a quiet stretch of dense-cue material, and it is **not** a stale copy:
the file's last cue (counter 466764.970 ≈ 01:43:09) is within a minute of the read, its mtime is
`2026-09-27 01:43`, and the tap is still publishing (`chunk-093356.wav`, mtime `01:43:19`). The
file is a monotonic record from session start (00:05:24) to now, and it has a hole where the
outage was.

**This contradicts the brief's own parenthetical.** The brief says "public's ASR
`captions\active.vtt` kept emitting cues" during the outage. I cannot reproduce that for this
window from the artifact on disk, at 01:41 (sweep) or at 01:48: no cue whose counter interval
overlaps 01:34:27–01:35:27, and no cue at all between 01:32:51 and 01:38:04. Either that
observation was of the file's growth/mtime rather than its content in the window, or it was of a
different time range. Worth re-checking against the same mapping.

## 4. Work 2 answered in full: the flip list is empty

All 91 `verify-*.json` in all 11 `evidence\rung-*\` folders, through the unmodified tool, plus
the briefed predicate evaluated on every CAPTION_QUIET item (`fixtures\U59\sweep.txt`, captured
`2026-09-27T01:41:33-06:00`, 14.8 s total):

```
evidence\rung-8h-post-c1-20260926-190215\verify-07.json  public     FAIL cues=0  span=60.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 446596 < vtt 460910) | win 20:06:49-20:07:49
evidence\rung-8h-post-c2-20260926-213112\verify-06.json  public     FAIL cues=0  span=2.0  ASR_in_window=0 coverage=OUT-OF-RANGE(win 454881 < vtt 460910) | win 22:24:55-22:24:57
evidence\rung-8h-post-c4-20260927-000847\verify-09.json  public     FAIL cues=0  span=60.0 ASR_in_window=0 coverage=covered                          | win 01:34:27-01:35:27
evidence\rung-8h-post-u47-20260926-133151\verify-01.json government UNVERIFIED cues=1 span=24.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 328443 < vtt 366870)
evidence\rung-8h-post-u47-20260926-133151\verify-01.json public     UNVERIFIED cues=2 span=24.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 422481 < vtt 460910)
evidence\rung-8h-post-u47-20260926-133151\verify-07.json public     FAIL cues=0  span=10.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 426692 < vtt 460910)
evidence\rung-8h-post-u47-20260926-133151\verify-09.json education  UNVERIFIED cues=10 span=60.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 334100 < vtt 367232)
evidence\rung-8h-post-u47-20260926-133151\verify-09.json government UNVERIFIED cues=7  span=60.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 333880 < vtt 366870)
evidence\rung-8h-post-u47-20260926-133151\verify-09.json public     UNVERIFIED cues=13 span=60.0 ASR_in_window=0 coverage=OUT-OF-RANGE(win 427900 < vtt 460910)
```

**Flip count under the briefed rule: 0.**
* 8 of the 9 have no mapping at all — `OUT-OF-RANGE`: their window counters precede the current
  VTT's first cue (counter 460910.240 = 00:05:24), because the ASR session restarted. The brief's
  own fail-safe applies ("if the mapping is unavailable, keep today's behaviour"), so they stay.
* 1 of the 9 has a mapping, and it measures 0 cues, so it stays per the brief's second branch.

No BAD in the tree changed either: `post-u47/verify-27` and all 8 `pre-u44` verifies still print
the same stale/absent-receipt FAILs they printed before.

## 5. Structural, and worth knowing before relying on this witness

**Only the newest ASR session is mappable.** The VTT is one live file per channel, rewritten in
place, holding only the current session's span (1.63 h here). Any window from a previous session
is unreachable by construction — which is why 8 of 9 filed CAPTION_QUIET windows cannot be
re-judged from the ASR at all, and why the brief's "re-run every earlier CAPTION_QUIET verify …
so the coordinator can re-judge them" cannot deliver what it intends.

There is no frozen VTT from 01:36 anywhere on disk. The only `*.vtt` under the station data root
outside the live three are `2026-09-14 23:51` podcast-package captions under
`data\uploads\.civiccast-packages\`, which are unrelated to the caption chain. So a re-judgment
after the fact is impossible for this event too, unless the rung starts snapshotting the VTT
beside each `verify-NN.json` (see the recommendation in §7 — that is a rung-script change, yours,
like the earlier `bin\rung.ps1` edits).

## 6. The decisive fact: silence can never print BAD, and U55 already reads this window correctly

The dispatch is `rung_check.py:592-619`. `PASS` skips; a caption `FAIL`/`UNVERIFIED` goes to
`caption_outage()`; **both** of the softer outcomes are appended to the `quiet` list, and the
printed line is `"OK" if not bad else "BAD " + ...` (`:623-624`). So:

* `CAPTION_QUIET(...)` → an **OK** line.
* `NO_SPEECH_SOURCE(...)` → an **OK** line.
* `BAD <ch>:caption_decode_back=FAIL(...)` requires `caption_outage() == True` **and**
  `no_speech_source() is None` (`:613-618`).

For `verify-09`, both of the tool's own entry points were called directly (real evidence, real
functions):

```
caption_outage() -> (False, '')
no_speech_source() -> None
```

`no_speech_source()` returns None at `rung_check.py:534-539` — the **fresh positive receipt**
gate ("A receipt within RECEIPT_FRESH_SECONDS says the worker injected captions for the window,
so the silence is the station's problem, not the source's"). It returns *before* the gap test at
`:553-561` is reached. Neutralising only that gate **in memory** (the receipt's `status` changed
to `"ABSENT"` in a copy of the dict; no file written) yields:

```
with the receipt gate neutralised (IN MEMORY, no file written):
  no_speech_source() -> asr gap 01:32:51-01:38:04, 313s; the ASR emitted no cue across the 60s window
```

So the tool's U55 machinery **already recognises this exact window as "the ASR emitted no cue
across the 60s window."** The ASR witness the brief wants to add is not missing evidence — it is
present, correct, and overruled. And note the shape of the precedent inside tonight's own run:

```
[   8.4s] rung-8h-post-c4-20260927-000847/verify-02.json
        OK public:NO_SPEECH_SOURCE(asr gap 00:15:10-00:22:24, 434s; the ASR emitted no cue across the 60s window)
```

The other 433.84 s hole in the same file *did* get the U55 treatment earlier tonight — because
that window's receipt was `UNAVAILABLE` (age 183.635 s), not fresh. And that line is **OK too**.
It did not become a rung failure. That is the whole point: **the U55 route was already walked on
this exact station tonight, and it did not catch the outage either.**

## 7. The question

**Do you want the 0-cue decode to outrank a fresh worker receipt — and if so, under what
guard?**

This is the only lever that produces you a `BAD` on `verify-09`. Every route through the ASR's
silence, including the one the tool already computes, prints an OK line.

* **Option A — hold U59 until U58 says which stage dropped the cues.** If the ASR was starved by
  the same upstream stall that emptied the video, the ASR's *silence* is a second symptom, not an
  independent witness, and no rule keyed on it can ever be sound. This is the conservative read
  of my evidence, and it is worth an hour of U58's findings before any code here.
* **Option B — change the precedence, not the witness.** Treat `received>0` + a 30-segment
  clean decode of 0 cues as a contradiction and let it reach `BAD`. Precise surface:
  `rung_check.py:534-539`. Blast radius is the thing to decide: this converts `CAPTION_QUIET`
  into `BAD` for every 0-cue window with a fresh receipt, i.e. including genuinely quiet rooms
  — the exact false-positive class U48 and U55 were written to remove. It needs a guard
  (consecutive windows? a minimum span? the ASR gap *plus* the receipt?). **This is the product
  decision, and I will not pick it for you.**
* **Option C — implement the briefed rule anyway, as a live-only tightening.** It is honest,
  cheap, and *inert*: 0 flips on all filed evidence, and on a live run it can only fire when the
  ASR emits ≥ 2 cues the video drops — a real class (the injector backlog case), just not this
  event. If you want it as a down-payment on that class I will ship it, with the RED shown
  against a synthetic fixture rather than against `verify-09`, since `verify-09` cannot be made
  to go GREEN.

**My recommendation: A, then C.** Ask U58 for the stage first; if the ASR turns out to be an
independent witness (it had cues the VTT and video both lost, i.e. the VTT is downstream of the
same broken stage), then C is worth having as the injector-backlog detector it actually is; if
the ASR was simply starved, C is still harmless but B is the only thing that would have caught
this, and B is yours to decide.

**Separately, and independent of the above:** have the rung snapshot `captions\active.vtt` (and
the receipt line) beside each `verify-NN.json` when it writes the verify. Right now a filed
verify is unjudgeable after the session ends, which is why 8 of 9 of tonight's CAPTION_QUIET
items could not be re-judged at all. That is a `bin\rung.ps1` / rung-script change on your side,
cheap, and it makes every future re-judgment possible from frozen bytes.

## 8. What I did NOT do, and what I could not verify

* **No code change.** `bin\rung_check.py` is byte-identical to its pre-unit state: md5
  `c975c22226af11a1ee17ef5eb21889e7`, 30617 bytes. No test was added; no atomic replace was run.
* **No station action.** No service started, stopped, or restarted; nothing written under
  `C:\ProgramData\CivicCast` or `C:\Program Files`; no live HLS reader was opened (all reads of
  emitted material in this unit were of `evidence\` JSON and of the caption VTT/tap paths, which
  are plain file reads, not mux readers).
* **No writes outside the two oversight subfolders.** Probes live in `$TEMP`; the only artifact
  written is `fixtures\U59\sweep.txt`.
* **I did not verify U58's fault.** Why the caption chain went silent at 01:32:51 is U58's
  question and I did not attempt it.
* **I could not verify one of the brief's own observations.** The claim that the ASR VTT "kept
  emitting cues" across the outage is contradicted by the artifact on disk at 01:41 and again at
  01:48 (§3). I am reporting the contradiction rather than resolving it, because I cannot see the
  file's 01:36 state and there is no snapshot of it anywhere.

## 9. Doubts

* **The one thing that could still make Work 1 right:** if the brief's author read the VTT at
  01:36 and saw cues in the window that the file no longer holds, then the file was rewritten
  after the fact and my 01:41/01:48 reads are of a different state. I looked for a snapshot and
  found none. The file's monotonicity (session start 00:05:24 → the current minute, growing
  between my own reads) is evidence against a rewrite, but it is not proof, and the brief's
  observation is evidence for one. If you can show me those cues — a screenshot, a copy, a byte
  offset — the answer to Work 1 changes completely and I will implement it as written.
* **The `near=142` figure** in the sweep (`fixtures\U59\sweep.txt`, the ASR table) counts cues
  within ±600 s of the window on the same mapping; I include it as evidence that the mapping is
  live and correct, not as a claim about the window itself. The window count is the 0.
* **Probe provenance:** the probes are `$TEMP\u59_final.py`, `$TEMP\u59_gaps.py`,
  `$TEMP\u59_bypass.py`, `$TEMP\u59_sweep.py` — they load `rung_check.py` via `importlib` after
  stubbing `sys.argv` and catching `SystemExit`, then call the tool's own functions. They are not
  in the worktree, per the no-scratch rule. The sweep output is preserved at
  `fixtures\U59\sweep.txt`; the probe sources are not, and I can re-emit them on request.
