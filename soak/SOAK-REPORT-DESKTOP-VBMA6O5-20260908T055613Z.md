# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260908T055613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 51.5 h of 2
- egress probes: 104, failing: 104
- heartbeats: 215
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 44320): cpu%= cpu_seconds_total=0.03125 rss_mb=25.1
- python (pid 21128): cpu%= cpu_seconds_total=4.65625 rss_mb=773.9
- python (pid 32524): cpu%= cpu_seconds_total=20.53125 rss_mb=750.3
- python (pid 45040): cpu%=29.01 cpu_seconds_total=52740.40625 rss_mb=1848.2
- python (pid 46772): cpu%= cpu_seconds_total=2.53125 rss_mb=774.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21128, relaunches_total=103, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2511; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=46772, relaunches_total=102, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3646; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32524, relaunches_total=102, relaunched_this_cycle=True, last_errors=System.Object[]
