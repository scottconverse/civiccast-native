# U37 evidence — the mux's video pad goes quiet after a committed deferred reload

Commit-bound evidence for unit U37. Every number in `reports/U37.md` is produced by the
instruments in `instruments/` against the artefacts named here. Text only: the captured
transport streams are public-record meeting media and are **not** committed; their sha256 is
recorded instead (`raw/ref-sha256.txt`) so provenance can be re-checked if the media is
re-provided.

## Environment

- GStreamer 1.28.7 installed runtime, `CIVICAST_GSTREAMER_RUNTIME_ROOT` =
  `C:\Program Files\CivicCast (Native)\runtime` (double `C`); staged python at
  `<root>\dependencies\gstreamer\python`.
- Base revision `5397c069`, extracted with
  `git archive 5397c069 | tar -x -C %TEMP%\u37\base-5397c069`. Base `engine.py` sha256
  `9175935425ff0d8fa7f86316152d8f73166fed083ae30203b579bbd5234eea23`, 306504 bytes.
  - **Off-live capture runs** select the base engine with `PYTHONPATH` (the harness sets it,
    `instruments/x4.py:53`) — sound there only because the harness's cwd is `%TEMP%\u37`,
    which holds no `civiccast` package. `raw/harness/x4base.txt` is one base batch's own
    stdout, and its header prints the resolved `engine_src` sha256 and byte count.
  - **pytest runs do not work that way.** `python -m pytest` puts the invocation cwd at
    `sys.path[0]`, ahead of `PYTHONPATH`; a base-engine unit run made from the worktree
    therefore imports the *worktree* engine and is green for the wrong reason (observed:
    `41 passed in 1.80s`). The unit runs are made from inside the extracted base tree with
    the HEAD test files copied in — see `raw/unit/`.
- Candidate = this branch's HEAD when the runs were captured (`866703c7`), run from the
  worktree. The two commits after it are `3f15ffc6` (evidence files only) and `53186ea1`
  (comments only, in `engine.py`); neither changes behaviour, and `head2-fullsuite.txt` is a
  full suite run at `53186ea1`.
- Live station: read only. Nothing started, stopped, or written.

## Instruments

| file | what it measures |
|------|------------------|
| `tsraw.py` | pure-Python 188-byte TS reader: `packets`, `psi_sections`, `pmt_pids`, `pes_pts` |
| `regcheck.py` | per-PID PES **order regression** in the mux's own output — the red/green verdict |
| `lag.py` | per-PID **airing lag**: at each emitted PES, the leading frontier minus the emitting stream's running time |
| `audioonly.py` | longest unbroken **audio-only run** in emission order, plus per-PID frame counts |
| `dts.py` | the mux output's own video **DTS**: is one emitted at all, is it one frozen value, is it non-monotone |
| `step.py` | prints each actual backward PES step (emission index, before/after running times) |
| `intervals.py` | the worker's own `CTRL output:` interval lines that show a collapsed src rate |
| `x4.py` | the A/B harness that runs the real pipelines off-live (`--tree`, `--caps`, `--captions`, `--runs`, `--tag`) |
| `sumlag.py`, `toplag.py` | summarise `lag-all.txt` into the bound's figures and the base/candidate split |
| `whyx1.py` | spot-check of the emission interleave |

