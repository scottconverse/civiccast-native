# Execution spec - claims-evidence rule (`slice:ws3-claims-evidence`)

**Decision state: Proposed. Consolidated v8 rewrite after auditor design
review rounds 1-7 (SDR-006; audit-control
reviews/2026-07-17-specs-design-review.md). Not owner-approved. The
trust-root pin (D6) is an explicit owner-acceptance item and is
NON-AUTHORIZING until the owner accepts it.**

Charter section 4 / gate 3, alongside ADR-0021. A capability claim in prose
must be machine-bound to evidence; the motivating failure was an overclaim
inside the honesty machinery itself (the DR doc's "Postgres backup/restore is
implemented" while no pg_restore existed).

## D1. Registry + enforced markers

Registry `docs/claims/claims.yaml`. Within a GOVERNED DOC SET (enumerated in
the registry header: README, CAPABILITIES, DR docs, release verification
docs, `civiccast/dr/__init__.py` - extendable), every occurrence of a
strong-claim token (`implemented`, `proven`, `validated`, `executed`,
`verified` - word-bounded, case-insensitive) must carry an adjacent claim
marker (`<!-- claim:ID -->` in markdown; `# claim:ID` in Python docstrings)
referencing a registry entry. Unmarked strong tokens in governed docs = exit
1. Prose that doesn't want the burden gets softened, which is the point.

## D2. Committed side: definitions only, typed input roles

A committed registry can never contain results (run IDs, artifacts, dates) -
committing a result for its own final SHA is an unresolvable fixed point.
Each entry: `{id, claim, where (file+anchor), inputs, controls}`.

`inputs` is a TYPED ROLE MAPPING; the schema enforces every role and each
role's git blob ID (filter-aware `git hash-object --path`, the WS1
machinery) is recorded. Roles, all mandatory:

