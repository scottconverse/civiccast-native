# Installed beta.5 failure diagnostic R5

The autorun `AUTORUN-SEP8-BETA5-INSTALLED-DIAGNOSTIC-R5.ps1` is scoped to
DESKTOP-VBMA6O5 and mission beta5-sep8-be1260bd0630, source be1260bd0630261c571e3adf5aac6a6cbebd9e3a.
It collects existing installed-identity receipts, current hashes of the two
candidate-bound runtime files, service metadata, and bounded stage/stack
signals from the three workers' stdout/stderr. It never reads the token,
changes station settings, retries installation, or starts a soak/browser.

Only its new `installed-diagnostic-r5` report/helper directory and fresh Git
return clone are written. Existing state is not replaced. Original logs and
receipts remain private on the tester; returned JSON contains allowlisted
identity fields and numeric stage counts, not raw logs or command lines.
The single retry journal describes its last state, not a per-step history.

Run the autorun with `-DryRun` to inspect the plan without collecting/writing.
The collector's DRAFT filename is retained to match the reviewed fixture; the
autorun explicitly loads its library and invokes its real read-only adapters.
The standalone workspace launcher is not part of this dispatch package.

Validation: real temporary file/JSON/log fixtures in PowerShell 5.1 and 7;
six worker files, exact stage markers, nested runtime hashes, asset count,
missing/oversized data, secret exclusion and bounded cleanup paths checked.
The report is diagnostic evidence, not a successful installation or media verdict.
