# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T192612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 17 h of 2
- egress probes: 35, failing: 35
- heartbeats: 146
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 38408): cpu%= cpu_seconds_total=5.828125 rss_mb=774.9
- python (pid 45040): cpu%=24.71 cpu_seconds_total=20406.8125 rss_mb=1829.5
- python (pid 46464): cpu%= cpu_seconds_total=10.453125 rss_mb=780.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47476, relaunches_total=34, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26904, relaunches_total=33, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2739; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33292, relaunches_total=34, relaunched_this_cycle=True, last_errors=
