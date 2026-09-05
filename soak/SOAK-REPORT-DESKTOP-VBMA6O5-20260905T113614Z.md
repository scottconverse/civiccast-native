# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T113614Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 2.5 h of 2
- egress probes: 7, failing: 5
- heartbeats: 83
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 24248): cpu%= cpu_seconds_total=0.375 rss_mb=25.3
- python (pid 4764): cpu%=278.65 cpu_seconds_total=34179.890625 rss_mb=1369.3
- python (pid 19148): cpu%=53.56 cpu_seconds_total=1806.296875 rss_mb=296.5
- python (pid 22156): cpu%= cpu_seconds_total=23.046875 rss_mb=3207.5
- python (pid 28560): cpu%= cpu_seconds_total=25.046875 rss_mb=6586.7

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3589; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=28560, relaunches_total=2, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=46372; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=19148, relaunches_total=1, relaunched_this_cycle=False, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=1483; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=35508, relaunches_total=3, relaunched_this_cycle=True, last_errors=
