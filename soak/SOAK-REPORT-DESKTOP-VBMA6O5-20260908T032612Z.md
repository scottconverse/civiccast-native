# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T032612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 49 h of 2
- egress probes: 99, failing: 99
- heartbeats: 210
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 43820): cpu%= cpu_seconds_total=0.015625 rss_mb=16.4
- python (pid 21232): cpu%= cpu_seconds_total=8.46875 rss_mb=763.5
- python (pid 38132): cpu%= cpu_seconds_total=7.25 rss_mb=777
- python (pid 45040): cpu%=33.72 cpu_seconds_total=50147.734375 rss_mb=1845.1
- python (pid 47604): cpu%= cpu_seconds_total=10.546875 rss_mb=763.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1795; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27692, relaunches_total=98, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3625; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21232, relaunches_total=97, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=38088, relaunches_total=97, relaunched_this_cycle=True, last_errors=System.Object[]
