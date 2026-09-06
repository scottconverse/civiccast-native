# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T185613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 16.5 h of 2
- egress probes: 34, failing: 34
- heartbeats: 145
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 488): cpu%= cpu_seconds_total=0.015625 rss_mb=19.8
- python (pid 22748): cpu%= cpu_seconds_total=28.140625 rss_mb=437.6
- python (pid 34140): cpu%= cpu_seconds_total=39.1875 rss_mb=436.5
- python (pid 45040): cpu%=24.28 cpu_seconds_total=19962.25 rss_mb=1830.9
- python (pid 46336): cpu%= cpu_seconds_total=6.390625 rss_mb=774.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3609; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=46336, relaunches_total=33, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22692, relaunches_total=32, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=9512, relaunches_total=33, relaunched_this_cycle=True, last_errors=
