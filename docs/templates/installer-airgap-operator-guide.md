# Air-Gapped Installer Operator Guide

1. Copy the complete CivicCast air-gapped bundle to the target host.
2. Disconnect the target host from external networks before verification.
3. Confirm the bundle contains `proof.json`, this operator guide, and every model artifact named by the proof manifest.
4. Run `civiccast model import-offline --bundle-dir <bundle> --expected <filename=sha256>` for each artifact listed in the proof manifest.
5. If any file is missing or any hash mismatches, stop and rebuild the bundle from verified bytes.

External provider credentials are not verified by this offline flow. Verify those lanes only through an approved online proof run.
