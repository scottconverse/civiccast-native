# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T102612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 32 h of 2
- egress probes: 65, failing: 65
- heartbeats: 176
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 30736): cpu%= cpu_seconds_total=0.046875 rss_mb=20.4
- python (pid 7968): cpu%= cpu_seconds_total=23.1875 rss_mb=767.4
- python (pid 10228): cpu%= cpu_seconds_total=2.84375 rss_mb=773.7
- python (pid 24768): cpu%= cpu_seconds_total=60.15625 rss_mb=721.8
- python (pid 45040): cpu%=22.78 cpu_seconds_total=32801.0625 rss_mb=1835.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2319; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24768, relaunches_total=64, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2210; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=7968, relaunches_total=63, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22332, relaunches_total=63, relaunched_this_cycle=True, last_errors=System.Object[]
