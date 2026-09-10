# Provisioning-journal fixtures

`provision-journal-2026-08-15-beta1-nats.json` -- the on-disk shape of a
`C:\ProgramData\CivicCast\provision\provision-journal.json` written by the
August 2026 (beta.1/beta.2-era) installer: `schema_version: 1`,
`phase: complete`, and five `context.nats_*` keys plus two `nats_*` history
phases that `85ffe6c0` ("stop provisioning a NATS store or config") removed
from the model without a migration. Loading it through the beta.5 model
halted an upgrade with "5 validation errors for ProvisionJournal ...
Extra inputs are not permitted"; beta.5.1 tolerates it
(`tests/native/test_provision_journal.py`, `tests/native/test_provision_cli.py`).

The Windows paths inside are the journal's real content (ProgramData /
Program Files defaults) and are deliberately kept verbatim. The password is
the product's own redaction marker; no credential is present.
