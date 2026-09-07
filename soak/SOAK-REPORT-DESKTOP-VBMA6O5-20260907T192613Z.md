# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T192613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 41 h of 2
- egress probes: 83, failing: 83
- heartbeats: 194
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 32112): cpu%= cpu_seconds_total=0 rss_mb=21.5
- python (pid 23600): cpu%= cpu_seconds_total=1.78125 rss_mb=38.1
- python (pid 28212): cpu%= cpu_seconds_total=3.328125 rss_mb=773.6
- python (pid 41700): cpu%= cpu_seconds_total=11.421875 rss_mb=768.6
- python (pid 45040): cpu%=23.24 cpu_seconds_total=41056.015625 rss_mb=1837.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28212, relaunches_total=82, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33492, relaunches_total=81, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3604; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27844, relaunches_total=81, relaunched_this_cycle=True, last_errors=System.Object[]
