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
  `git archive 5397c069 | tar -x -C %TEMP%\u37\base-5397c069` and run with `PYTHONPATH` at that
  root. Base `engine.py` sha256 `9175935425ff0d8fa7f86316152d8f73166fed083ae30203b579bbd5234eea23`,
  306504 bytes.
- Candidate = this branch's HEAD (`866703c7`), run from the worktree.
- Live station: read only. Nothing started, stopped, or written.

## Instruments

| file | what it measures |
|------|------------------|
| `tsraw.py` | pure-Python 188-byte TS reader: `packets`, `psi_sections`, `pmt_pids`, `pes_pts` |
| `regcheck.py` | per-PID PES **order regression** in the mux's own output — the red/green verdict |
| `lag.py` | per-PID **airing lag**: at each emitted PES, the leading frontier minus the emitting stream's running time |
| `audioonly.py` | longest unbroken **audio-only run** in emission order, plus per-PID frame counts |
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
| `rebase-drain-wait`, `rebase-drain-drained` | 0 | 1 | final candidate |
| `rebase-fence-armed … fenced=`, `u37-drain-trace` | 0 | 0 | **discarded** intermediate (DROP fence); excluded from the green count |
| `rebase-fence-disarmed … dropped=` | 0 | 0 | the discarded build's harm line |

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

`raw/logs/base-x4dbg-run3-intervals.txt` — the collapsing base run's own interval line
(`src_d=+282` while its video still arrives at `+180`), with the ordinary commit ladder and no
U37 stage (`raw/logs/base-x4dbg-run3-stages.txt`).

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

The accounting is exact: 1813 (base, U37 red) + the 7 U37 tests = 1820, + the 2 per-stream-judge
tests = 1822. The one failure throughout — and the *only* one at HEAD — is
`test_hls_sink_captions.py::test_packaged_gstreamer_to_hls_sink_preserves_captions_and_cadence`,
which is therefore pre-existing rather than introduced.

## Reproducing

```
cd %TEMP%\u37
python regcheck.py <tag>/run<N>/out.ts ...     # red/green verdicts
python lag.py      <tag>/run<N>/out.ts ...     # the airing-lag bound's figures
python audioonly.py <tag>/run<N>/out.ts ...    # audio-only run + frame counts
python step.py     <tag>/run<N>/out.ts         # the exact backward steps
```

The `out.ts` files themselves are deleted with the scratch tree (`%TEMP%\u37`) at the end of the
unit; `raw/ref-sha256.txt` records the hashes of the ones quoted above.
