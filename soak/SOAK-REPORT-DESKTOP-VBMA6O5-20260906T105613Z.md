# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T105613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 8.5 h of 2
- egress probes: 18, failing: 18
- heartbeats: 129
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 28752): cpu%= cpu_seconds_total=0.046875 rss_mb=24.6
- python (pid 19292): cpu%= cpu_seconds_total=1.9375 rss_mb=771.8
- python (pid 30308): cpu%= cpu_seconds_total=5.078125 rss_mb=774.3
- python (pid 39612): cpu%= cpu_seconds_total=3.09375 rss_mb=772.9
- python (pid 45040): cpu%=22.97 cpu_seconds_total=12826.203125 rss_mb=1827.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2875; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30308, relaunches_total=17, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42424, relaunches_total=16, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=18220, relaunches_total=17, relaunched_this_cycle=True, last_errors=
