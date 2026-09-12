# Beta.7 physical soak R3

Run only `soak/autorun/AUTORUN-BETA7-TESTER-SOAK-R3.ps1` on
`DESKTOP-VBMA6O5`. Preserve R1 and R2 completely. R3 reuses the exact installed
candidate `a963c39cc44e2643065a818aac0206b110d515d4` and existing return checkout;
there is no installer or kit transfer.

The old schedule cannot cover another full mission, so R3 uses the supported
fresh-schedule path and cancels only overlapping scheduled/published test rows
through the supported API. Before any cancellation, every overlap must belong
to the exact 180 unique schedule IDs loaded from the single preserved R1 plan;
an unknown overlap aborts without cancelling anything. For both captions ON and captions OFF, R3 waits for
all three configured channels to become ON_AIR, records their original PIDs,
and runs TSDuck one channel at a time. It preserves one excluded 30-second
acquisition diagnostic and requires a second clean 30-second 0/0/0 admission
round before starting the full 120-minute measured phase. During and between
every serialized probe, all three channels must remain ON_AIR with those PIDs.

Each TSDuck input has a documented 10-second receive timeout. Each process
retains the 60-second hard lifecycle bound and must exit normally with code zero
before its report can be graded. Every measured report retains strict parsed
0/0/0 transport grading and the existing F1/F2/F3 checks.

Before task creation and again before result publication or station mutation,
R3 requires the upgrade PASS receipt and exact a963 source identity across the
candidate, build, Gate A, and installed native-app payload fields. Both admission
and measured probe registries are stopped by the outer cleanup path.
