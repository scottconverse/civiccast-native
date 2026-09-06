# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T115612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 9.5 h of 2
- egress probes: 20, failing: 20
- heartbeats: 131
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 12344): cpu%= cpu_seconds_total=0.046875 rss_mb=25.2
- python (pid 22380): cpu%= cpu_seconds_total=14.953125 rss_mb=763.2
- python (pid 23716): cpu%= cpu_seconds_total=12.984375 rss_mb=778.2
- python (pid 45040): cpu%=19.12 cpu_seconds_total=13476.5 rss_mb=1825.4
- python (pid 46092): cpu%= cpu_seconds_total=21.09375 rss_mb=767.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3683; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22832, relaunches_total=19, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23716, relaunches_total=18, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3613; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42224, relaunches_total=19, relaunched_this_cycle=True, last_errors=
