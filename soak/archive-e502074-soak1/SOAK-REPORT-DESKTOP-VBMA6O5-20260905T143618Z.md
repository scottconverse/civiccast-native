# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260905T143618Z

- soak start (UTC): 2026-09-05T09:06:14.8833448Z
- elapsed: 5.5 h of 2
- egress probes: 13, failing: 11
- heartbeats: 89
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- python (pid 4764): cpu%=227.88 cpu_seconds_total=59641.015625 rss_mb=982.1
- python (pid 22012): cpu%= cpu_seconds_total=104.125 rss_mb=4529.7
- python (pid 22936): cpu%= cpu_seconds_total=59.234375 rss_mb=1695.1
- python (pid 24664): cpu%= cpu_seconds_total=36.421875 rss_mb=5955.6

## per-channel, this probe

- **public** (udp 9001): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3638; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=22936, relaunches_total=8, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=3640; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=gstreamer, pid=22012, relaunches_total=7, relaunched_this_cycle=True, last_errors=
- **government** (udp 9003): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=FALLBACK_SLATE, engine=, pid=27468, relaunches_total=9, relaunched_this_cycle=True, last_errors=
