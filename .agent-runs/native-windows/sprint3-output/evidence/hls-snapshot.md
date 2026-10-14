# HLS live-manifest snapshot evidence

Branch: `codex/sprint3-output-completion`  
Scope: synchronize the live HLS publisher's in-place playlist writes with public
playlist reads; keep segment responses and VOD responses on their existing file
paths. No station configuration or service was changed.

## Change

`civiccast/stream/live_manifest_lock.py` owns one process-local lock shared by
`_ManifestPublisher._write_manifest` and the live media route. The route keeps
the lock only while reading manifest bytes, then returns a normal byte
`Response`, so the file is closed before a slow client receives the response.
The writer still updates the advertised manifest in place, preserving the U51
Windows behavior. The existing containment check, HLS content type, live
manifest cache header, and segment `FileResponse` remain in effect.

## Evidence

Baseline before the change:

```text
python -m pytest tests/stream/test_media_router_live.py tests/egress/test_hls_relay.py -q
39 passed in 2.19s
```

The new concurrent integration regression was run before the lock was wired in:

```text
python -m pytest tests/stream/test_media_router_live.py::TestServeLiveManifest::test_manifest_response_waits_for_publisher_and_captures_complete_bytes -q
1 failed in 6.83s
```

It failed at the assertion waiting for the route's second shared-lock acquisition,
which did not occur before the fix. The test pauses the in-place publisher after
writing only part of the replacement bytes, starts an HTTP read, and then checks
that the read waits and returns exactly the completed replacement.

After the fix, the focused regression passed:

```text
python -m pytest tests/stream/test_media_router_live.py::TestServeLiveManifest::test_manifest_response_waits_for_publisher_and_captures_complete_bytes -q
1 passed in 1.62s
```

Affected live-media and relay tests after the snapshot change passed:

```text
python -m pytest tests/stream/test_media_router_live.py tests/egress/test_hls_relay.py -q
40 passed in 2.28s
```

Lint passed:

```text
python -m ruff check civiccast/stream/media_router.py civiccast/stream/live_manifest_lock.py civiccast/egress/hls_relay.py tests/stream/test_media_router_live.py
All checks passed!
```

`git diff --check -- civiccast/stream/media_router.py civiccast/egress/hls_relay.py tests/stream/test_media_router_live.py`
exited 0 with no output.

The formatter check was also run on those four Python files plus the new lock
module. It reported only parallel formatting in the pruning helper and EOS
test edits in `civiccast/egress/hls_relay.py` and
`tests/egress/test_hls_relay.py`; it did not flag the snapshot or restart
cleanup changes. I left those unrelated lines untouched. Ruff lint passed on
all touched Python files.

## Restart cleanup correction

Fresh/dead relay startup now attempts to remove the advertised playlist while
holding the same lock as HTTP playlist snapshots and publisher writes. It keeps the
playlist's referenced segments through their existing measured retirement
deadlines and gives any other safe numeric segment file one conservative
playlist-window grace. The new FFmpeg child starts after the largest retained
segment number. This avoids exposing a playlist whose files have already been
deleted during cleanup and avoids overwriting files named by responses already
copied by the route. Temporary/staging debris is still removed. A live relay
rebind keeps its current public window.

The restart regression checks withdrawal, retention of a listed and an
unlisted numeric segment through grace, pruning after grace, and publication
using the next sequence number. Results:

```text
python -m pytest tests/egress/test_hls_relay.py::test_fresh_restart_withdraws_old_playlist_and_retains_its_segments_until_expiry tests/egress/test_hls_relay.py::test_new_session_withdraws_fresh_or_dead_playlist_but_preserves_referenced_segments -q
2 passed in 1.24s

python -m pytest tests/stream/test_media_router_live.py tests/egress/test_hls_relay.py -q
41 passed in 1.90s
```

Final lint passed:

```text
python -m ruff check civiccast/stream/media_router.py civiccast/stream/live_manifest_lock.py civiccast/egress/hls_relay.py tests/stream/test_media_router_live.py tests/egress/test_hls_relay.py
All checks passed!
```

The exact formatting check was:

```text
python -m ruff format --check civiccast/stream/media_router.py civiccast/stream/live_manifest_lock.py civiccast/egress/hls_relay.py tests/stream/test_media_router_live.py tests/egress/test_hls_relay.py
```

It reported two files would be reformatted: `civiccast/egress/hls_relay.py`
in the parallel pruning helper and `tests/egress/test_hls_relay.py` in parallel
EOS test edits. It did not flag the restart cleanup or its assertions. I left
those unrelated lines untouched. The exact whitespace check was:

```text
git diff --check -- civiccast/stream/media_router.py civiccast/stream/live_manifest_lock.py civiccast/egress/hls_relay.py tests/stream/test_media_router_live.py tests/egress/test_hls_relay.py
```

It exited 0 without output.

The lock coordinates only the current single control process. It does not
coordinate an independent process or an external file reader. A segment
snapshot remains safe through the configured measured or one-window grace;
there is no guarantee for a client that retains a playlist longer than that
bounded period. If an external process holds the manifest so it cannot be
removed, startup logs the skipped file and retains its numeric segments. The
lock still keeps this process's route out of the cleanup operation. No station
config or service was changed. Parent owns manual,
ops, and generated API documentation updates; they should describe
lock-protected byte snapshots for live playlists, unchanged segment file
responses, and bounded segment retention across fresh/dead relay startup.
