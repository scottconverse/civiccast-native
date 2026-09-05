# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T130616Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 4 h of 2
- egress probes: 10, failing: 8
- heartbeats: 86
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=236.37 cpu_seconds_total=47139.0625 rss_mb=1156.4
- python (pid 20720): cpu%= cpu_seconds_total=152.921875 rss_mb=878.3
- python (pid 33888): cpu%= cpu_seconds_total=110.140625 rss_mb=3277.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3612; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=35224, relaunches_total=5, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3642; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=20720, relaunches_total=4, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=21892, relaunches_total=6, relaunched_this_cycle=True, last_errors=
