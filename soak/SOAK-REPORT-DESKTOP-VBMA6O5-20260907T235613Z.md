# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T235613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 45.5 h of 2
- egress probes: 92, failing: 92
- heartbeats: 203
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 18556): cpu%= cpu_seconds_total=9.8125 rss_mb=764.3
- python (pid 28080): cpu%= cpu_seconds_total=21.046875 rss_mb=755.6
- python (pid 40416): cpu%= cpu_seconds_total=3.5 rss_mb=773.4
- python (pid 45040): cpu%=33.94 cpu_seconds_total=45923.984375 rss_mb=1843.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2393; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27804, relaunches_total=91, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35196, relaunches_total=90, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2236; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20884, relaunches_total=90, relaunched_this_cycle=True, last_errors=System.Object[]
