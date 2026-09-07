# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T045614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 26.5 h of 2
- egress probes: 54, failing: 54
- heartbeats: 165
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 27564): cpu%= cpu_seconds_total=0.0625 rss_mb=20.6
- python (pid 19024): cpu%= cpu_seconds_total=47.15625 rss_mb=728.3
- python (pid 24420): cpu%= cpu_seconds_total=13.640625 rss_mb=777.8
- python (pid 34084): cpu%= cpu_seconds_total=6.96875 rss_mb=773.7
- python (pid 45040): cpu%=22.93 cpu_seconds_total=27611.8125 rss_mb=1834.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=307; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=11496, relaunches_total=53, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3561; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34084, relaunches_total=52, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34316, relaunches_total=53, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
