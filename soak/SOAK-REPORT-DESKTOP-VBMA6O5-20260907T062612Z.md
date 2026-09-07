# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T062612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 28 h of 2
- egress probes: 57, failing: 57
- heartbeats: 168
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 5800): cpu%= cpu_seconds_total=0.03125 rss_mb=20.7
- python (pid 488): cpu%= cpu_seconds_total=3.90625 rss_mb=772.5
- python (pid 29240): cpu%= cpu_seconds_total=62.828125 rss_mb=701.7
- python (pid 43876): cpu%= cpu_seconds_total=13.609375 rss_mb=763.7
- python (pid 45040): cpu%=24.37 cpu_seconds_total=28777.546875 rss_mb=1833.8

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2283; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43876, relaunches_total=56, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2897; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=488, relaunches_total=55, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3639; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=43372, relaunches_total=56, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
