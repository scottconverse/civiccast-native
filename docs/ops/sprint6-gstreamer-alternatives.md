# Sprint 6: GStreamer alternatives

Decision, October 17, 2026: retain the existing selector and FFmpeg HLS relay
for this sprint. Item 24 requested consideration, not mandatory replacement.

The installed corrected Beta 19 runtime was queried through the production
GStreamer bootstrap and `Gst.ElementFactory.find`, without starting pipelines
or touching the running station:

```text
input-selector available
fallbackswitch absent
hlssink3 available
```

The source closure also stages `hlssink3` as an optional graph factory in
`civiccast/native/runtime_closure.py`. Older comments describing the runtime
without HLS factories are historical and must not be used to justify today's
choice.

## Selector

`InputSelectorSwap` in `civiccast/egress/gst/engine.py` already coordinates
audio/video switching, program reload and explicit live takeover. The daemon
implements failure budgets, cooldown and recoverable fallback. Introducing
`fallbackswitch` would require a new packaged plugin and adaptation of those
ownership rules. Its absence is not a demonstrated defect in the selector.
There is no measured benefit here that justifies changing a working broadcast
path during this preparation/integration sprint.

## HLS

Direct `hlssink3` is technically available for future work. It is not a drop-in
replacement for `HlsRelaySupervisor`: the current path owns configured output
directories, publication snapshots, retired-segment grace, restart numbering,
caption preservation and stalled-output recovery. A replacement would need to
carry those behaviors across rather than merely generate a playlist.

Existing Sprint 3 HLS evidence and the October 17 real media checks cover the
current relay, including advancing HTTP output and captions. No direct-sink
benchmark or comparative reliability claim is made. Retain the relay until a
specific performance or operational problem warrants that migration. No new
benchmark harness, build, soak or architecture rewrite is needed for this
assessment.
