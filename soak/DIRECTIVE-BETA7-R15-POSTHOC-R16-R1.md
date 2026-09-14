# Beta.7 R15 terminal-log recovery R16-R1

Run `soak/autorun/AUTORUN-BETA7-R15-POSTHOC-R16-R1.ps1` once on
`DESKTOP-VBMA6O5`.

This is a read-only evidence recovery for exact candidate
`3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`. R15 completed its full four-hour
clock, terminal state checks, and transport schedule, then its final collector
mistook normal `control_plane-app.log` rotation for truncation. R15 preserved an
exact terminal `all-raw` snapshot locally before uploading its failure archive.

The order must bind the exact R15 mission, terminal error, and evidence SHA-256
`ee2edeb12d701d460f607acf4a400a180698107f9dcf5948464945c685ceb6d1`, then
publish the preserved three-channel GStreamer worker logs and bounded control
plane rotation chain to the tester evidence branch. It must not reinstall,
start or stop services, alter channels or schedules, rerun the soak, or read the
staff token.
