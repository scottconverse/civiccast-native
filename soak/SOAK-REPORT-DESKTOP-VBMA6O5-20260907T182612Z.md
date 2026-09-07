# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T182612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 40 h of 2
- egress probes: 81, failing: 81
- heartbeats: 192
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 12072): cpu%= cpu_seconds_total=18.171875 rss_mb=755.7
- python (pid 24328): cpu%= cpu_seconds_total=2.5625 rss_mb=772.7
- python (pid 45040): cpu%=20.8 cpu_seconds_total=40213.546875 rss_mb=1839.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3010; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31692, relaunches_total=80, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3615; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24328, relaunches_total=79, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21596, relaunches_total=79, relaunched_this_cycle=True, last_errors=System.Object[]
