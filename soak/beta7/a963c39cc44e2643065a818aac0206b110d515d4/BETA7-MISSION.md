# Beta.7 dedicated tester mission

This package is bound to the accepted pre-publication candidate:

- source `a963c39cc44e2643065a818aac0206b110d515d4`
- successful signed build `34706796638`
- full Gate A PASS `34710327291`
- manifest SHA-256 `878b168e149fd19ca905baa10c2047c9c2418cb5b40a729d503050fde75074c1`
- installer SHA-256 `9346c3a791d20dedb9c17905f9c8982bb0e92773a2e0eac3d7735c0cd374ede7`

The identity is bound to `1.0.0-beta.7`, `DESKTOP-VBMA6O5`, ports 9001/9002/9003, and the candidate-scoped LAN kit root `http://192.168.0.135:8766/a963c39cc44e2643065a818aac0206b110d515d4/`. The mission root is `C:\CivicCastSoak\missions\beta7-sep12-a963c39cc44e2643065a818aac0206b110d515d4`.

Run `Invoke-Beta7TesterUpgrade.ps1` first, then `Start-Beta7SoakJob.ps1`. Both use Windows PowerShell 5.1, target the existing tester, preserve the three `CivicCastSoak-*` coordination tasks, and enforce one-run paths. The soak runs captions ON and OFF for 120 minutes each with five-minute boundaries, GStreamer worker evidence, TSDuck transport grading, and fail-closed F-1/F-2/F-3 checks. The allowed element counts are phase-specific and come from the exact beta.7 Sandbox topology plus the preserved physical-tester topology for the same graph. No beta.5, beta.6, rejected beta.7, or 39e7 product bytes belong in this package.
