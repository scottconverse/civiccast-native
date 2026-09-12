# Beta.7 physical soak R2 recovery

Run only `soak/autorun/AUTORUN-BETA7-TESTER-SOAK-R2.ps1` on
`DESKTOP-VBMA6O5`. R1 is preserved evidence: its fail-closed cleanup stopped all
three channels at 2026-09-12T23:02:27Z after the first transport probe began at
the measured schedule boundary.

R2 uses the already-installed exact candidate
`a963c39cc44e2643065a818aac0206b110d515d4`, the existing verified return
checkout, and R1's still-valid published schedule. It does not install,
republish, cancel, or rewrite channel configuration. Outside measurement it
starts the three existing public/education/government channel configurations,
waits for all three to become ON_AIR, preserves one 30-second acquisition
diagnostic excluded from the verdict, and requires a second 30-second clean
0/0/0 transport round on all three channels before each measured phase. Only
then does each full 120-minute captions-ON or captions-OFF measurement begin. Every measured
TSDuck round retains zero tolerance, and the existing F1/F2/F3 grading remains
unchanged.

The R2 task, stable script folder, output, return path, report, and archive are
all R2-specific. Do not replay R2 or alter R1 markers/evidence.
