# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T142612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 12 h of 2
- egress probes: 25, failing: 25
- heartbeats: 136
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 40720): cpu%= cpu_seconds_total=0.15625 rss_mb=21
- python (pid 13796): cpu%= cpu_seconds_total=4.546875 rss_mb=774.5
- python (pid 26264): cpu%= cpu_seconds_total=12.296875 rss_mb=777.4
- python (pid 31044): cpu%= cpu_seconds_total=38.75 rss_mb=446.2
- python (pid 45040): cpu%=23.5 cpu_seconds_total=15933.671875 rss_mb=1827.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=13796, relaunches_total=24, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3613; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=37148, relaunches_total=23, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33128, relaunches_total=24, relaunched_this_cycle=True, last_errors=
