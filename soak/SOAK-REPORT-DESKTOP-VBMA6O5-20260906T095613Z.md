# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T095613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 7.5 h of 2
- egress probes: 16, failing: 16
- heartbeats: 127
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 5176): cpu%= cpu_seconds_total=24.34375 rss_mb=767.7
- python (pid 42208): cpu%= cpu_seconds_total=3.078125 rss_mb=774.6
- python (pid 43136): cpu%= cpu_seconds_total=9.328125 rss_mb=777.2
- python (pid 45040): cpu%=23.39 cpu_seconds_total=12044.78125 rss_mb=1827.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42208, relaunches_total=15, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=, pid=, relaunches_total=14, relaunched_this_cycle=False, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3631; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=33704, relaunches_total=15, relaunched_this_cycle=True, last_errors=
