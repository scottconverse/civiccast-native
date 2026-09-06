# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260906T132612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 11 h of 2
- egress probes: 23, failing: 23
- heartbeats: 134
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 22596): cpu%= cpu_seconds_total=5.234375 rss_mb=348.4
- ffmpeg (pid 44684): cpu%= cpu_seconds_total=0.109375 rss_mb=21.3
- python (pid 31804): cpu%= cpu_seconds_total=8.65625 rss_mb=766.6
- python (pid 43616): cpu%= cpu_seconds_total=44.4375 rss_mb=447.4
- python (pid 45040): cpu%=20.58 cpu_seconds_total=14870.15625 rss_mb=1829.5

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3625; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=34944, relaunches_total=22, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=47360, relaunches_total=21, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=43616, relaunches_total=22, relaunched_this_cycle=True, last_errors=
