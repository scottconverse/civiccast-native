# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T195613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 17.5 h of 2
- egress probes: 36, failing: 36
- heartbeats: 147
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 13412): cpu%= cpu_seconds_total=0.015625 rss_mb=20
- python (pid 19892): cpu%= cpu_seconds_total=8.8125 rss_mb=778.8
- python (pid 23968): cpu%= cpu_seconds_total=11.0625 rss_mb=778
- python (pid 41568): cpu%= cpu_seconds_total=2.921875 rss_mb=771.7
- python (pid 45040): cpu%=20.43 cpu_seconds_total=20774.65625 rss_mb=1830.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2693; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=21364, relaunches_total=35, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2560; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29444, relaunches_total=34, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=18448, relaunches_total=35, relaunched_this_cycle=True, last_errors=
