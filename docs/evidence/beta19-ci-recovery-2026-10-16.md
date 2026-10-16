# Beta 19 current-source claim binding correction

On October 16, 2026, the Beta 19 CI failure recovery reviewed the current
worker, engine, graph and live-engine test changes against their previous
registry blobs, then ran existing native GStreamer producers before updating
the nine stale bindings in `docs/claims/claims.yaml`.

The released runtime source is `7d61cbede3123a65b4a0d6d4b413ae99edbc3f04`.
The recovery worktree starts at `962f0a6e4d4f623cb5496a8e81e6dcbb96fc63fb`;
the changes between those commits affect documentation and the public
downloader, not these four runtime/test inputs. This recovery changes their
registry bindings and unit fixtures, not the runtime files or signed package.

| Input | Current Git blob |
| --- | --- |
| `civiccast/egress/gst/worker.py` | `295135425c3fdd323167e5addb63e4966b09434b` |
| `civiccast/egress/gst/engine.py` | `ba27385ef7bd1861f640d94b5074f53913236864` |
| `civiccast/egress/gst/graph.py` | `54fc1e5dd16c1fcdbe237b713dd3a9ed9ebbe638` |
| `tests/egress/test_gst_engine_wsl.py` | `0256a6784b2c0dd522d62ce6c8df262ebdd1c33a` |

Review covered native worker termination after pipeline cleanup, board audio
gain and live-zone selection, RTSP video-pad selection, compositor ordering,
the graph serialization additions and the new live-board pixel check. The
existing producer command was run from the recovery worktree in PowerShell:

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:CIVICCAST_GSTREAMER_RUNTIME_ROOT = 'C:\Program Files\CivicCast (Native)\runtime'
& 'C:\Dev\Claude\civiccast-beta19-release\.venv\Scripts\python.exe' -m pytest --no-cov -q tests/egress/test_gst_engine_wsl.py::test_board_live_video_is_visible_above_the_board_raster tests/egress/test_gst_engine_wsl.py::test_control_stop_does_not_hang tests/egress/test_gst_graph.py
```

Result: `32 passed in 10.97s`. Both live engine tests ran; none skipped.
The live-board test launched the current worker with a local SRT source,
captured encoded output and checked board/live-zone pixels. The stop test
exercised current native worker shutdown. The graph tests checked their
existing graph contracts. Dependencies were borrowed from the installed
runtime; test output and state used pytest temporary directories. No station
configuration, installation, signed artifact or running feed was changed by
this command.

The full output and actual Beta 19 CI logs are retained locally under
`C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\beta19-recovery-2026-10-16`,
including `claim-producers.log`, `ci-test-unit.log`, `test-junit/junit.xml` and
`diagnosis.md`. The original failed workflow is
[ci-test 38797803935](https://github.com/scottconverse/civiccast-native/actions/runs/38797803935).

These checks support the bounded current-source review tripwire rebind.
They do not renew the historical native decision-gate spike or pre-login
LocalSystem/service acceptance, establish an installed Beta 19 station result,
or prove every board gain, RTSP and reload failure mode. Historical claim
wording and its original external evidence remain unchanged.
