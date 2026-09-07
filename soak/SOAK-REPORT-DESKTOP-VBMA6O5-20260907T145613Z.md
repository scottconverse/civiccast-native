# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T145613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 36.5 h of 2
- egress probes: 74, failing: 74
- heartbeats: 185
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 6352): cpu%= cpu_seconds_total=7.421875 rss_mb=765.1
- python (pid 27440): cpu%= cpu_seconds_total=3.3125 rss_mb=774.3
- python (pid 40852): cpu%= cpu_seconds_total=22.125 rss_mb=739.9
- python (pid 45040): cpu%=27.91 cpu_seconds_total=36962.234375 rss_mb=1838.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3651; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40852, relaunches_total=73, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35516, relaunches_total=72, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37560, relaunches_total=72, relaunched_this_cycle=True, last_errors=System.Object[]
