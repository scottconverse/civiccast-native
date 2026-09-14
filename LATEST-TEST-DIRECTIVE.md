# soak8-e1acfe6 Latest Test Directive

Current: soak/DIRECTIVE-BETA7-R15-POSTHOC-R16-R1.md

Autorun: soak/autorun/AUTORUN-BETA7-R15-POSTHOC-R16-R1.ps1

R15 completed the full four-hour clock with all 4,320 state samples ON_AIR,
stable worker PIDs, 144/144 programme changes, 480/480 healthy service samples,
and 24/24 clean transport probes. Its final log collector then mistook normal
10 MiB `control_plane-app.log` rotation for truncation before grading the
preserved terminal worker logs. R16-R1 retrieves the exact `all-raw` snapshot
that R15 copied locally during cleanup. It is evidence recovery only: no station
change and no soak rerun.

The R15 failure archive SHA-256 is
`ee2edeb12d701d460f607acf4a400a180698107f9dcf5948464945c685ceb6d1`.

---

Previous directive follows.

Candidate: 3e117ff1fa9e06873ecec5b5b07f1360bc8b228d, build 34762831824,
Gate A PASS run 34772707033. Captions are OFF. The measured gate is exactly
four hours on DESKTOP-VBMA6O5.

R5 is invalidated at tester evidence commit
0c90c8bce3f0cbe36af9671a5bbea91116d832a6. R6 stopped in package preflight
before creating a mission root or changing the station because it required
PowerShell 7 on the Windows PowerShell 5 tester. R7 stopped later in read-only
adoption preflight at `directive-package-clean`: its Windows-to-Git path
conversion treated a lone backslash as a regular expression. R8 stopped before
station mutation because it incorrectly required a currently executing disabled
Scheduled Task to report state Disabled; Windows correctly reports state Running
with Settings.Enabled=false. R9 stopped after publishing STARTED because the
outer launcher compared the adoption-updated receipt with its stale pre-adoption
identity. R10 passed that corrected remote-start gate, then stopped before
measurement because the physical job did not pass the exact invalidated R5 plan
IDs into its bounded schedule replacement path. R11 verifies the receipt-bound
R5 plan hash and its 180 unique schedule IDs, then permits cancellation only for
live overlaps in that exact set. Any unrelated row fails before cancellation.
R11 cancelled the 21 remaining R5 rows, then its supervisor-restart shutdown
barrier timed out and left the channel configs disabled. R12 repaired that
barrier and reached complete controlled programme changes on all three
channels. It then falsely failed because it treated beta.5's `elements=146`
graph size as universal. The exact beta.7 captions-OFF evidence instead proves
healthy `elements=132` twelve-segment slate graphs and healthy `elements=33`
one-segment programme graphs, with complete preroll and handoff receipts plus
continued output. R13 binds that R12 evidence hash and corrects only the stale
topology rule while retaining worker-exit, missing-preroll, output-stall,
wrong-source, missing-PID, `56`/`74`, and transport failures.

R13 then stopped in package preflight before a mission root or station change:
Git supplied LF text on the tester and CRLF text on the coordinator, while R13
compared raw manifest bytes. R14 corrected that boundary and reached complete
controlled transitions on all three channels. It then falsely failed because
stdout and stderr were sliced independently but the grader required their
commit counts to match. Each channel had four complete stdout commits and one
complete stderr diagnostic commit with subsequent output; there were no worker
exits, stalls, or 56/74 partial graphs.

R15 removes only that invalid cross-file count assertion. Its tests replay the
six exact R14 slices as a healthy 4-to-1 boundary and replay an exact beta.5
Blackwell death log as a failure. Missing preroll, missing selector handoff or
old-tail detach, 56/74/146 topology, clean worker exit, output stall, and no
post-commit output remain failures. The exact committed package passed under
Windows PowerShell 5.1 and PowerShell 7 from a fresh LF-only Git archive.

R15's source anchor is b4696c97c9f33cd6b81f6d73caa3cd879950e69f, its binding
commit is d0da1b61acafff70d1a1e8be45667b587794f9b7, and its harness manifest
SHA-256 is e6875a33e412f7597cb660a38cfe6d4856768384b52bd23f40ba653ff067b428.

Execute the R15 autorun once. It must refuse any identity, package, host,
receipt, schedule, topology, task, or evidence mismatch. It must return
success only after the physical task publishes and remotely verifies its
STARTED receipt. Preserve all evidence on either pass or failure.

This directive authorizes the four-hour beta.7 candidate soak only. It does
not authorize tagging or publication. If this gate passes, the separate
eight-hour overnight soak is still required before beta.7 publication.
