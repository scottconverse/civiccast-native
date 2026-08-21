# Execution spec — native installer + lifecycle proofs (`slice:ws5-installer`)

**Decision state (v4): OWNER-APPROVED 2026-07-29.** Scott approved (a) the
installer format — signed NSIS `.exe` via the Tauri v2 bundler — and (b) this
spec as the audit baseline for the installer slice (the `spec:v2` decisions as
amended by `WS5-INSTALLER-SLICE-CHARTER.md`, recorded here as v3). The v4
amendment makes Windows Sandbox the primary full-matrix cleanroom, assigns a
persistent VM only to proof gaps Sandbox cannot faithfully establish, and
places external hardware validation at LPM beta. Approval is
recorded in the charter's report thread ("`.exe` it is" + "Go"). D1–D7 and the
lifecycle proof matrix remain otherwise unchanged in substance from v2 — v3 folds in
the charter's two locked calls (format + payload provenance) and the approval
state; v4 changes venue allocation but drops no proof row. Any future
narrowing of a D-decision or a matrix row still requires an owner-approved
amendment (the auditor has ruled once that a coder cannot narrow a spec
silently).

Three items remain OPEN and are **pre-beta-tag**, not installer-slice blockers
(carried over from the ws5-packaging-closure slice): the dual-license elections
for librtmp / cairo / D-Bus + FreeType; the prune-or-keep call on two dead
D-Bus typelibs; and the VC++ Redistributable labelling acknowledgment. None of
these gate the installer build; all must close before the beta tag.

Charter §7 installer obligations. Produces the beta artifact.

## Locked format + payload (charter §2, owner-approved 2026-07-24)

- **Format = signed NSIS `.exe` via the Tauri v2 bundler.** The 2026-07-22
  owner note "signed MSI" was shorthand for "signed via the proven Azure
  pipeline"; the proven pipeline (`.github/workflows/release-artifacts.yml`,
  `azure/artifact-signing-action@v2`) signs an NSIS `.exe`, the existing
  product is NSIS, and this spec's hook design is NSIS. This supersedes any MSI
  wording anywhere in the program docs for the native product. If the owner
  later elects MSI, that overrides and this line is reopened.
- **Payload = the audited runtime closure, rebuilt reproducibly at build time
  and verified before embedding.** The closure the ws5-packaging-closure slice
  produced and merged (round-9 `AUDIT_PASS` @ `ebc42be7`) is **220 manifest
  files / 75,097,266 bytes**, with trust artifacts `runtime-manifest.json`
  (`99143f7f…`) → `SHA256SUMS` (`dab7bf03…`) → `LICENSE-BOM.md` (`8f235f95…`)
  written after the manifest (223 files on disk = 220 + 3 trust artifacts). At
  installer-build time the payload is rebuilt from the hash-pinned wheel set
  (`requirements-native-runtime.txt`, `uv pip compile … --generate-hashes`) and
  **verified against `runtime-manifest.json` before being embedded** — a
  mismatch fails the build loud. This is the build-time half of D2; the
  install-time half (below) chains verification to the installer's Authenticode
  signature.

## Decisions (v4)

