# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T152612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 37 h of 2
- egress probes: 75, failing: 75
- heartbeats: 186
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 8964): cpu%= cpu_seconds_total=6.21875 rss_mb=773.7
- python (pid 23616): cpu%= cpu_seconds_total=13.59375 rss_mb=762.4
- python (pid 45040): cpu%=19.63 cpu_seconds_total=37315.375 rss_mb=1836.7
- python (pid 47272): cpu%= cpu_seconds_total=4.890625 rss_mb=773.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=8964, relaunches_total=74, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3548; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=40664, relaunches_total=73, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3667; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=6440, relaunches_total=73, relaunched_this_cycle=True, last_errors=System.Object[]
