# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T015614Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 23.5 h of 2
- egress probes: 48, failing: 48
- heartbeats: 159
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 37672): cpu%= cpu_seconds_total=0.09375 rss_mb=25.3
- python (pid 21280): cpu%= cpu_seconds_total=7.734375 rss_mb=405.1
- python (pid 29356): cpu%= cpu_seconds_total=3.140625 rss_mb=656.1
- python (pid 38224): cpu%= cpu_seconds_total=44.296875 rss_mb=426.2
- python (pid 45040): cpu%=20.19 cpu_seconds_total=25506 rss_mb=1832.4

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2222; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=31208, relaunches_total=47, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2456; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26808, relaunches_total=46, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2601; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=26452, relaunches_total=47, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
