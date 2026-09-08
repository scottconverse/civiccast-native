# Native live-caption flow repair

Source-level verification on2026-09-08, not installed-candidate or field acceptance.
Public beta.4 remains current; beta.5 has not been tagged or published.

## Cause and scope

Exact signed-be1260 baseline output stalled with no reload request when three
720p workers played bars/snow playlists with live captions and audio capture.
Removing captions avoided that reproducer; removing the audio tap did not.
The failed trace's logical caption cursor advanced to18.006s but appsrc's last
observed GAP was7.676s. GStreamer1.28.5 serialized appsrc.send_event returns
enqueue acceptance, not downstream delivery. Debug logging altered scheduling
and suppressed the failure, so verbose-debug successes were not fixes.

Queue-only isolation afterappsrc passed two three-worker runs, with an
interleaved unchanged baseline still failing. However gstqueue.c explicitly
does not count serialized events against buffer/byte/time limits. The production
repair therefore combines a persistent non-leaky forwarding queue with an
explicit heartbeat admission gate, not queue limits alone.

The engine reserves Gst's own event seqnum before enqueue, and the queue.src
probe clears only that reservation as the event enters downstream push. During
a blocked push, at most one further heartbeat waits; later ticks coalesce the
elapsed interval after forwarding resumes. Prime retains its250ms GAP and uses
the same gate. Stop closes admissions before removing timer/probe. Real caption
cue buffers keep their existing path and are not counted by this heartbeat gate.
No caption, role, provider or watchdog capability is disabled.

## Exact production source hashes

- engine.py:0831d8c3dceac4daffbee2f5593352bfe1ba2f4cea6d8333cfda9a769c5b5bc3
- caption_flow.py:955bf1993caf6898761ecd5274118ee48718d6bcb643c5299828fbf1d70af3ed
- test_gst_engine_caption_flow_native.py:8e825517d1b7fc16d6c37938ca31d854725b291fa1291c6751259fe281c97766
- test_gst_engine_caption_gap_admission.py:6cedca6f7eb06f36735092fd2de0d4e36ac76a4573d4a532c194076ad0d0fade

## Verification

- Production native stress3475:PASS55.30s, three rounds xthree channels; each
  emitted >=9.5s actual video AND audio packet spans, continuous TS/PCR,
  caption-audio WAVs/no partials, and clean exit. Path
  native-caption-flow-production-20260908a. Its earlier test-file version
  073d13c86eede0d97a2f675e70263f5fc9738083624fadd83975c793efd8c051 contained
  only the stress node, not the later direct-probe node.
- Stronger native52541:2PASS56.60s, same stress plus direct real-GStreamer queue
  probe proof of automatic seqnum reservation/forwarding and timer/probe removal
  on stop. Path native-caption-flow-production-probe-20260908a. Final hashesabove.
- Full combined native engine suite76966:24PASS159.95s, zero skips. Path
  native-caption-flow-full-engine-20260908a. Includes real later-cue decode-back,
  live UDP, graphics, repeated3x6 program changes with caption commands, transport,
  settlement and clean stop. Reload fixture remains1f2e937e5e1decbc2cdf6b94bfdf627982a9ad47da0299c51b485492a43ccea9.
- Combined GI-free helper/production-admission/reload/worker/strategy/daemon:
  250PASS/6SKIP in7.81s. Six skips are POSIX-FIFO-only tests on Windows; native
  Windows pipe/error paths ran. Profile-write diagnostic reported zero attempts.
- Production admission red-first:4FAIL/1PASS before wiring;38PASS after wiring
  with helper and reload-ordering tests. Helper originally6PASS and independently
  reviewed; source integration independent review found no blocking race.
- Ruff check/format and strict mypy on engine/helper/daemon passed.
- Docs/public-surface checks68PASS2.08s; source manual unchanged in this caption
  slice because operator controls/acknowledgement semantics did not change.

## Documentation artifact correction

PR199 initial headb61d9c5c doc job102263226285 inrun34286503465 correctly failed:
manual text had changed without regenerated tracked outputs. Pandoc conversion
succeeded; the source-hash freshness check failed. The release manager missed
those generated artifacts in the first source push.

Existing renderers regenerated PDF, DOCX, both manifests and in-product handbook.
Both --check-current checks nowPASS. Extracted PDF/DOCX text contains the updated
program-change explanation and v1.0.0-beta.5; handbook contains the same paragraph.
- normalized manual source:d3e8b259f43f347f77128ca8239ea1f2913d2c06564eefecfd05ded3ec468641
- PDF:c047136fbadcaa2a4c6691a9c7f0b287252e1856b743c58c60dbf5a066a865f3
- DOCX:c9974a2845e733fb615f6b710fa193d81137bcaf82dd4c42e51a48d7c63b72df
- handbook JSON:1e100575d5db73e347ff2b7d0c9e31e6ec6db4c9cbd822cbfaba7d9f9018aa7d
MiKTeX printed update-check reminders but rendering exited0; no runtime or TeX
upgrade was performed and no freshness check was relaxed.

## Remaining release work

New exact-head CI, source-bound signed candidate, installer lifecycle acceptance,
Sandbox media soak, dedicated-tester installed-media verification and two-hour
soak, then prepared filler/caption/browser operator acceptance and publication.
The earlier be1260 installed/Sandbox failures remain preserved and rejected.
