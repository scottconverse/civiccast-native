# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T140620Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 5 h of 2
- egress probes: 12, failing: 10
- heartbeats: 88
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=229.88 cpu_seconds_total=55543.703125 rss_mb=983.6
- python (pid 17840): cpu%= cpu_seconds_total=27.140625 rss_mb=6706.7
- python (pid 41264): cpu%= cpu_seconds_total=179.234375 rss_mb=1016.5
- python (pid 46512): cpu%= cpu_seconds_total=128.46875 rss_mb=2540.1

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3638; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=17840, relaunches_total=7, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=46512, relaunches_total=6, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=1808, relaunches_total=8, relaunched_this_cycle=True, last_errors=
