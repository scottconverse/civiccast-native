# Dependency advisory checks

The `ci-security-scan` workflow checks the development dependency environment
and the native application's declared requirements separately. Neither check
proves that an installer contains those packages or that the station runs them.

The development job installs the frozen lock without the local first-party
project. It collects `pip list` from that environment independently of the
scanner, then runs both the scanner and checker with `uv run --no-sync`.
Bandit remains a separate check of first-party source.

`scripts/check_pip_audit_allowlist.py` requires the scanner report, its original
exit status, and exactly one independent dependency list:

- `--inventory <pip-list.json>` for an installed environment; or
- `--requirements requirements-native-app.txt` for the native exact-pin list.

Also pass `--scanner-exit-code <status>`. Do not construct the expected inventory
from the audit report: that would let an incomplete report validate itself.
See `.github/workflows/ci-security-scan.yml` for executable command sequences.
The native parser accepts exact, unmarked version pins and SHA-256 hash lines;
it rejects unresolved ranges, markers, extras, URLs and included files.

The checker exits:

- **0:** the complete name/version list matches, scanner status agrees, and
  findings are absent or covered by current, reviewed exceptions.
- **1:** the complete report contains an unapproved finding.
- **2:** verification is incomplete or invalid, including missing dependencies,
  duplicate identities, scanner errors, malformed reports or expired exceptions.

Exceptions in `pip-audit-allowlist.json` require a package/advisory identity,
reason, review date and review deadline. Recheck source reachability when callers
or dependencies change; a dated exception is not a general safety guarantee.
Upgrade when a fix is available. Native advisory scans do not verify downloaded
wheel bytes, license provenance, installation or runtime compatibility.
