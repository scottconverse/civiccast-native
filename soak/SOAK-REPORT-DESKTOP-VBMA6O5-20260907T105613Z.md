# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T105613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 32.5 h of 2
- egress probes: 66, failing: 66
- heartbeats: 177
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 5140): cpu%= cpu_seconds_total=31.546875 rss_mb=757.1
- python (pid 27052): cpu%= cpu_seconds_total=8.421875 rss_mb=777
- python (pid 28256): cpu%= cpu_seconds_total=48.421875 rss_mb=711
- python (pid 45040): cpu%=22.1 cpu_seconds_total=33199.0625 rss_mb=1835.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3093; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27052, relaunches_total=65, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2575; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23684, relaunches_total=64, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31028, relaunches_total=64, relaunched_this_cycle=True, last_errors=System.Object[]
