# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T232612Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 45 h of 2
- egress probes: 91, failing: 91
- heartbeats: 202
- engine observed now: ffmpeg-fallback (gst=0 ffmpeg=1)

## worker process CPU/RSS (this probe)

- python (pid 24504): cpu%= cpu_seconds_total=9.171875 rss_mb=778.7
- python (pid 30540): cpu%= cpu_seconds_total=35.296875 rss_mb=736.1
- python (pid 45040): cpu%=38.17 cpu_seconds_total=45312.8125 rss_mb=2039.8
- python (pid 48068): cpu%= cpu_seconds_total=7.640625 rss_mb=777.2

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=24504, relaunches_total=90, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3644; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=48068, relaunches_total=89, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3663; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=46296, relaunches_total=89, relaunched_this_cycle=True, last_errors=System.Object[]