Running time = recorded PES PTS in 90 kHz ticks ÷ 90000 − 3600 (the mux's output base).
PID names: `0x41` video, `0x42` audio, `0x43` captions.

## How a recording is classified base vs candidate

By the engine's own diagnostic vocabulary in its worker log — the U37 stages exist only in the
candidate engine:

| stage string | base `5397c069` | HEAD | build |
|--------------|-----------------|------|-------|
| `rebase-observer-armed … observed=` | 0 | 1 | final candidate |
| `rebase-drain-drained` | 0 | 1 | final candidate |
| `rebase-drain-wait` | 0 | 1 | final candidate **and** the 1.0 s intermediate `h1` — not a marker on its own |
| `rebase-fence-armed … fenced=`, `u37-drain-trace` | 0 | 0 | **discarded** intermediate (DROP fence); excluded from the green count |
| `rebase-fence-disarmed … dropped=` | 0 | 0 | the discarded build's harm line |
| `WARN: rebase drain did not empty within 1.0s` | 0 | 0 | the 1.0 s intermediate `h1` only — see `raw/logs/h1-1.0s-deadline.txt` |

The sound final-candidate markers are `rebase-observer-armed` **and** `rebase-drain-drained`
together: the `h1` intermediate emits `rebase-fence-armed`/`rebase-drain-wait` but never
`rebase-observer-armed`, never `rebase-drain-drained`, and raises the 1.0 s WARN on a switch
whose recorded output is healthy (`x2/_ref/h1-out.ts`: 659 / 1061, worst lag 0.501344 s).

## Results (raw output in `raw/`)

`raw/regcheck-all.txt` — 39 recordings:

| group | runs | collapses |
|-------|------|-----------|
| base `5397c069` | 21 | **4** (x2/run8, x2/run10, x4dbg/run3, x4dbg/run6) |
| final candidate HEAD | 15 | **0** |
| discarded fence build (excluded) | 3 | 0 |

Each collapse is one video PES stepping backwards, with audio continuous:

```
raw/step-collapses.txt:
  x4dbg\run3   video: emitted #1236 (per-pid #298) 0:00:19.992322 -> 0:00:10.581322  backstep=9.411000s
  x2\run8      video: emitted #1238 (per-pid #299) 0:00:20.025656 -> 0:00:10.581322  backstep=9.444333s
  x2\run10     video: emitted #1236 (per-pid #298) 0:00:19.992322 -> 0:00:10.581322  backstep=9.411000s
  x4dbg\run6   video: emitted #1236 (per-pid #298) 0:00:19.992322 -> 0:00:10.581322  backstep=9.411000s
```

Consequence — the longest unbroken audio-only run (`raw/ref-audioonly.txt`): base collapse
**478** (`x2/_ref/red-out.ts`, video 659 / audio 1061) against **26–36** on candidate runs.

`raw/dts-out.txt` (`instruments/dts.py`) — the mux output's own **video DTS**. In all four
collapses the emitted video carries **one single DTS value** in the whole file, equal to the
re-dated stale frame's PTS, on exactly the frames whose PTS lies below it — and no other frame:

```
x4dbg/run3  video 659 PES  PTS+DTS 283  PTS-only 376  PTS backsteps 1
   distinct DTS values: 1  min=19.992322 max=19.992322
   DTS-carrying frames: #297..#579 of 659  (count 283); their PTS 10.581322..19.981322
   of those, frames whose PTS is below the frozen DTS 19.992322: 283 / 283  (DTS-PTS 0.011..9.411000s)
   first PTS-only after: #580 PTS 20.014656 -> 79 PTS-only frames to end
```

The `x2/run8` collapse is the same law with its own value (284 frames, DTS 20.025656, PTS
10.581322..20.014656). The `--hex` appendix at the end of the same file is the field verbatim
for `x4dbg/run3` (#294..#300): the stale frame `#296` is `PTS_DTS_flags=10 hdr_len=5` with PTS
bytes `21 4d ad 9b 1b`, and every DTS-carrying frame from `#297` on is
`PTS_DTS_flags=11 hdr_len=10` whose DTS bytes are `11 4d ad 9b 1b` — **byte-identical to `#296`'s
PTS apart from the PTS/DTS marker nibble**, so the frozen DTS is literally the re-dated stale
frame's stamp. **Every one of the 11 healthy recordings checked** — base `x4base/run1`
and `x1/run1`, the fence build `x2/run2`, `x2/_ref/h1-out.ts`, `x2/_ref/green-out.ts`,
`x2/_ref/h3-out.ts`, and candidate `x4green/run1`, `x4green/run6`, `x4lag/run1`, `x4pc/run1` —
emits **zero** PTS+DTS video headers and zero backsteps.

`raw/logs/base-x4dbg-run3-intervals.txt` — the collapsing base run's own interval line
(`src_d=+282` while its video still arrives at `+180`), with the ordinary commit ladder and no
U37 stage, followed by that run's own reload lines (`raw/logs/base-x4dbg-run3-stages.txt`):
`ends=[video=9.867,audio=10.581] switch_running_time=10.581`, i.e. the outgoing video's declared
tail ends 0.714 s short of the switch instant while the audio's ends exactly on it.

The five files under `raw/logs/` are committed with `git add -f`: the repo's `.gitignore:119`
carries a blanket `logs/` rule that would otherwise silently swallow them, and the paragraphs
above cite them.

`raw/drain-tally.txt` — every final-candidate run's own `worker.log` lines for the drain gate,
one block per run plus a totals block: **15 armed, 15 waits, 15 drained, 0 deadline WARNs**,
drained times `1.125 1.125 1.140 1.141 1.141 1.156 1.157 1.157 1.157 1.172 1.187 1.188 1.203
2.109 2.141` s. Wait shapes: 11× `sink_66=6`, 2× `sink_66=5`, 2× `sink_65=2,sink_66=4`. (The
scratch logs it was built from are deleted with `%TEMP%\u37`, so this file *is* the record.)

`raw/ends-shapes.txt` — each run's declared outgoing-tail `ends=[video=,audio=]` crossed with
its own `out.ts` verdict. It is the race, run by run: on the base engine the shape
`ends=[video=9.867,audio=10.581]` occurs **8** times and collapses **3** of them, and
`ends=[video=9.900,audio=10.581]` occurs **4** times and collapses **1**; against **0 collapses
in 11 final-candidate runs carrying exactly those two shapes.**

`raw/lag-summary.txt` — `instruments/sumlag.py` over `raw/lag-all.txt`: 78 pid-rows, **74
healthy**, worst healthy **0.726678 s** (at the switch emission, i.e. the media's own A/V end
offset), **no healthy row with any emission >1.0 s behind**, and 4 rows over 2.0 s — all four
the video of a collapsed capture. By build: base-only 42 rows (worst healthy 0.149322 s),
discarded fence 6, final candidate 30 (worst 0.726678 s).

Bound (`raw/ref-lag.txt`, `raw/lag-all.txt`): worst healthy airing lag **0.726678 s**; no healthy
stream-recording ever emitted a PES more than 1.0 s behind; the four collapses sit at
**9.408000–9.429333 s**, each with 253 of ~1720 emissions over 1.0 s and 133 over 5.0 s.

The discarded DROP build's harm (`raw/logs/fence-variant-x2-run3.txt`,
`raw/ref-regcheck.txt` on `x2/_ref/green-out.ts`): `stage=rebase-fence-disarmed pad=sink_66
stream=audio dropped=48` and audio **1013** frames against the 1061 every non-dropping run airs,
with video 653 against 659.

## Gates (`raw/fullsuite/`)

All four are `python -m pytest tests/egress -q -p no:randomly`.

| log | revision | result |
|-----|----------|--------|
| `base-fullsuite.txt` | base engine `5397c069`, **with the seven U37 ordering tests present** | `8 failed, 1813 passed, 46 skipped` — the 7 U37 tests **red** plus one pre-existing failure |
| `wt-fullsuite2.txt` | candidate engine, before the two per-stream-judge tests landed | `1 failed, 1820 passed, 46 skipped` |
| `wt-fullsuite3.txt` | same, a second run | `1 failed, 1820 passed, 46 skipped` |
| `head-fullsuite.txt` | HEAD `866703c7` | `1 failed, 1822 passed, 46 skipped` |
| `head2-fullsuite.txt` | HEAD `53186ea1` (comments only past `866703c7`) | `1 failed, 1822 passed, 46 skipped` |

The accounting is exact: 1813 (base, U37 red) + the 7 U37 tests = 1820, + the 2 per-stream-judge
tests = 1822. The one failure throughout — and the *only* one at HEAD — is
`test_hls_sink_captions.py::test_packaged_gstreamer_to_hls_sink_preserves_captions_and_cadence`,
which is therefore pre-existing rather than introduced.

### Focused gate pair (`raw/unit/`)

The two touched files, same selection on both sides, run twice — once against each engine:

| log | engine | result |
|-----|--------|--------|
| `raw/unit/base-unit-red.txt` | base `5397c069` with the HEAD test files copied into the extracted tree, pytest run from inside that tree | `9 failed, 146 passed, 2 skipped in 4.89s` |
| `raw/unit/head-unit-green.txt` | HEAD `ffbc88de`, run from the worktree | `155 passed, 2 skipped in 4.26s` |

146 + 9 = 155, and the 2 skips are the same two runtime-undeclared skips in both runs. The red
file quotes pytest's own rendering of the imported module —
`...\base-5397c069\civiccast\egress\gst\engine.py` — which is the engine-identity proof here,
because `PYTHONPATH` is exactly what does *not* select the engine for pytest.

### Harness identity (`raw/harness/`)

`raw/harness/x4base.txt` — one base batch's full stdout, header included:
`# engine_src=base-5397c069\civiccast\egress\gst\engine.py sha256=9175935425ff0d8f bytes=306504`,
`# verdicts(x4base): ['ok', 'ok', 'ok']`, `# src-collapse runs: 0/3`. It also carries that run's
whole switch ladder, which is what a *healthy* base switch looks like.

**Gap, stated rather than papered over:** the other batches' harness stdout was not captured, so
per-run engine byte-identity exists for this batch only. For every other run, base-vs-candidate
is carried by the behavioural markers in the table above (the U37 stages exist only in the
candidate engine) plus the pinned base-tree hash. The captured trees are deleted with
`%TEMP%\u37`, so this cannot be re-derived from here afterwards.

## Reproducing

The instruments are `instruments/*.py`; they read a captured `out.ts` (a raw 188-byte TS) and
print, respectively: the red/green verdict (`regcheck.py`), the airing-lag figures (`lag.py`),
the longest audio-only run (`audioonly.py`), the exact backward steps (`step.py`), the emitted
video DTS (`dts.py`). `endsshapes.py` additionally reads a run's `worker.log` for its declared
`ends=[video=,audio=]`; `sumlag.py` and `toplag.py` summarise the committed `raw/lag-all.txt`.

The `out.ts` files themselves are public-record meeting media and are not committed; they are
deleted with the scratch tree (`%TEMP%\u37`) at the end of the unit, and `raw/ref-sha256.txt`
records the hashes of the ones quoted above so provenance can be re-checked if the media is
re-provided.
