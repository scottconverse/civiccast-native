# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T125613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 34.5 h of 2
- egress probes: 70, failing: 70
- heartbeats: 181
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 2432): cpu%= cpu_seconds_total=0.046875 rss_mb=24.8
- python (pid 19480): cpu%= cpu_seconds_total=41.96875 rss_mb=740.2
- python (pid 26500): cpu%= cpu_seconds_total=8.75 rss_mb=776.8
- python (pid 33936): cpu%= cpu_seconds_total=69.578125 rss_mb=694.2
- python (pid 45040): cpu%=24.11 cpu_seconds_total=35036.515625 rss_mb=1838.3

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2435; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=44064, relaunches_total=69, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2314; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26500, relaunches_total=68, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=4948, relaunches_total=68, relaunched_this_cycle=True, last_errors=System.Object[]
