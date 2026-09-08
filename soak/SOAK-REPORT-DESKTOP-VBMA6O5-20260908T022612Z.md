# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T022612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 48 h of 2
- egress probes: 97, failing: 97
- heartbeats: 208
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 31428): cpu%= cpu_seconds_total=0.03125 rss_mb=20.6
- python (pid 20544): cpu%= cpu_seconds_total=4.890625 rss_mb=774.5
- python (pid 25480): cpu%= cpu_seconds_total=5.703125 rss_mb=777.3
- python (pid 35232): cpu%= cpu_seconds_total=2.890625 rss_mb=774.2
- python (pid 45040): cpu%=39.94 cpu_seconds_total=48932.171875 rss_mb=1846.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=35232, relaunches_total=96, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3638; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20544, relaunches_total=95, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2974; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47220, relaunches_total=95, relaunched_this_cycle=True, last_errors=System.Object[]