| Role | Carries |
|---|---|
| `prose` | the `where` file |
| `code` | the claim-defining module(s) |
| `test` | pytest node id + file |
| `verifier` | checker script + registry schema |
| `workflow` | the trusted workflow file |
| `workflow_contract` | `docs/claims/workflow-contract.yaml` (D3) |
| `trust_root` | `docs/claims/trust-root.yaml` (D6) |
| `generator` | evidence generator script |
| `fixtures` | claim-specific fixtures/config, exhaustively listed (enforced by D8's omission mutations + audit review - no schema can infer an omitted dependency) |

Verification at any commit: claim text present at `where`; `code` resolves;
every role's CURRENT blob ID equals the recorded one - any drift invalidates
(exit 1: "re-prove or re-bind"). Missing role = malformed, exit 2.

## D3. Same-run resolution (CI-provable claims)

The verifier runs INSIDE the trusted workflow and consumes its OWN run
context; nothing about a run is ever committed back.

- **Source identity:** the checked-out source head - for `pull_request`
  events `github.event.pull_request.head.sha`, never `GITHUB_SHA` (the
  synthetic merge commit). The verifier asserts its own
  `git rev-parse HEAD` equals that head.
- **Workflow contract** (`docs/claims/workflow-contract.yaml`, created BY
  this slice) has two fields with distinct jobs-completeness roles:
  - `workflow_job_inventory`: EVERY static job ID in the trusted workflow,
    INCLUDING the verifier. Compared exactly against the workflow file's
    parsed job list - an unlisted live job (or listed dead job) is drift.
  - `expected_producers`: a mapping keyed by producer job ID, each value
    naming that producer's exact junit artifact name, metadata artifact
    name, `requires_checkout_attestation: true`, and that producer's OWN `junit_collection_floor` (a global floor can hide an empty-but-successful producer; floors are per producer). The verifier must
    never appear here; the verifier's `needs:` must equal the producer
    keys exactly. (The current workflow has three test-producing jobs -
    `test`, the GStreamer engine job, and the NATS boundary job - with
    differently named or absent junit artifacts; the mapping is what makes
    each one's proof obligations explicit. ws3 lands the workflow changes
    that make every producer emit its junit + meta pair.)
- **Per-producer one-commit identity:** EVERY producer job checks out the
  PR head explicitly (`actions/checkout` with
  `ref: github.event.pull_request.head.sha`) and uploads, beside its junit
  artifact, a `<job>-meta.json` containing its own `git rev-parse HEAD`.
  The verifier asserts every producer's meta SHA == its own checkout ==
  the binding SHA.
- **Fail-closed execution (GitHub `needs` semantics):** a job that `needs`
  a skipped/failed job is itself skipped - which would let claims silently
  evade verification. The verifier job therefore runs with `if: always()`
  and EXPLICITLY evaluates every producer's result: any producer not
  `success` = verifier FAILS (red, visibly), never skips.
- **Checks performed:** trusted workflow identity; job inventory equality;
  every producer success + junit + meta present and SHA-matched; junit
  collection floor met (`junit_collection_floor` in the contract); the
  claim's test node PASSED (skipped/xfail = fail).
- Output goes to the run summary and, for gate events, to audit-control
  keyed by source SHA. Offline/no-token = exit 2 (cannot-check), never a
  silent pass.

## D4. Negative controls

Committed side holds only definitions (`command`, `expected_red_when`,
`ci_safe`). `ci_safe: true` controls RUN in the verifier job each time
(same-run provenance). Non-CI controls resolve per D5. A claim exits 0 only
at the confidence class its CURRENT (blob-matched) controls support; a
missing, stale, or unresolvable required control FAILS the claim - no
informational "degraded" beside a green result.

## D5. External-evidence resolution (non-CI claims: hardware, session-0, clean-machine)

Evidence records live OUTSIDE this repo in the audit-control repository -
the same trust root the program's verdicts stand on.

- **Canonical, create-only records:** exactly one record per (source SHA,
  claim id, control id) at
  `evidence/<source-sha-40hex>/<claim-id>/<control-id>.json` on
  audit-control `main`. Records are CREATE-ONLY: any change to an existing
  record path is itself a violation the verifier fails on (it validates
  the exact selected commit, not merely an introducing commit - a later
  modification cannot inherit the original's authentication).
- **Authority record (the decisive edge, round-7 closure):** a claim above
  code-review confidence requires a CANONICAL AUTHORITY RECORD - an
  extension of the existing verdict format at
  `authority/<claim-id>/<control-id>/<source-sha>.md (one record per control - a claim with multiple controls gets one authority record each; path collisions are impossible by construction)` in audit-control - whose
  STRUCTURED FIELDS bind all five identities:
  `source_sha`, `claim_id`, `control_id`, `evidence_commit`,
  `evidence_blob` - using authority-record-v1's exact field syntax
  (`**Claim:**`, `**Control:**`, `**Source SHA:**`, `**Evidence commit:**`,
  `**Evidence blob:**`, `**Authority format:**`, `**Assessment:**` - the
  same bold-label line syntax verdict records use; a record missing any
  field or carrying an unparseable value is malformed). Resolution and
  authentication, in order: (1) locate the record at its canonical path on
  audit-control `main`; (2) authenticate the commit that FIRST INTRODUCED
  that path (first-parent history walk) - signature against the pinned
  signers, role = auditor or owner; (3) verify create-only BY HISTORY, not
  by bytes (round-12 correction: byte comparison of introduction vs HEAD
  accepts a forbidden A->B->A modification history): EXACTLY ONE commit in
  `main`'s first-parent history touches the path - a second touching
  commit is a violation regardless of the final bytes; (4) verify BOTH bindings per
  authority-record-v1: path segments equal body fields (canonical-path
  binding) AND the referenced `evidence_blob` is byte-identical to the
  evidence record actually fetched, where the evidence record's own
  canonical path is derived from the SAME (source_sha, claim_id,
  control_id) triple - one triple, two canonical paths, no independent
  path inputs anywhere; (5) verify the evidence record's introducing
  commit is not NEWER than the authority record's introducing commit
  (no retroactive authority: an authority record cannot pre-certify
  evidence that did not exist when it was signed). An auditor-signed
  review referencing DIFFERENT evidence fails at (4).
- **Record body:** full charter contract - command, environment/tool
  versions, timestamps, exit status, output hashes, source SHA, input
  blob IDs, origin machine. Coder-authored evidence alone never certifies
  a coder claim (no-self-certification, extended to evidence records).
- Offline/no-token = exit 2, never a silent pass. Attestation may be
  layered per the charter for integrity/provenance; raw observations
  retained.

## D6. Trust root - pinned in the product repo, owner-accepted

`docs/claims/trust-root.yaml` (created BY this slice; a `trust_root` typed
input) pins: the audit-control repository's canonical URL, the expected
blob hash of `keys/allowed_signers`, the ROLE each key carries
(`codex-auditor` = auditor, `claude-coder` = coder, owner keys = owner),
AND the AUTHORITY-FORMAT governance binding (round-9 closure): the format
identifier (`authority-record-v1`), the audit-control commit that ratified
it, and the exact blob hash of the ratified `AUTHORITY_RECORDS.md`
(auditor-ratified at `05f78d89787990a2355fa319a520ea6c821993fd`, blob `d6944d08d5870a60df5ae912aa8cfc62c2f4e047`). The verifier validates authority records against THOSE exact
governance bytes - a drifted/superseded format doc means cannot-check
until the pin is updated through this same owner-gated file. Canonical
path grammar, enforced as a regex:
`^authority/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}/[0-9a-f]{40}\.md$ PLUS the ratified doc's prohibition list applied AFTER the regex (the regex alone admits '..' inside a slug; the doc bans it): reject any slug containing '..', and reject slash, backslash, percent-escape, uppercase - grammar = regex AND prohibitions, exactly as authority-record-v1 states them`.
The verifier validates repository identity (normalized origin URL - the
completion hook's existing validation) and the fetched allowed_signers
blob hash before trusting any signature.

**Owner governance (round-7):** the initial key set, role mapping, and the
pin/rotation procedure are the OWNER's decision - entered in
specs/README.md's owner-acceptance register. Until Scott accepts the exact
initial pin, the verifier treats the trust root as NON-AUTHORIZING:
external-evidence claims resolve to cannot-check, not to pass.

## D7. CI wiring

Verifier job: `needs:` = exactly the `expected_producers` keys;
`if: always()` with explicit per-producer result evaluation (D3
fail-closed rule); downloads each producer's junit + meta artifacts; runs
D4 ci-safe controls.

## D8. The verifier's own falsifications (gate-3 exit criterion)

Committed pytest fixtures proving the verifier rejects, each expected-red:

1. Seeded false "implemented" claim (the charter's own exit criterion).
2. Wrong-SHA junit; junit-meta from ANOTHER run; missing or malformed
   junit-meta.
3. Mutated input file (blob drift) for EACH typed role in turn - prose,
   code, test, verifier, schema, workflow, workflow_contract, trust_root,
   generator, fixture (one mutation per role).
4. Skipped test node presented as proof; test mutated after its junit run.
5. Unmarked strong token in a governed doc; stale `where` anchor;
   duplicate claim ID; malformed registry.
6. Synthetic merge SHA (`GITHUB_SHA`) substituted for head SHA.
7. Job-inventory drift (live job unlisted; listed job dead); verifier
   listed in `expected_producers`; `needs:` diverging from producer keys.
8. Producer skipped/failed while the verifier still runs = verifier RED
   (the always() fail-closed proof); one producer missing its junit or
   meta artifact.
9. Evidence record at non-canonical path; duplicated; uncommitted;
   path/body SHA disagreement; record MODIFIED after creation (create-only
   violation); wrong evidence blob behind a valid path.
10. Authority record signed by a key absent from the pinned signers;
    signed by the CODER key (role failure); correctly auditor-signed but
    referencing DIFFERENT evidence (blob-binding failure).
11. Tampered trust-root pin (allowed_signers blob-hash mismatch) = hard
    fail; unaccepted trust root = external claims cannot-check, never pass.
12. Self-reference probe: an entry claiming a run for the commit
    containing the entry itself = malformed (committed run metadata is
    banned by D2).
13. Round-8 additions: a successful producer whose junit collects ZERO
    tests = red against ITS per-producer floor (the empty-but-green
    producer case a global floor hides); a producer collecting FEWER than
    its floor while others exceed theirs = red (positive-below-floor,
    round-9 Minor); two controls of one claim resolving to the SAME
    authority path = malformed (per-control paths make collisions
    structurally impossible - the control proves the structure is
    enforced, not assumed); an authority record whose format does not
    match the ratified governance definition = rejected.
15. Round-11/12 controls: introducing-commit authentication proven IN
    ISOLATION (round-12 correction - the naive form of this control is
    satisfied by create-only alone and proves nothing about the
    authenticator): the mutation fixture DISABLES the create-only check,
    then presents a path introduced by an UNSIGNED commit and later
    touched by a correctly-signed auditor commit - the verifier must
    STILL reject, which only introducing-commit authentication can do; an
    A->B->A history (record modified and reverted, final bytes identical
    to introduction) = rejected by the history-based create-only check
    (two touching commits), which byte comparison would wrongly accept;
    a retroactive authority record (evidence introduced AFTER the
    authority record's signing commit) = rejected; a trust-root pin
    carrying an abbreviated (non-40-hex) commit or malformed blob hash =
    malformed, exit 2; a record with a missing or unparseable structured
    field = malformed.
14. Round-9/10 governance-binding controls: an authority record declaring
    a format identifier other than the pinned `authority-record-v1` =
    rejected; a fetched `AUTHORITY_RECORDS.md` whose blob hash differs
    from the trust-root pin = cannot-check (never pass); a record
    validated against a DIFFERENT audit-control commit's copy of the
    governance doc than the pinned ratifying commit = cannot-check; path
    grammar boundary set - a 128-char slug and slugs containing `.`/`_`
    are VALID (grammar-conformance positives), while a 129-char slug,
    `..`, uppercase, slash/backslash, or percent-escape = rejected.

## D9. First registration scope

The program's own claims (WS2 drill, release-truth checker, decision gate,
session-0) + every strong token currently in `civiccast/dr/__init__.py` and
the DR verification doc. Not a repo-wide sweep; the RULE ships first.

## Acceptance criteria

- AC1 Verifier green on registered claims at head (same-run mode), with the
  external-evidence claims resolving once the owner accepts the trust root.
- AC2 Every D8 falsification red, each as its own test.
- AC3 Editing any bound input without re-binding = exit 1 naming the blob
  drift.
- AC4 Removing a marker (or adding an unmarked "proven") in a governed doc
  = exit 1.

## Halt triggers

- A claim that can only pass by weakening: list as an open overclaim for
  the owner, never weaken silently.
- Any need to trust a signature whose key/role is not in the owner-accepted
  pin: cannot-check, surface to owner.
