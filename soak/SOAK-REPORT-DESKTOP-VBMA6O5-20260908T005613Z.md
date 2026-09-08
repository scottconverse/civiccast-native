# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T005613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 46.5 h of 2
- egress probes: 94, failing: 94
- heartbeats: 205
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 29512): cpu%= cpu_seconds_total=0.03125 rss_mb=25.4
- python (pid 8760): cpu%= cpu_seconds_total=11.75 rss_mb=762.3
- python (pid 29216): cpu%= cpu_seconds_total=15.28125 rss_mb=767.7
- python (pid 39996): cpu%= cpu_seconds_total=10.6875 rss_mb=763.2
- python (pid 45040): cpu%=25.9 cpu_seconds_total=46958.21875 rss_mb=1842.1

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=28660, relaunches_total=93, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3714; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21608, relaunches_total=92, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3439; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31280, relaunches_total=92, relaunched_this_cycle=True, last_errors=System.Object[]
