# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T225613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 44.5 h of 2
- egress probes: 90, failing: 90
- heartbeats: 201
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 23368): cpu%= cpu_seconds_total=12.09375 rss_mb=765.3
- python (pid 31748): cpu%= cpu_seconds_total=17.5625 rss_mb=747.9
- python (pid 34628): cpu%= cpu_seconds_total=13.3125 rss_mb=765.2
- python (pid 45040): cpu%=30 cpu_seconds_total=44626.046875 rss_mb=1842.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31748, relaunches_total=89, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3604; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27832, relaunches_total=88, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3550; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34628, relaunches_total=88, relaunched_this_cycle=True, last_errors=System.Object[]
