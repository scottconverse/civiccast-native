# Fixture provenance and exclusions

Copied verbatim from a real Windows Sandbox Gate A reference run's
`output\` directory, dated 2026-08-19 (source: the standalone harness at
`C:\Users\scott\Desktop\Code\sandbox-lab\output\`, outside this repository).
Text/JSON files keep their original UTF-8 BOM.

**Excluded on purpose** (not present in this fixture, deliberately):

- `ui-dom-operator.html`, `ui-dom-portal.html`, `ui-health.html`,
  `ui-operator_console.html`, `ui-resident_portal.html`, and their paired
  `.stderr.log` files — raw DOM/HTML dumps. Not needed by any
  `scripts/gate_a_verdict.py` check; the T2 render check reads the byte-ratio
  verdict already written to `T2-RENDER-RESULT.txt`.
- `T3-CREDENTIALS.txt` — a freshly-generated, disposable password for the
  sandbox-only "Sandbox Proof Station" admin account (the sandbox VM and its
  database are torn down at the end of every run; nothing this password
  protects survives past that). Not needed by any check. Excluded as a
  matter of hygiene rather than committing a password-shaped string to a
  public repository for no functional reason.

**NOT excluded, despite the temptation:** `DONE.json` is genuinely absent
from the real source run — not stripped here. See
`scripts/gate_a_verdict.py`'s module docstring ("Known harness quirk") and
`docs/ops/gate-a.md` for why, and what it means for this fixture's own
verdict (FAIL, on the `completion` check alone).
