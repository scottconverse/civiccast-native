# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T172612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 39 h of 2
- egress probes: 79, failing: 79
- heartbeats: 190
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 21820): cpu%= cpu_seconds_total=0.015625 rss_mb=19.8
- python (pid 30328): cpu%= cpu_seconds_total=11.953125 rss_mb=779.5
- python (pid 30800): cpu%= cpu_seconds_total=4.34375 rss_mb=775.1
- python (pid 32528): cpu%= cpu_seconds_total=19.0625 rss_mb=769.3
- python (pid 45040): cpu%=27.86 cpu_seconds_total=39280.15625 rss_mb=2010.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2462; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30800, relaunches_total=78, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2616; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=20604, relaunches_total=77, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3692; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30328, relaunches_total=77, relaunched_this_cycle=True, last_errors=System.Object[]
