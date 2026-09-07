# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T115613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 33.5 h of 2
- egress probes: 68, failing: 68
- heartbeats: 179
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 45900): cpu%= cpu_seconds_total=0.03125 rss_mb=24.7
- python (pid 26204): cpu%= cpu_seconds_total=11 rss_mb=777.8
- python (pid 28692): cpu%= cpu_seconds_total=2.25 rss_mb=772.3
- python (pid 45040): cpu%=22.95 cpu_seconds_total=34001.3125 rss_mb=1837.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2366; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41232, relaunches_total=67, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2293; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26204, relaunches_total=66, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28692, relaunches_total=66, relaunched_this_cycle=True, last_errors=System.Object[]
