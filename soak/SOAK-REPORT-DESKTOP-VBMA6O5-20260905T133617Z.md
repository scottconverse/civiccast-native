# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T133617Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 4.5 h of 2
- egress probes: 11, failing: 9
- heartbeats: 87
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=236.59 cpu_seconds_total=51398.71875 rss_mb=1045
- python (pid 9168): cpu%= cpu_seconds_total=58.34375 rss_mb=3267
- python (pid 35116): cpu%= cpu_seconds_total=85.109375 rss_mb=3126.9
- python (pid 41376): cpu%= cpu_seconds_total=147 rss_mb=289.9

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3641; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=41376, relaunches_total=6, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3760; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=25984, relaunches_total=5, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3637; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=28980, relaunches_total=7, relaunched_this_cycle=True, last_errors=
