# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T145612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 12.5 h of 2
- egress probes: 26, failing: 26
- heartbeats: 137
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 34772): cpu%= cpu_seconds_total=0.09375 rss_mb=21.5
- python (pid 4120): cpu%= cpu_seconds_total=45.328125 rss_mb=445.4
- python (pid 45040): cpu%=22.74 cpu_seconds_total=16343.171875 rss_mb=1830

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3604; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22188, relaunches_total=25, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=8772, relaunches_total=24, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3548; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=10716, relaunches_total=25, relaunched_this_cycle=True, last_errors=