- **D1. Two PRODUCTS, one codebase (SDR-004).** Native is a distinct Windows
  product, not a mode flag inside the WSL product: its own bundle identifier
  (`org.civiccast.native`), product name ("CivicCast (Native)"), executable
  and shortcut names, install root, uninstall registration, update channel,
  and **its own NSIS hook set containing ZERO WSL-touching steps** (the
  current hooks delete the WSL autostart, terminate and unregister the
  distro — those stay exclusively in the WSL product's hooks). Native
  installs **perMachine** with elevation (it writes Program Files, ProgramData
  machine state, and registers a LocalSystem service); the WSL product stays
  currentUser as today. Both appear as independent Apps & Features entries;
  either installs, repairs, or uninstalls in either order without touching
  the other's files, registry, or runtime. **Selector handling on uninstall
  (round-2 correction — reporting an orphan is not an operable station):
  uninstalling the ACTIVE product is BLOCKED until ownership is transferred**
  — the uninstaller detects `ActiveRuntime` pointing at itself while the
  other product is installed, and requires the operator to run the
  cutover/rollback transfer (offered as an explicitly acknowledged
  transaction from the uninstall UI) before removal proceeds. Uninstalling
  the inactive product never touches the selector. If the active product is
  the ONLY one installed, uninstall clears the selector (nothing remains to
  orphan). Cross-uninstall proofs assert the REMAINING product is OPERABLE
  (starts, transmits) — not merely byte-unchanged.
- **D2. Payload trust:** the payload's `SHA256SUMS` is covered by the SIGNED
  installer itself (inside the signed bundle), so install-time verification
  chains to Authenticode, not to a checksum file an attacker could swap
  beside the payload (SDR-008 note). Verify before laying files; corrupt ⇒
  loud failure. **Build-time provenance (charter §2.2):** before it is
  embedded, the payload is rebuilt reproducibly from
  `requirements-native-runtime.txt` and verified byte-for-byte against
  `runtime-manifest.json` (220 files / 75,097,266 bytes), so the bytes the
  signature later covers are exactly the audited closure.
- **D3. Upgrade with a REAL recovery point (SDR-005; ordering corrected in
  round 2 — freeze BEFORE the backup, hold it through commit):** sequence:
  (1) journal phase-0 AND **acquire the shared D7a maintenance interlock**
  (spec-dual-runtime-guard) — every native start path honors it, so a
  concurrent operator/SCM start during the upgrade window is REFUSED at the
  start path, not merely absent; (2) **stop/drain all writers** (service
  stop; Postgres stays up solely for the upgrade connection) and VERIFY
  quiescence (WS2 pre/post snapshot equality); (3) **pre-upgrade database backup via the WS2
  machinery** (dump + globals + quiescence-bound manifest), VERIFIED
  (artifact hash + restore-drill spot check) before proceeding — the
  recovery point now precedes every mutation and no discarded-writes window
  exists; (4) lay `app\<new>\`, flip `current` junction;
  (5) `alembic upgrade head`; (6) start service in **maintenance/read-only
  health mode** (the supervisor, seeing the interlock, starts pg/NATS/
  control-plane read paths but refuses mutating endpoints and starts no
  workers — this is how "the freeze holds" survives step 6's health gate);
  (7) health green ⇒ release the interlock (commit) and resume normal
  operation; journal complete. Failure at/after (5):
  flip junction back AND restore the step-3 backup, so the old binary never
  runs against a newer schema. **Rollback-failure is itself defined:** if
  the restore fails, the installer HALTS with the service stopped (never
  running on a wrong schema), preserves the verified backup + journal, and
  emits an operator recovery document naming exact next steps — an injected
  restore-failure test is a proof-matrix row. The journal binds: old/new
  product versions, pre/post schema revisions, backup manifest hash + blob
  identity, verification result, and rollback outcome; resume is idempotent
  from the journal; power loss at each boundary is a proof row. A release
  whose migration cannot restore-roll-back must declare it; the installer
  refuses auto-upgrade for it (manual path with operator ack).
- **D4. Uninstall contract:** remove service + Program Files + shortcuts;
  PRESERVE ProgramData unless "also delete recordings, database, and
  configuration" is checked with typed confirmation. Exact state inventory
  (files, registry keys, service, firewall rules) is enumerated in the spec's
  implementation and asserted by the proofs — "everything gone" means that
  inventory, bidirectionally.
- **D5. Repair:** re-verify current tree against the signed manifest, re-lay
  corrupted files, re-register service, never touch data.
- **D6. Signing:** Azure Trusted Signing; per the standing owner rule, verify
  the repo's actual secrets/action inputs/build outputs before writing YAML.
  Signing credentials and release publication remain owner actions.
- **D7. Clean-machine venues (SDR-009; owner amendment 2026-07-29):** the FULL
  lifecycle matrix runs in a fresh Windows Sandbox instance with captured
  provenance (host Windows build, launch time, `.wsb` configuration, and
  zero-prior-install assertion). Restart-required flows restart Windows inside
  the running sandbox; closing the sandbox discards the venue. A separately
  provisioned persistent VM runs only rows Sandbox cannot faithfully prove,
  such as a pre-login service boundary when Sandbox automatic login makes the
  timestamps ambiguous, multi-session/multi-version upgrade chains, or
  account/domain/policy isolation. It does not duplicate the full matrix by
  default. The owner's development host is not a cleanroom and must not be
  rebooted for routine lifecycle proof. External hardware/live-peer validation
  stays at LPM beta. Sandbox vGPU is disabled for the mandatory CPU-only
  software matrix.

## Lifecycle proof matrix (every row = evidence artifact)

| Proof | Pass condition |
|---|---|
| Fresh install | Supervisor ready after an in-Sandbox reboot; pre-login service behavior is established from service/event timestamps or rerun in the focused persistent VM when Sandbox automatic login makes that boundary ambiguous |
| Coexistence A | WSL product installed FIRST, then native: two ARP entries; WSL runtime/config untouched (inventory diff); guard blocks double transmission per WS4 |
| Coexistence B | Native FIRST, then WSL product: same assertions, reversed |
| Cross-uninstall (inactive product) | Uninstall the product the selector does NOT point at: survivor's full inventory unchanged; selector untouched; survivor starts and transmits |
| Cross-uninstall (active, survivor present) | Acknowledged ownership TRANSFER (cutover/rollback) required and executed, THEN removal; selector points at survivor; survivor operable (starts + transmits) |
| Cross-uninstall (active, sole product) | Selector CLEARED on removal; machine carries no orphan pointer |
| Cross-uninstall (transfer refused/cancelled) | NOTHING removed; both products intact and operable |
| Upgrade | vN→vN+1: data intact (WS2 snapshot equality), journal complete, health green |
| Failed upgrade (health) | Test hook refuses readiness ⇒ junction back + DB restore, old version healthy |
| Failed upgrade (schema) | **A genuinely incompatible migration fixture** ⇒ restore path proves old binary never touches new schema |
| Power loss | Kill installer at each journal boundary ⇒ resume completes or rolls back cleanly |
| Rollback-restore failure (injected) | Restore made to fail after an incompatible migration ⇒ installer HALTS with service stopped, backup + journal preserved, operator recovery document emitted — never runs old binary on new schema |
| Concurrent start during upgrade | Manual + SCM start attempts mid-window ⇒ refused by the D7a interlock, journaled |
| Repair | Byte-flipped DLL detected via signed manifest, restored, healthy |
| Uninstall default / purge | Per D4 inventory |
| UAC denied / partial service reg / same-version reinstall | Defined, non-destructive outcomes |
| Reboot / logout mid-playout | Unattended resume / uninterrupted |

## Build steps

1. Native product identity + hook set (D1) in the Tauri/NSIS config —
   verified against the CURRENT tauri.conf.json/nsis-hooks.nsh rather than
   assumed (the existing hooks are the SDR-004 hazard). **Layout decision
   (WP-2, 2026-07-24):** the native product is a Tauri v2 **config overlay in
   the same app** — new files `src-tauri/tauri.native.conf.json` and
   `src-tauri/nsis-hooks-native.nsh`, built via
   `tauri build --config src-tauri/tauri.native.conf.json` — not a forked app
   directory. This honors D1's "two products, one codebase" (frontend and Rust
   crate are shared), and it never edits the WSL product's `tauri.conf.json` or
   `nsis-hooks.nsh` (both stay byte-identical). Rationale, the Tauri-v2
   merge-semantics grounding, and the rejected sibling-app-directory
   alternative are recorded in
   `.agent-runs/native-windows/ws5-installer/evidence/wp2-native-identity-decision.md`.
   Because Tauri's `--config` deep-merges the overlay OVER the WSL base, the
   overlay MUST explicitly override every identity field (identifier,
   productName, mainBinaryName, `bundle.windows.nsis.installMode`,
   `bundle.windows.nsis.installerHooks`); the WP-2 disjointness test replicates
   the deep-merge and asserts the EFFECTIVE native config's hook file,
   installMode, identifier, and install identity are all disjoint from the WSL
   product and free of any inherited WSL hook — closing the SDR-004
   inheritance footgun at the test layer.

   *Superseded by two later, unrelated decisions, kept here as the historical
   record of WP-2 itself:* `nsis-hooks-native.nsh` was folded into
   `nsis-hooks-bootstrap.nsh` in the WP2 hook-migration (2026-07-30) and no
   longer exists as a separate file. The WSL product itself — and its
   `tauri.conf.json` `installerHooks`/`nsis-hooks.nsh` — was retired under the
   owner's "no linux" decision (2026-08-19); the base `tauri.conf.json` is
   kept only as the file Tauri's CLI always merges a `--config` overlay on
   top of and no longer declares any `installerHooks` of its own. The
   disjointness test this paragraph describes is now
   `tests/policy/test_native_installer_identity.py`'s positive assertion that
   only the native hook file exists/is wired, not a two-product comparison.
2. Journaled install/upgrade engine with the D3 backup/restore integration.
3. Windows Sandbox automation driver for the full proof matrix, plus focused
   persistent-VM automation for any row Sandbox cannot faithfully establish.
4. Evidence per matrix row, bound to its assigned venue and provenance.

## Halt triggers

- Anything requiring rc-line/WSL-product behavior changes.
- Signing inputs differ from expectation (D6 rule): stop, report actual.
- A migration that cannot satisfy D3's restore contract: owner decision.
