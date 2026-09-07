# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T205614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 42.5 h of 2
- egress probes: 86, failing: 86
- heartbeats: 197
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 25996): cpu%= cpu_seconds_total=0.0625 rss_mb=16.5
- python (pid 27028): cpu%= cpu_seconds_total=9.625 rss_mb=778.1
- python (pid 31544): cpu%= cpu_seconds_total=4.09375 rss_mb=773.6
- python (pid 32820): cpu%= cpu_seconds_total=1.765625 rss_mb=438.8
- python (pid 45040): cpu%=23.97 cpu_seconds_total=42413.796875 rss_mb=1841

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32820, relaunches_total=85, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3629; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27028, relaunches_total=84, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31000, relaunches_total=84, relaunched_this_cycle=True, last_errors=System.Object[]
