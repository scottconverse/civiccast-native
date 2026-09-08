# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T065612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 52.5 h of 2
- egress probes: 106, failing: 106
- heartbeats: 217
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 27892): cpu%= cpu_seconds_total=15.453125 rss_mb=749
- python (pid 32236): cpu%= cpu_seconds_total=10.53125 rss_mb=763.7
- python (pid 35516): cpu%= cpu_seconds_total=2.75 rss_mb=773.3
- python (pid 45040): cpu%=23.76 cpu_seconds_total=53663.4375 rss_mb=1847.6

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42144, relaunches_total=105, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=22280, relaunches_total=104, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=41540, relaunches_total=104, relaunched_this_cycle=True, last_errors=System.Object[]
