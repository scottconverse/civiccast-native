# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T205613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 18.5 h of 2
- egress probes: 38, failing: 38
- heartbeats: 149
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 12044): cpu%= cpu_seconds_total=17.90625 rss_mb=428.2
- python (pid 21952): cpu%= cpu_seconds_total=8.390625 rss_mb=777.4
- python (pid 38472): cpu%= cpu_seconds_total=13.75 rss_mb=766.4
- python (pid 45040): cpu%=31.69 cpu_seconds_total=21699.59375 rss_mb=1833.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3611; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34880, relaunches_total=37, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=12044, relaunches_total=36, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22632, relaunches_total=37, relaunched_this_cycle=True, last_errors=
