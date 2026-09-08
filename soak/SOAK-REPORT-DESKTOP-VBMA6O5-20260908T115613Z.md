# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T115613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 57.5 h of 2
- egress probes: 116, failing: 116
- heartbeats: 227
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 15984): cpu%= cpu_seconds_total=31.8125 rss_mb=736.5
- python (pid 37364): cpu%= cpu_seconds_total=14.375 rss_mb=763.6
- python (pid 45040): cpu%=29.52 cpu_seconds_total=59183.59375 rss_mb=1850.8
- python (pid 45552): cpu%= cpu_seconds_total=20.546875 rss_mb=751.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37364, relaunches_total=115, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45552, relaunches_total=114, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2623; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36856, relaunches_total=114, relaunched_this_cycle=True, last_errors=System.Object[]
