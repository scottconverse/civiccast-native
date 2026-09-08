# Exact beta.5 tester installation diagnostic

R2 returned18:36:13UTC with a property-missing error and no completed install.
PowerShell wrapped the long script path in its log, so the initial location
parser found no line. R3 preserves R1/R2 and recognizes whitespace-wrapped
known script names, plus the exact known `sha256` property-error phrase.
Only known filename/line/character and fixed category values are exported.
Actual filesystem classifier tests18PASS perPowerShell engine.

R1 returned successfully at18:26:13UTC. It showed the initial identity had no
verified-artifact or installed receipt, no soak state, and the older installed
service still running. Its original autorun log stopped at16:06:39UTC. The
known ffprobe, completed-upgrade and signature-rejection phrases were absent.
This is a pre-install verification failure, not a completed upgrade/soak.

R2 uses a new `install-inventory-r2` directory and report; R1 is preserved.
It adds fixed pre-install error categories and known script-name/line/character
locations plus a bounded PowerShell category name. No arbitrary error text or
log contents are exported. Null pending hash fields are valid JSON and no
longer incorrectly mark the identity as malformed; they remain no proof of
completed artifact verification or installation. Actual adapter tests16PASS
on both PS5.1/PS7, plus inventory contracts and inert wrapper plans.

This support package is not shipped CivicCast product code. Its unique
`AUTORUN-SEP8-BETA5-INSTALL-INVENTORY-R1.ps1` directive uses the existing
tester poll channel, only on DESKTOP-VBMA6O5, for mission
beta5-sep8-be1260bd0630 / signed sourcebe1260bd / build34237280539.

It creates a fresh mission-local `install-inventory-r1` evidence directory
and separate Git return checkout. It never reruns the installer, changes a
service/task, reads the operator token, calls a station API, or overwrites
the original mission bin. Existing diagnostic state refuses a blind rerun.

The report contains selected receipt fields, exact marker/file metadata,
service executable/PID/start, bounded kit file counts/sizes, and names,
PIDs, parents, start times and CPU for selected setup/helper processes.
Generic helper names can include unrelated processes; metadata alone does
not establish that they belong to this installation. No process command
line is collected or exported.

Up to three original autorun logs, at most4MiB each, are internally inspected
for fixed known failure/success phrases. Only boolean signals are exported,
not log text, arbitrary exception messages, tokens, or credentials. Oversize
logs are explicitly skipped. Collection errors produce a safe failure receipt.

`receipt_matches_expected` checks listed mission identity fields only. It is
not proof that installation completed, that the current runtime matches the
candidate, or that a soak passed. Known log phrases are diagnostic leads,
not substitutes for fresh installed-source and final media verdicts.

The wrapper defaults to execution because the existing poller is the authorized
dispatch mechanism. Use `-DryRun` for a plan only, on either host. The support
draft itself remains non-executing unless the wrapper binds its read adapters.

Validation: root and independent Terra ran parsers, PS5.1/PS7 inventory
contracts, wrapper DryRun, and12 actual filesystem adapter assertions per
engine. No live diagnostic result existed when this directive was prepared.
The tests do not claim that Git return publication has already succeeded.
