# beta.7 R6 immediate finite switch repair - local verification

Date: 2026-09-12

Branch: `fix/beta7-zero-held-preroll`

Base `main`: `a963c39cc44e2643065a818aac0206b110d515d4`

Source and local-proof anchor: `d5c9eb4827be2cb6bc8a40049dfc733d0cd579cd`

PR: https://github.com/scottconverse/civiccast-native/pull/225

Candidate status: no installer or release candidate has been built from this
change. beta.5, beta.6, and the `a963c39` beta.7 kit remain rejected.

## Physical failure and evidence-backed mechanism

The dedicated tester's R6 run failed on all three channels immediately after a
live fallback slate switched to a finite MPEG-TS programme. Each worker logged
`held_streams=0`, selected the new programme, and then received propagated
`GST_FLOW_ERROR` (`-5`) from the new programme's `decodebin` / `tsdemux` leg.
The slate contains neither element.

`GstPlayoutEngine.reload_program()` only enabled its held preroll and
running-time rebase when `switch_at_end_of_current=True`. Immediate finite
programmes therefore sent a segment beginning near running time zero into the
persistent encoder and mux after the output timeline had advanced.

## Source correction

- Every finite or otherwise segment-timed replacement now uses the existing
  two-stream held preroll and common `Gst.Pad.set_offset()` transaction,
  regardless of whether its switch is immediate or boundary-aligned.
- Immediate finite switches observe the outgoing audio and video pads while
  the new leg prerolls. Their latest buffer ends supply the common rebase point;
  the pipeline running time remains the fallback when no outgoing buffer was
  observed.
- Clock-timed live replacements remain unheld and unrebased.
- The proven retirement order is unchanged: select while held, set retiring
  elements to `NULL`, unlink and release their selector pads, remove them, then
  release the replacement holds.
- The abandoned retiring-old-leg error-suppression experiment was removed. R6's
  failing `tsdemux` belonged to the incoming programme.

## Focused results

GI-free engine, graph, and log-contract checks:

```powershell
python -m pytest tests/egress/test_gst_engine_reload_commit_ordering.py `
  tests/egress/test_gst_graph.py `
  tests/policy/test_reload_preroll_log_contract.py `
  -p no:randomly -p no:cacheprovider -q
```

Initial result: `80 passed in 2.48s`. After the adversarial review required
finite-versus-clock timing receipts and matching rebase proof, the expanded
focused result was `83 passed in 1.83s`.

Exact native Windows R6 regression:

```powershell
$env:CIVICCAST_GSTREAMER_RUNTIME_ROOT = `
  'C:\CivicCastTester\candidates\a963c39cc44e2643065a818aac0206b110d515d4\candidate\trust-bridge-install\runtime'
python -m pytest `
  tests/egress/test_gst_engine_wsl.py::test_immediate_finite_playlist_reload_holds_rebases_and_stays_on_air `
  -p no:randomly -p no:cacheprovider -q
```

Result after correcting a filesink-marker timing assertion: `1 passed in
6.41s`. The first run's product path also completed cleanly; its assertion
sampled the output file at the commit marker before the newly released buffer
reached the filesink. The assertion now requires output growth after commit.

Compatibility run covering immediate finite, immediate clock-timed live, and
deferred finite switching: `3 passed in 15.02s`; the final run after the
receipt-contract correction was `3 passed in 15.08s`.

The exact native R6 regression then passed five consecutive independent runs:
`5/5 passed`, with individual runtimes from 5.42s to 6.66s.

The native test uses a running live A/V slate and an ordinary immediate reload
whose replacement is a four-segment `PlaylistLeg` of real MPEG-TS files decoded
through `filesrc`, `decodebin`, and `tsdemux`. It asserts two held streams, an
immediate running-time rebase, selector / retirement / release order, continued
A/V output, no internal-stream error, no transport continuity failure, and no
backward PES timestamps.

Ruff and formatting checks passed for every modified Python file. Focused mypy
reported no issues in `engine.py` or `graph.py`. These are source-level and
native runtime results. A fresh signed build, Sandbox soak, Gate A, dedicated
physical soak, and publication gate remain outstanding.
