# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T112613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 57 h of 2
- egress probes: 115, failing: 115
- heartbeats: 226
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 33920): cpu%= cpu_seconds_total=0.03125 rss_mb=20.8
- python (pid 28244): cpu%= cpu_seconds_total=10.875 rss_mb=763.3
- python (pid 34224): cpu%= cpu_seconds_total=8.984375 rss_mb=763.3
- python (pid 45004): cpu%= cpu_seconds_total=7.296875 rss_mb=778.4
- python (pid 45040): cpu%=29.51 cpu_seconds_total=58652.140625 rss_mb=1851.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2598; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=45004, relaunches_total=114, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2643; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28876, relaunches_total=113, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3632; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34836, relaunches_total=113, relaunched_this_cycle=True, last_errors=System.Object[]
