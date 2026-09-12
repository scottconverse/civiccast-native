# Beta.7 dedicated tester mission R1

The poller-visible order is `soak/autorun/AUTORUN-BETA7-TESTER-MISSION-R1.ps1`.
It is beta.7-only and preserves the existing three CivicCastSoak coordination
tasks. Run it once on `DESKTOP-VBMA6O5`; do not replay it or alter completion
markers.

The issued identity is exact source
`a963c39cc44e2643065a818aac0206b110d515d4`, successful signed build
`34706796638`, and full Gate A PASS run `34710327291`. The expected kit hashes
are manifest `878b168e149fd19ca905baa10c2047c9c2418cb5b40a729d503050fde75074c1`
and installer `9346c3a791d20dedb9c17905f9c8982bb0e92773a2e0eac3d7735c0cd374ede7`.
The order downloads from the source-SHA-scoped LAN kit root, verifies every manifest entry,
performs the in-place upgrade, and starts one two-hour captions-ON plus two-hour
captions-OFF soak. It publishes phase-start receipts, status, verdict, and
bounded evidence through `tester/soak8-e1acfe6-DESKTOP-VBMA6O5`.
