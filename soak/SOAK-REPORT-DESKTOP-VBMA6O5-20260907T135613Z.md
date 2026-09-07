# soak8-e1acfe6 rollup -- DESKTOP-VBMA6O5 -- 20260907T135613Z

- soak start (UTC): 2026-09-06T02:26:16.5653747Z
- elapsed: 35.5 h of 2
- egress probes: 72, failing: 72
- heartbeats: 183
- engine observed now: none-running (gst=0 ffmpeg=0)

## worker process CPU/RSS (this probe)

- ffmpeg (pid 14512): cpu%= cpu_seconds_total=0.09375 rss_mb=20.9
- python (pid 18560): cpu%= cpu_seconds_total=25.296875 rss_mb=752.7
- python (pid 29068): cpu%= cpu_seconds_total=16.234375 rss_mb=762.3
- python (pid 36692): cpu%= cpu_seconds_total=8.8125 rss_mb=777.3
- python (pid 45040): cpu%=26.86 cpu_seconds_total=35959.671875 rss_mb=1957.8

## per-channel, this probe

- **public** (udp 9001): tsduck=fail-timed-out, packets=, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=2204, relaunches_total=71, relaunched_this_cycle=True, last_errors=
- **education** (udp 9002): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2340; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=29068, relaunches_total=70, relaunched_this_cycle=True, last_errors=No valid source plan is available; generated fallback slate.
- **government** (udp 9003): tsduck=pass, packets=@{invalid-syncs=0; suspect-ignored=0; total=2554; transport-errors=0}, invalid_syncs=, transport_errors=, discontinuities=, engine_state=ON_AIR, engine=gstreamer, pid=42180, relaunches_total=70, relaunched_this_cycle=True, last_errors=System.Object[]
