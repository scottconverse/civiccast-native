# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T072612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 29 h of 2
- egress probes: 59, failing: 59
- heartbeats: 170
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 46060): cpu%= cpu_seconds_total=0.375 rss_mb=9.9
- python (pid 21496): cpu%= cpu_seconds_total=64.3125 rss_mb=697.2
- python (pid 23564): cpu%= cpu_seconds_total=3.21875 rss_mb=772.1
- python (pid 45040): cpu%=24.54 cpu_seconds_total=29650.890625 rss_mb=1963.7

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=27432, relaunches_total=58, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=23564, relaunches_total=57, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29448, relaunches_total=58, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
