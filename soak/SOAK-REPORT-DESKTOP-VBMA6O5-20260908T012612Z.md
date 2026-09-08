# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T012612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 47 h of 2
- egress probes: 95, failing: 95
- heartbeats: 206
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 15552): cpu%= cpu_seconds_total=8.09375 rss_mb=778
- python (pid 37804): cpu%= cpu_seconds_total=6 rss_mb=774.1
- python (pid 41744): cpu%= cpu_seconds_total=23.40625 rss_mb=750.8
- python (pid 45040): cpu%=30.34 cpu_seconds_total=47504.09375 rss_mb=1844

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3632; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=41744, relaunches_total=94, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3548; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=39388, relaunches_total=93, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=36304, relaunches_total=93, relaunched_this_cycle=True, last_errors=System.Object[]
