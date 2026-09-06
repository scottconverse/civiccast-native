# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T102612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 8 h of 2
- egress probes: 17, failing: 17
- heartbeats: 128
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 23900): cpu%= cpu_seconds_total=2.765625 rss_mb=771.2
- python (pid 32648): cpu%= cpu_seconds_total=36.84375 rss_mb=756.8
- python (pid 33720): cpu%= cpu_seconds_total=17.171875 rss_mb=761.3
- python (pid 45040): cpu%=20.44 cpu_seconds_total=12412.484375 rss_mb=1825.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23900, relaunches_total=16, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=25924, relaunches_total=15, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32996, relaunches_total=16, relaunched_this_cycle=True, last_errors=
