# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T132612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 35 h of 2
- egress probes: 71, failing: 71
- heartbeats: 182
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 13620): cpu%= cpu_seconds_total=0.015625 rss_mb=16.5
- python (pid 32996): cpu%= cpu_seconds_total=3.65625 rss_mb=773.7
- python (pid 45040): cpu%=24.42 cpu_seconds_total=35475.8125 rss_mb=1838.4
- python (pid 45820): cpu%= cpu_seconds_total=8.453125 rss_mb=776.5
- python (pid 46784): cpu%= cpu_seconds_total=44 rss_mb=737.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2387; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=46784, relaunches_total=70, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3353; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=32996, relaunches_total=69, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3645; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=30008, relaunches_total=69, relaunched_this_cycle=True, last_errors=System.Object[]
