# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Claims-evidence verifier (spec-claims-evidence-rule.md D1-D4, D8).

A capability claim in governed prose must be machine-bound to evidence. This
script implements the registry/marker rule (D1), the typed-input-role
blob-drift check (D2), same-run CI resolution (D3), and negative controls
(D4).

Usage (run inside the trusted CI workflow):
    python scripts/policy/check_claims_evidence.py --mode same-run \
        --registry docs/claims/claims.yaml \
        --workflow-contract docs/claims/workflow-contract.yaml \
        --workflow-file .github/workflows/ci-test.yml \
        --artifacts-dir claims-artifacts \
        --producer-results producer-results.json \
        --ci-safe-controls

Exit 0 = pass. Exit 1 = a violation (drift, a claim failed its checks, a
rejected control). Exit 2 = cannot-check or malformed (missing role, bad
registry shape, offline/no-token) -- never inferred as a pass.

Removed 2026-08-07 (owner decision): D5 (external-evidence resolution
against a separate, owner/auditor-signed "civiccast-audit-control"
repository) and D6 (that repository's trust-root pin validation), plus the
``--mode external-evidence`` CLI mode, ``run_external_evidence_mode``,
``resolve_external_evidence``, ``PendingOwnerAcceptanceError``, the D5
evidence-record body schema, and every other D5/D6-only helper. This
mechanism was invented by an AI coder on 2026-07-17 (commit c8c5eafa,
hardened further the same day in e87b4724 and dd34eb37) during a period
when Codex acted as auditor -- the owner never asked for an
owner/auditor-signed authority-record requirement gating releases, and by
2026-08-07 it was blocking a beta release over claims whose evidence had
already been re-proved and passed. See CHANGELOG.md for the full record.

D2's blob-drift binding is explicitly UNCHANGED and UNWEAKENED by this
removal: ``blob_drift_violations`` still runs, unconditionally, against
every registered claim's every input role -- including the two claims still
recorded as ``resolution: external_evidence`` in docs/claims/claims.yaml
(their ``code``/``prose``/``test``/etc. bindings still drift-check exactly
as before; only the separate owned-repo authority-record requirement that
used to additionally gate them is gone). That is the half of this
mechanism the owner explicitly kept, precisely because it has caught real
drift.

Round-2 audit additions (CC-WS3-001, CC-WS3-003, CC-WS3-004) -- still in
force:

* A capability-token lexical tripwire (CC-WS3-001): if a claim's own text
  uses "backup"/"restore"/"dump", its bound test's path/node id must
  mention that same word, or it is flagged as a possible overclaim
  (heuristic, not proof).
* Identity tying (CC-WS3-003): ``inputs.prose.path`` must equal
  ``where.file``, and the pytest node id's file component must equal
  ``inputs.test.path`` -- malformed (exit 2) otherwise.
* Exact artifact routing (CC-WS3-004): producer artifacts resolve ONLY at
  the contract's exact ``<artifact>/<file>`` path (no repo-wide fallback);
  producer meta must carry a matching ``job_id`` and, when
  ``--run-attempt``/``GITHUB_RUN_ATTEMPT`` is known, a matching
  ``run_attempt``.
* One-or-more ``code`` modules (CC-WS3-005): the ``code`` input role
  accepts either a single role-file mapping or a non-empty list of them
  (mirroring ``verifier``/``fixtures``), so a claim about evidence produced
  by several cooperating modules can bind all of them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

STRONG_TOKENS_DEFAULT: tuple[str, ...] = (
    "implemented",
    "proven",
    "validated",
    "executed",
    "verified",
)

# CC-WS3-001 (round-2 audit, Critical): a small, deliberately narrow lexical
# tripwire. If a claim's own `claim` text uses one of these capability words,
# the bound `test` role's path/node id must ALSO mention that same word -
# otherwise the claim is asserting a capability (e.g. "restore") that its
# bound test does not exercise by name (e.g. a test file named only
# "backup"). This is exactly the ws2-postgres-restore-drill defect: the
# claim said "restore" while the bound test only ran pg_dump. This is a
# HEURISTIC, not a proof - it understands words, not code, and can both
# miss real overclaims (a test file coincidentally named "restore_smoke"
# that doesn't actually restore anything) and flag honest claims that
# happen to share vocabulary. It exists to force a human/auditor look at
# the mismatch, not to replace claim review.
CAPABILITY_TOKENS: tuple[str, ...] = ("backup", "restore", "dump")

# CC-WS3-008 (round-5 audit, Major): per-BLOCK capability-coverage lexicon
# for the D1 governed-block scan (scan_marker_violations), reusing
# CAPABILITY_TOKENS above as its base (the round-1 entry-text tripwire's
# lexicon) and extending it with the two additional words D9's Postgres
# restore finding requires at minimum ("capture", "recovery") that
# CAPABILITY_TOKENS does not carry. Kept as its OWN constant, not a mutation
# of CAPABILITY_TOKENS: claim_capability_token_violations' entry-text
# tripwire is a distinct, narrower check (round-1) — widening its lexicon
# too would newly flag existing entries whose claim text legitimately says
# "recovery" in prose unrelated to any bound-test-name mismatch, which is
# not this finding's defect.
BLOCK_CAPABILITY_TOKENS: tuple[str, ...] = tuple(dict.fromkeys((*CAPABILITY_TOKENS, "capture", "recovery")))

CLAIM_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
BLOB_RE = re.compile(r"^[0-9a-f]{40}$")
MD_MARKER_RE = re.compile(r"<!--\s*claim:([a-z0-9-]+)\s*-->")
PY_MARKER_RE = re.compile(r"#\s*claim:([a-z0-9-]+)")
SLUG_PROHIBITED = ("..", "/", "\\", "%")
SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

MANDATORY_ROLES: tuple[str, ...] = (
    "prose",
    "code",
    "test",
    "verifier",
    "workflow",
    "workflow_contract",
    "trust_root",
    "generator",
    "fixtures",
)

# D2: "verifier | checker script + registry schema" is one role that carries
# TWO files. "fixtures" is explicitly plural/exhaustive. Both are ALWAYS
# lists of RoleFile.
LIST_ROLES: frozenset[str] = frozenset({"verifier", "fixtures"})

# CC-WS3-005 (Major, round-3 audit): "code" accepts EITHER a single RoleFile
# mapping (the common case: one module) OR a non-empty list of them (a
# claim about evidence produced by several cooperating modules, e.g. a
# decision-gate spike that exercised worker.py + engine.py + graph.py
# together). Unlike LIST_ROLES, the YAML shape decides which — a bare
# mapping stays a single RoleFile, a YAML sequence becomes a list.
FLEXIBLE_LIST_ROLES: frozenset[str] = frozenset({"code"})

# D2/D8 group 12 (self-reference probe): the committed side holds only
# definitions — a run ID, date, or commit for the entry's OWN final SHA is an
# unresolvable fixed point and is banned outright.
FORBIDDEN_ENTRY_FIELDS: frozenset[str] = frozenset(
    {"run_id", "run_date", "executed_at", "result", "commit_sha", "source_sha", "run_attempt"}
)


class MalformedRegistryError(Exception):
    """The registry, schema, contract, or trust root fails structural validation.

    Distinct from a ViolationError: this means the checker cannot reliably
    evaluate claims at all (bad YAML shape, missing mandatory role, unparsable
    grammar) — exit 2, never a silent pass or an ordinary drift finding.
    """


class CannotCheckError(Exception):
    """A check cannot be completed (offline, unaccepted trust root, ambiguous
    signature, missing evidence). Exit 2 — never inferred as a pass."""


class ViolationError(Exception):
    """A check completed and found the claim/control/pin invalid. Exit 1."""


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def git_hash_object(repo_root: Path, rel_path: str) -> str:
    """Filter-aware blob ID: `git hash-object --path <p> <p>` (the WS1 machinery)."""
    abs_path = repo_root / rel_path
    proc = run_git(["hash-object", "--path", rel_path, str(abs_path)], cwd=repo_root)
    return proc.stdout.strip()


def git_rev_parse(cwd: Path, ref: str) -> str:
    proc = run_git(["rev-parse", ref], cwd=cwd)
    return proc.stdout.strip()


def git_show(cwd: Path, ref: str, path: str) -> str | None:
    proc = run_git(["show", f"{ref}:{path}"], cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_blob_at(cwd: Path, ref: str, path: str) -> str | None:
    proc = run_git(["rev-parse", f"{ref}:{path}"], cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def git_first_parent_touching(cwd: Path, branch: str, path: str) -> list[str]:
    """Commits in `branch`'s first-parent history that touch `path`, oldest first."""
    proc = run_git(
        ["log", "--first-parent", "--reverse", "--format=%H", branch, "--", path],
        cwd=cwd,
    )
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_paths_under(cwd: Path, ref: str, directory: str) -> list[str]:
    """Tracked paths below ``directory`` in ``ref`` (never working-tree files)."""
    proc = run_git(["ls-tree", "-r", "--name-only", ref, "--", directory], cwd=cwd)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    proc = run_git(["merge-base", "--is-ancestor", ancestor, descendant], cwd=cwd, check=False)
    return proc.returncode == 0


def git_remote_url(cwd: Path, remote: str = "origin") -> str | None:
    proc = run_git(["remote", "get-url", remote], cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def normalize_repo_url(url: str) -> str:
    normalized = url.strip().lower()
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    normalized = normalized.rstrip("/")
    return re.sub(r"^git@github\.com:", "https://github.com/", normalized)


# ---------------------------------------------------------------------------
# Registry data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleFile:
    path: str
    blob: str
    node_id: str | None = None


@dataclass(frozen=True)
class Control:
    id: str
    command: str
    expected_red_when: str
    ci_safe: bool


@dataclass(frozen=True)
class ClaimEntry:
    id: str
    claim: str
    where_file: str
    where_anchor: str
    resolution: str
    inputs: dict[str, RoleFile | list[RoleFile]]
    controls: list[Control]

    def role_files(self) -> list[tuple[str, RoleFile]]:
        """Flatten inputs into (role_label, RoleFile) pairs, expanding fixtures."""
        out: list[tuple[str, RoleFile]] = []
        for role, value in self.inputs.items():
            if isinstance(value, list):
                for index, item in enumerate(value):
                    out.append((f"{role}[{index}]", item))
            else:
                out.append((role, value))
        return out


@dataclass(frozen=True)
class GovernedDoc:
    path: str
    doc_format: str
    enforced: bool


@dataclass(frozen=True)
class Registry:
    schema_version: int
    governed_doc_set: list[GovernedDoc]
    strong_claim_tokens: tuple[str, ...]
    entries: list[ClaimEntry]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MalformedRegistryError(message)


# CC-WS3-007 fold (round-5 audit, Minor): docs/claims/claims-schema.json has
# always declared additionalProperties:false for roleFile/testRole/control/
# claimEntry (and claimEntry.where) — the parsers below silently accepted
# stray keys the schema forbids. This shared helper makes every parser
# strict, matching the schema (house extra="forbid" style): an unexpected
# key is malformed (exit 2), never silently ignored.
def _reject_unknown_keys(value: dict[str, Any], allowed: frozenset[str], context: str) -> None:
    unknown = sorted(set(value) - allowed)
    _require(
        not unknown,
        f"{context}: unexpected key(s) {unknown} not permitted here "
        "(schema declares additionalProperties: false)",
    )


_ROLE_FILE_KEYS: frozenset[str] = frozenset({"path", "blob"})
_TEST_ROLE_FILE_KEYS: frozenset[str] = frozenset({"path", "blob", "node_id"})
_CONTROL_KEYS: frozenset[str] = frozenset({"id", "command", "expected_red_when", "ci_safe"})
_ENTRY_KEYS: frozenset[str] = frozenset({"id", "claim", "where", "resolution", "inputs", "controls"})
_WHERE_KEYS: frozenset[str] = frozenset({"file", "anchor"})
# CC-WS3-007 residue (round-6 fold): claims-schema.json's top-level object
# and its governed_doc_set item def are ALSO additionalProperties: false --
# load_registry parsed both shapes without ever calling _reject_unknown_keys
# on them, the last two shapes the round-5 parity pass missed.
_REGISTRY_ROOT_KEYS: frozenset[str] = frozenset(
    {"schema_version", "governed_doc_set", "strong_claim_tokens", "entries"}
)
_GOVERNED_DOC_KEYS: frozenset[str] = frozenset({"path", "format", "enforced"})


def _parse_role_file(value: Any, context: str, *, allow_node_id: bool = False) -> RoleFile:
    _require(isinstance(value, dict), f"{context}: must be a mapping")
    # CC-WS3-007 fold: node_id is a testRole-only property in the schema —
    # every other role uses the plain roleFile def, which has no node_id
    # property at all.
    _reject_unknown_keys(value, _TEST_ROLE_FILE_KEYS if allow_node_id else _ROLE_FILE_KEYS, context)
    path = value.get("path")
    blob = value.get("blob")
    _require(isinstance(path, str) and bool(path), f"{context}: 'path' must be a non-empty string")
    _require(isinstance(blob, str) and bool(BLOB_RE.match(blob)), f"{context}: 'blob' must be a 40-hex git blob ID")
    node_id = value.get("node_id")
    if node_id is not None:
        _require(isinstance(node_id, str) and bool(node_id), f"{context}: 'node_id' must be a non-empty string")
    return RoleFile(path=path, blob=blob, node_id=node_id)


def _parse_control(value: Any, context: str) -> Control:
    _require(isinstance(value, dict), f"{context}: control must be a mapping")
    _reject_unknown_keys(value, _CONTROL_KEYS, context)
    control_id = value.get("id")
    command = value.get("command")
    expected_red_when = value.get("expected_red_when")
    ci_safe = value.get("ci_safe")
    _require(isinstance(control_id, str) and bool(CLAIM_ID_RE.match(control_id)), f"{context}: control 'id' fails slug grammar")
    _require(isinstance(command, str) and bool(command), f"{context}: control 'command' must be a non-empty string")
    _require(
        isinstance(expected_red_when, str) and bool(expected_red_when),
        f"{context}: control 'expected_red_when' must be a non-empty string",
    )
    _require(isinstance(ci_safe, bool), f"{context}: control 'ci_safe' must be a boolean")
    return Control(id=control_id, command=command, expected_red_when=expected_red_when, ci_safe=ci_safe)


def _parse_entry(value: Any) -> ClaimEntry:
    _require(isinstance(value, dict), "entry must be a mapping")
    claim_id = value.get("id")
    _require(isinstance(claim_id, str) and bool(CLAIM_ID_RE.match(claim_id)), f"entry id {claim_id!r} fails slug grammar")
    present_forbidden = sorted(FORBIDDEN_ENTRY_FIELDS & set(value.keys()))
    _require(
        not present_forbidden,
        f"{claim_id}: entry carries banned result/run field(s) {present_forbidden} — the committed "
        "side holds only definitions (self-reference probe, D2)",
    )
    # CC-WS3-007 fold: checked AFTER the forbidden-field probe above so a
    # banned run/result field still raises ITS specific message, not a
    # generic "unexpected key" one — genuinely unknown keys (neither a known
    # entry field nor a banned one) are malformed here.
    _reject_unknown_keys(value, _ENTRY_KEYS, claim_id)
    claim_text = value.get("claim")
    _require(isinstance(claim_text, str) and bool(claim_text), f"{claim_id}: 'claim' must be a non-empty string")
    where = value.get("where")
    _require(isinstance(where, dict), f"{claim_id}: 'where' must be a mapping")
    _reject_unknown_keys(where, _WHERE_KEYS, f"{claim_id}.where")
    where_file = where.get("file")
    where_anchor = where.get("anchor")
    _require(isinstance(where_file, str) and bool(where_file), f"{claim_id}: where.file must be a non-empty string")
    _require(isinstance(where_anchor, str) and bool(where_anchor), f"{claim_id}: where.anchor must be a non-empty string")
    resolution = value.get("resolution")
    _require(resolution in ("same_run", "external_evidence"), f"{claim_id}: 'resolution' must be same_run or external_evidence")

    inputs_raw = value.get("inputs")
    _require(isinstance(inputs_raw, dict), f"{claim_id}: 'inputs' must be a mapping")
    missing_roles = [role for role in MANDATORY_ROLES if role not in inputs_raw]
    _require(not missing_roles, f"{claim_id}: missing mandatory input role(s): {missing_roles}")
    extra_roles = [role for role in inputs_raw if role not in MANDATORY_ROLES]
    _require(not extra_roles, f"{claim_id}: unknown input role(s): {extra_roles}")

    inputs: dict[str, RoleFile | list[RoleFile]] = {}
    for role in MANDATORY_ROLES:
        raw = inputs_raw[role]
        # CC-WS3-005: "code" is list-shaped ONLY when the registry actually
        # wrote it as a YAML sequence; a bare mapping stays a single
        # RoleFile (backward compatible with every existing single-module
        # claim). "verifier"/"fixtures" are unconditionally list-shaped.
        as_list = role in LIST_ROLES or (role in FLEXIBLE_LIST_ROLES and isinstance(raw, list))
        # CC-WS3-007 fold: node_id is only a valid key on the `test` role
        # (testRole in the schema); every other role uses the plain roleFile
        # def, which has no node_id property at all.
        allow_node_id = role == "test"
        if as_list:
            _require(isinstance(raw, list) and len(raw) >= 1, f"{claim_id}: inputs.{role} must be a non-empty list")
            inputs[role] = [
                _parse_role_file(item, f"{claim_id}.inputs.{role}[{i}]", allow_node_id=allow_node_id)
                for i, item in enumerate(raw)
            ]
        else:
            role_file = _parse_role_file(raw, f"{claim_id}.inputs.{role}", allow_node_id=allow_node_id)
            if role == "test":
                _require(bool(role_file.node_id), f"{claim_id}: inputs.test must carry a pytest node_id")
            inputs[role] = role_file

    # CC-WS3-003 (Major, round-2 audit): identity tying. The `where` file is
    # the SAME file as inputs.prose (the marker/claim text and the pinned,
    # blob-checked prose role must never point at two different files - a
    # claim marked in one file could otherwise be "proven" by a completely
    # unrelated prose blob). Role-path ALIASING (the same file bound under
    # two DIFFERENT roles, e.g. a single module serving as both `prose` and
    # `code`) is explicitly fine where the spec requires it; this check only
    # constrains prose/where, which must never diverge.
    prose_role = inputs["prose"]
    assert isinstance(prose_role, RoleFile)
    _require(
        prose_role.path == where_file,
        f"{claim_id}: inputs.prose.path {prose_role.path!r} != where.file {where_file!r} "
        "(identity tying, CC-WS3-003 — the marked claim location and the pinned prose blob must "
        "be the same file)",
    )
    # CC-WS3-003: the pytest node id's file component (before `::`) must
    # equal inputs.test.path, separator-normalized, so the recorded node id
    # can never silently claim a different test file than the one whose
    # blob is actually pinned and drift-checked.
    test_role = inputs["test"]
    assert isinstance(test_role, RoleFile)
    assert test_role.node_id is not None
    node_file_part = test_role.node_id.partition("::")[0].replace("\\", "/")
    normalized_test_path = test_role.path.replace("\\", "/")
    _require(
        node_file_part == normalized_test_path,
        f"{claim_id}: inputs.test node_id file component {node_file_part!r} != inputs.test.path "
        f"{test_role.path!r} (identity tying, CC-WS3-003 — the pytest node id and the pinned test "
        "blob must name the same file)",
    )

    controls_raw = value.get("controls")
    _require(isinstance(controls_raw, list), f"{claim_id}: 'controls' must be a list")
    controls = [_parse_control(item, f"{claim_id}.controls[{i}]") for i, item in enumerate(controls_raw)]
    control_ids = [control.id for control in controls]
    dup_controls = sorted({cid for cid in control_ids if control_ids.count(cid) > 1})
    _require(
        not dup_controls,
        f"{claim_id}: duplicate control id(s) {dup_controls} — two controls of one claim would "
        "resolve to the same authority path (malformed; per-control paths must be structurally unique)",
    )
    if resolution == "external_evidence":
        # CC-WS3-002(a) (Critical, round-2 audit): an external_evidence
        # entry with no ci_safe:false control (empty controls, or every
        # control marked ci_safe:true) can never actually be resolved by
        # the D5 external path - ci_safe:true controls run same-run and
        # external_evidence entries by definition have no same-run
        # producer evidence backing them. That shape is malformed, not a
        # legitimately-unproven claim: exit 2, not a silent pass.
        non_ci_safe_controls = [control for control in controls if not control.ci_safe]
        _require(
            bool(non_ci_safe_controls),
            f"{claim_id}: resolution external_evidence requires at least one control with "
            "ci_safe: false (empty controls, or all-ci_safe controls, cannot ever be resolved by "
            "the D5 external-evidence path — malformed)",
        )

    return ClaimEntry(
        id=claim_id,
        claim=claim_text,
        where_file=where_file,
        where_anchor=where_anchor,
        resolution=resolution,
        inputs=inputs,
        controls=controls,
    )


def load_registry(path: Path) -> Registry:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise MalformedRegistryError(f"cannot load registry {path}: {error}") from error
    _require(isinstance(raw, dict), "registry must be a YAML mapping at the top level")
    # CC-WS3-007 residue (round-6 fold): registry-root additionalProperties
    # parity -- see _REGISTRY_ROOT_KEYS above.
    _reject_unknown_keys(raw, _REGISTRY_ROOT_KEYS, "registry root")

    schema_version = raw.get("schema_version")
    _require(schema_version == 1, f"registry schema_version must be 1, got {schema_version!r}")

    governed_raw = raw.get("governed_doc_set")
    _require(isinstance(governed_raw, list) and len(governed_raw) >= 1, "governed_doc_set must be a non-empty list")
    governed_doc_set: list[GovernedDoc] = []
    for index, item in enumerate(governed_raw):
        _require(isinstance(item, dict), "governed_doc_set entries must be mappings")
        # CC-WS3-007 residue (round-6 fold): governed_doc_set item
        # additionalProperties parity -- see _GOVERNED_DOC_KEYS above.
        _reject_unknown_keys(item, _GOVERNED_DOC_KEYS, f"governed_doc_set[{index}]")
        doc_path = item.get("path")
        doc_format = item.get("format")
        enforced = item.get("enforced")
        _require(isinstance(doc_path, str) and bool(doc_path), "governed_doc_set entry needs a non-empty 'path'")
        _require(doc_format in ("markdown", "python"), f"governed_doc_set[{doc_path}]: format must be markdown or python")
        _require(isinstance(enforced, bool), f"governed_doc_set[{doc_path}]: 'enforced' must be a boolean")
        governed_doc_set.append(GovernedDoc(path=doc_path, doc_format=doc_format, enforced=enforced))

    tokens_raw = raw.get("strong_claim_tokens")
    _require(isinstance(tokens_raw, list) and len(tokens_raw) >= 1, "strong_claim_tokens must be a non-empty list")
    for token in tokens_raw:
        _require(isinstance(token, str) and bool(token), "strong_claim_tokens entries must be non-empty strings")
    strong_claim_tokens = tuple(tokens_raw)

    entries_raw = raw.get("entries")
    _require(isinstance(entries_raw, list), "'entries' must be a list")
    entries = [_parse_entry(item) for item in entries_raw]

    ids = [entry.id for entry in entries]
    duplicates = sorted({claim_id for claim_id in ids if ids.count(claim_id) > 1})
    _require(not duplicates, f"duplicate claim id(s) in registry: {duplicates}")

    return Registry(
        schema_version=schema_version,
        governed_doc_set=governed_doc_set,
        strong_claim_tokens=strong_claim_tokens,
        entries=entries,
    )


# ---------------------------------------------------------------------------
# D2: blob-drift check
# ---------------------------------------------------------------------------


def blob_drift_violations(repo_root: Path, registry: Registry) -> list[str]:
    violations: list[str] = []
    for entry in registry.entries:
        for role_label, role_file in entry.role_files():
            target = repo_root / role_file.path
            if not target.exists():
                violations.append(
                    f"{entry.id}: input role {role_label} path {role_file.path!r} does not exist "
                    "(re-prove or re-bind)"
                )
                continue
            current_blob = git_hash_object(repo_root, role_file.path)
            if current_blob != role_file.blob:
                violations.append(
                    f"{entry.id}: input role {role_label} ({role_file.path}) blob drift — "
                    f"recorded {role_file.blob}, current {current_blob} (re-prove or re-bind)"
                )
    return violations


# ---------------------------------------------------------------------------
# CC-WS3-001 (round-2 audit): claim-text capability-token lexical tripwire
# ---------------------------------------------------------------------------


def claim_capability_token_violations(registry: Registry) -> list[str]:
    """Heuristic (not proof — see CAPABILITY_TOKENS docstring above): every
    capability token from CAPABILITY_TOKENS that appears (word-bounded,
    case-insensitive) in an entry's `claim` text must ALSO appear somewhere
    in that entry's bound `test` role path or pytest node id. Catches the
    ws2-postgres-restore-drill class of defect — prose claims "restore",
    the bound test file is named only "backup" — without understanding
    what the test actually does."""
    violations: list[str] = []
    token_re = _token_pattern(CAPABILITY_TOKENS)
    for entry in registry.entries:
        claim_tokens = {match.lower() for match in token_re.findall(entry.claim)}
        if not claim_tokens:
            continue
        test_role = entry.inputs.get("test")
        if not isinstance(test_role, RoleFile):
            continue
        haystack = f"{test_role.path} {test_role.node_id or ''}".lower()
        for token in sorted(claim_tokens):
            if token not in haystack:
                violations.append(
                    f"{entry.id}: claim text uses capability token {token!r} but bound test "
                    f"{test_role.path!r} (node {test_role.node_id!r}) never mentions {token!r} "
                    "(CC-WS3-001 lexical tripwire — claim may be overclaiming a capability its "
                    "bound test does not exercise by name; not proof, forces a review)"
                )
    return violations


# ---------------------------------------------------------------------------
# D1: marker scan
# ---------------------------------------------------------------------------


def _bullet_split(text: str) -> list[str]:
    """Split text into runs starting at each top-level bullet ("* " or
    "- "); text before the first bullet stays a leading run. Shared by
    `_paragraph_blocks` (python doc blocks ARE bullet runs) and
    `_capability_sub_blocks` (bullet-level refinement of a markdown
    paragraph block, below)."""
    lines = text.splitlines()
    runs: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^\s{0,4}[*-]\s", line) and current:
            runs.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        runs.append(current)
    return ["\n".join(run) for run in runs]


def _paragraph_blocks(text: str, doc_format: str) -> list[str]:
    """Split text into adjacency blocks: markdown blank-line paragraphs, or
    (for python) bullet-delimited runs inside the module docstring."""
    if doc_format == "markdown":
        return re.split(r"\n\s*\n", text)
    return _bullet_split(text)


def _blank_line_blocks(text: str) -> list[tuple[int, str]]:
    """CC-WS3-008 round-7: the same markdown blank-line-delimited paragraph
    grouping `_paragraph_blocks` always used, but position-aware -- each
    block is paired with its 1-indexed starting line number in `text`, so
    the round-7 fail-closed violation can name a real line."""
    lines = text.splitlines()
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    start = 1
    for lineno, line in enumerate(lines, start=1):
        if line.strip() == "":
            if current:
                blocks.append((start, "\n".join(current)))
                current = []
            continue
        if not current:
            start = lineno
        current.append(line)
    if current:
        blocks.append((start, "\n".join(current)))
    return blocks


def _capability_sub_blocks(block: str) -> list[str]:
    """CC-WS3-008 (round-5 audit, Major): bullet-level refinement of a
    governed PYTHON docstring block, for the capability-coverage check
    only. `_paragraph_blocks` already scopes python blocks to one bullet
    each, so this is normally a no-op (bullet-splitting a single bullet
    yields that same one block back) -- it stays a real refinement for a
    bullet whose OWN continuation text happens to embed a further bullet
    line. Markdown blocks no longer route through here as of round 7: see
    `_markdown_item_locality`, which replaces this shallow split for
    markdown with true multi-form, multi-depth item locality."""
    return _bullet_split(block)


# ---------------------------------------------------------------------------
# CC-WS3-008 round-7: true markdown list-item locality across every list
# form allowed on governed surfaces ("*", "-", "+", ordered "1." / "1)",
# each optionally behind a blockquote prefix, at any indentation), plus a
# fail-closed rule for list-start shapes outside that supported set.
# ---------------------------------------------------------------------------

# A leading blockquote prefix: one or more ">" markers, each optionally
# followed by one space/tab, stripped before marker detection so a quoted
# list item ("> * text") is recognized the same as an unquoted one.
_BLOCKQUOTE_PREFIX_RE = re.compile(r"^(?:>[ \t]?)+")

# The supported list-item marker shapes: "*"/"-"/"+" bullets, ordered-dot
# ("1. ", "12. "), ordered-paren ("1) "). Requires at least one space/tab
# after the marker (matches ordinary Markdown; a bare "*word*" or "-1" is
# not a list item and must not be treated as one).
_SUPPORTED_LIST_ITEM_RE = re.compile(r"^([*+-]|\d{1,9}[.)])([ \t]+)(.*)$")

# A BROADER "this looks like it might be a list item" shape -- superset of
# the supported markers above, plus a bare letter marker ("a.", "A)") that
# this splitter does NOT support. Used only to detect list forms outside
# the supported set for the round-7 fail-closed rule (rule 3); never used
# to actually localize an item.
_GENERIC_LIST_START_RE = re.compile(r"^([*+-]|\d{1,9}[.)]|[A-Za-z][.)])[ \t]+")


def _markdown_item_locality(text: str) -> tuple[list[str], list[tuple[int, str, str]]]:
    """CC-WS3-008 round-7: split one governed markdown block (already
    blank-line-scoped by the caller) into item-level sub-blocks with TRUE
    locality, across every supported list form, at any indentation depth.

    Each item at every nesting depth becomes its OWN sub-block: its own
    text plus lazy continuation lines, EXCLUDING any nested child item (a
    child is always its own separate sub-block) -- no parent, sibling, or
    child inheritance in either direction. Leading text before the first
    recognized item is its own sub-block too, matching the pre-existing
    `_bullet_split` "leading run" convention.

    Nesting rule: a new item line is a CHILD of the innermost still-open
    item when it shares that item's blockquote depth AND its marker starts
    strictly further right than that item's own marker; otherwise it
    closes that item (and any shallower-or-equal-indent open ancestors)
    and becomes a sibling, or a new top-level item once the stack empties.

    Returns `(sub_blocks, unsupported)`:

    * `sub_blocks` -- item/leading texts safe for the caller's ordinary
      per-item capability-coverage scan. A run contaminated by an
      unsupported list-start line (see below) is EXCLUDED here: round-7
      rule 3 forbids ever falling back to paragraph-level (or any other
      unverified) grouping for it.
    * `unsupported` -- `(1-indexed line number in text, raw line text,
      that run's full own text)` for every line matching a generic
      list-start shape (`_GENERIC_LIST_START_RE`) the supported marker set
      does not cover -- e.g. a letter-ordered "a." item. The third field
      is the full text of whatever item/leading run the line was
      accumulated into (its own text plus lazy continuation, the same
      "adjacent content" a supported item would carry), letting the
      caller fail closed when a strong-claim token or claim marker sits
      in or next to content this splitter cannot confidently localize."""
    lines = text.splitlines()
    stack: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    unsupported: list[tuple[int, str, list[str]]] = []
    leading: list[str] = []
    leading_start = 1
    leading_unsupported = False

    def close_top() -> None:
        closed.append(stack.pop())

    for lineno, raw_line in enumerate(lines, start=1):
        bq_match = _BLOCKQUOTE_PREFIX_RE.match(raw_line)
        quote_depth = raw_line[: bq_match.end()].count(">") if bq_match else 0
        rest = raw_line[bq_match.end() :] if bq_match else raw_line
        stripped = rest.lstrip(" \t")
        marker_indent = len(rest) - len(stripped)

        supported = _SUPPORTED_LIST_ITEM_RE.match(stripped)
        if supported:
            while stack and not (
                stack[-1]["quote_depth"] == quote_depth and marker_indent > stack[-1]["marker_indent"]
            ):
                close_top()
            stack.append(
                {
                    "marker_indent": marker_indent,
                    "quote_depth": quote_depth,
                    "lines": [raw_line],
                    "start": lineno,
                    "unsupported": False,
                }
            )
            continue

        is_unsupported_shape = bool(_GENERIC_LIST_START_RE.match(stripped))
        if stack:
            stack[-1]["lines"].append(raw_line)
            if is_unsupported_shape:
                stack[-1]["unsupported"] = True
                unsupported.append((lineno, raw_line, stack[-1]["lines"]))
        else:
            if not leading:
                leading_start = lineno
            leading.append(raw_line)
            if is_unsupported_shape:
                leading_unsupported = True
                unsupported.append((lineno, raw_line, leading))

    while stack:
        close_top()

    entries: list[tuple[int, str]] = []
    if leading and not leading_unsupported:
        entries.append((leading_start, "\n".join(leading)))
    for item in closed:
        if not item["unsupported"]:
            entries.append((item["start"], "\n".join(item["lines"])))
    entries.sort(key=lambda pair: pair[0])

    resolved_unsupported = [(lineno, raw_line, "\n".join(bucket)) for lineno, raw_line, bucket in unsupported]
    return [item_text for _, item_text in entries], resolved_unsupported


def _token_pattern(tokens: tuple[str, ...]) -> re.Pattern[str]:
    alternation = "|".join(re.escape(token) for token in tokens)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


def scan_marker_violations(repo_root: Path, registry: Registry) -> list[str]:
    violations: list[str] = []
    entry_ids = {entry.id for entry in registry.entries}
    entry_by_id = {entry.id: entry for entry in registry.entries}
    token_re = _token_pattern(registry.strong_claim_tokens)
    capability_re = _token_pattern(BLOCK_CAPABILITY_TOKENS)

    for doc in registry.governed_doc_set:
        if not doc.enforced:
            continue
        target = repo_root / doc.path
        if not target.exists():
            violations.append(f"governed doc {doc.path} does not exist")
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        marker_re = MD_MARKER_RE if doc.doc_format == "markdown" else PY_MARKER_RE
        # CC-WS3-008 round-7: markdown blocks carry their 1-indexed starting
        # line number too, so the fail-closed rule below can name a real
        # line; python blocks don't need it (that rule is markdown-only),
        # so they're paired with a dummy start of 1.
        if doc.doc_format == "markdown":
            blocks = _blank_line_blocks(text)
        else:
            blocks = [(1, block) for block in _paragraph_blocks(text, doc.doc_format)]
        for block_start, block in blocks:
            # CC-WS3-008 round-8 (round-7 verdict, Major): unsupported-form
            # detection MUST run BEFORE the strong-token and marker early
            # exits below, so BOTH one-sided triggers reach it -- a claim
            # marker with no strong token anywhere in the block (round-7
            # gap: the "no token -> continue" exit below skipped this
            # analysis entirely, so `scan_marker_violations` returned []),
            # and a strong token with no marker anywhere in the block
            # (round-7 gap: the "no markers -> continue" exit emitted only
            # the generic unmarked-token message and returned before this
            # analysis ever ran). Running it unconditionally, per markdown
            # block, up front closes both gaps; an unsupported run with
            # NEITHER a token nor a marker in its own span still stays
            # non-violating (checked per-span below, same as round 7's
            # precision companion).
            markdown_sub_blocks: list[str] | None = None
            if doc.doc_format == "markdown":
                markdown_sub_blocks, unsupported_shapes = _markdown_item_locality(block)
                for rel_lineno, raw_line, span_text in unsupported_shapes:
                    if token_re.search(span_text) or marker_re.search(span_text):
                        violations.append(
                            f"{doc.path}:{block_start + rel_lineno - 1}: unsupported list form "
                            f"for locality analysis (line: {raw_line.strip()!r}) -- CC-WS3-008 "
                            "round-7 fail-closed: this list-item start is outside the supported "
                            "*/-/+/ordered-dot/ordered-paren (optionally blockquoted) set, and a "
                            "strong-claim token or claim marker sits in or adjacent to it; never "
                            "silently grouped at paragraph level"
                        )

            if not token_re.search(block):
                continue
            markers = marker_re.findall(block)
            if not markers:
                match = token_re.search(block)
                excerpt = match.group(0) if match else ""
                violations.append(
                    f"{doc.path}: unmarked strong-claim token {excerpt!r} in governed doc "
                    f"(no adjacent claim marker) — block: {block.strip()[:120]!r}"
                )
                continue
            for marker_id in markers:
                if marker_id not in entry_ids:
                    violations.append(
                        f"{doc.path}: claim marker references unknown registry entry {marker_id!r}"
                    )

            # CC-WS3-008 round-7: for markdown, split with TRUE per-item
            # locality across every supported list form (*, -, +, ordered,
            # blockquoted, at any nesting depth -- see
            # `_markdown_item_locality`); the split (and the fail-closed
            # unsupported-form check above) already ran up front, round-8.
            if doc.doc_format == "markdown":
                sub_blocks = markdown_sub_blocks
            else:
                sub_blocks = _capability_sub_blocks(block)

            # CC-WS3-008 (round-5 audit, Major): per-block CAPABILITY
            # coverage. A marker for one registered capability (e.g.
            # capture) must not satisfy D1 for a BROADER capability (e.g.
            # restore) strong-claimed in the same governed block — a
            # capture-only entry's claim text does not mention "restore",
            # so it cannot cover a block that strong-claims restore.
            # Scoped to item-level sub-blocks (see _markdown_item_locality /
            # _capability_sub_blocks) so a strong claim in one item is
            # judged only against capability words genuinely co-occurring
            # in THAT item, not a sibling/parent/child's unrelated sentence
            # sharing the same blank-line-delimited markdown paragraph.
            for sub_block in sub_blocks:
                if not token_re.search(sub_block):
                    continue
                sub_capabilities = {match.lower() for match in capability_re.findall(sub_block)}
                if not sub_capabilities:
                    continue
                # CC-WS3-008 residual (round-6 verdict, Major): STRICT
                # sub-block locality -- no `or markers` fallback. The
                # round-5 fallback let a marker-free strong-claim sub-block
                # "inherit" every marker from its enclosing paragraph, so a
                # SIBLING bullet's marker (or an unrelated marker sharing an
                # oversized python bullet) could silently cover a capability
                # its own sub-block never actually bound. A sub-block's
                # markers are only the markers found IN that sub-block.
                sub_markers = marker_re.findall(sub_block)
                covered: set[str] = set()
                for marker_id in sub_markers:
                    covering_entry = entry_by_id.get(marker_id)
                    if covering_entry is None:
                        continue
                    covered |= {match.lower() for match in capability_re.findall(covering_entry.claim)}
                uncovered = sorted(sub_capabilities - covered)
                for capability in uncovered:
                    if sub_markers:
                        marker_note = f"markers present: {sorted(sub_markers)}"
                    else:
                        # Name the nearest markers (the enclosing block's,
                        # minus this empty sub-block's own) so a reviewer
                        # can see they exist, just not in THIS sub-block --
                        # the round-5 fallback's exact blind spot.
                        nearest = sorted(set(markers) - set(sub_markers))
                        marker_note = f"no marker of its own (nearest markers, in the enclosing block: {nearest})"
                    violations.append(
                        f"{doc.path}: block strong-claims capability {capability!r} but no adjacent "
                        f"marker's registry entry claim text covers {capability!r} ({marker_note}) -- "
                        f"a capture-only entry must not satisfy a block that strong-claims a broader "
                        f"capability, and a sibling sub-block's marker must not cover an unmarked "
                        f"sub-block (D1 per-block capability coverage, strict sub-block locality, "
                        f"CC-WS3-008) — block: {sub_block.strip()[:160]!r}"
                    )

    # Stale anchor: every entry whose where.file is itself governed-doc-scanned
    # must have its recorded anchor text still present in that file.
    for entry in registry.entries:
        target = repo_root / entry.where_file
        if not target.exists():
            violations.append(f"{entry.id}: where.file {entry.where_file!r} does not exist")
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        if entry.where_anchor not in text:
            violations.append(
                f"{entry.id}: where.anchor {entry.where_anchor!r} not found in {entry.where_file} "
                "(stale anchor)"
            )

    return violations


# ---------------------------------------------------------------------------
# D3: same-run mode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceIdentity:
    event_name: str
    pr_head_sha: str | None
    github_sha: str


def resolve_source_sha(identity: SourceIdentity) -> str:
    """D3: pull_request events use the PR head SHA, never GITHUB_SHA (the
    synthetic merge commit). Raises ViolationError if GITHUB_SHA was substituted."""
    if identity.event_name == "pull_request":
        if not identity.pr_head_sha:
            raise CannotCheckError("pull_request event but no PR head SHA available")
        return identity.pr_head_sha
    return identity.github_sha


def assert_checkout_matches_source(repo_root: Path, source_sha: str) -> None:
    actual = git_rev_parse(repo_root, "HEAD")
    if actual != source_sha:
        raise ViolationError(
            f"verifier's own checkout HEAD {actual} does not equal resolved source SHA {source_sha} "
            "(synthetic merge commit substituted for head SHA?)"
        )


def parse_workflow_jobs(workflow_path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise MalformedRegistryError(f"cannot parse workflow file {workflow_path}: {error}") from error
    if not isinstance(raw, dict):
        raise MalformedRegistryError(f"workflow file {workflow_path} is not a YAML mapping")
    jobs = raw.get("jobs")
    if not isinstance(jobs, dict):
        raise MalformedRegistryError(f"workflow file {workflow_path} has no 'jobs' mapping")
    return jobs


def workflow_contract_violations(
    workflow_jobs: dict[str, Any], contract: dict[str, Any]
) -> list[str]:
    violations: list[str] = []
    inventory = set(contract.get("workflow_job_inventory") or [])
    actual_jobs = set(workflow_jobs.keys())
    unlisted_live = actual_jobs - inventory
    listed_dead = inventory - actual_jobs
    if unlisted_live:
        violations.append(f"job-inventory drift: live job(s) unlisted in contract: {sorted(unlisted_live)}")
    if listed_dead:
        violations.append(f"job-inventory drift: contract lists dead job(s): {sorted(listed_dead)}")

    producers = contract.get("expected_producers") or {}
    verifier_job = contract.get("verifier_job")
    if verifier_job in producers:
        violations.append(f"verifier job {verifier_job!r} must never appear in expected_producers")

    if isinstance(verifier_job, str) and verifier_job in workflow_jobs:
        needs = workflow_jobs[verifier_job].get("needs")
        needs_set = set(needs) if isinstance(needs, list) else ({needs} if isinstance(needs, str) else set())
        producer_keys = set(producers.keys())
        if needs_set != producer_keys:
            violations.append(
                f"verifier job {verifier_job!r} needs {sorted(needs_set)} but expected_producers "
                f"keys are {sorted(producer_keys)} (must be exactly equal)"
            )
    elif isinstance(verifier_job, str):
        violations.append(f"contract's verifier_job {verifier_job!r} not found in workflow jobs")

    return violations


@dataclass(frozen=True)
class JunitCase:
    classname: str
    name: str
    status: str  # "passed" | "skipped" | "failed"

    @property
    def node_id(self) -> str:
        # classname is dotted (tests.dr.test_restore_drill); node ids in the
        # registry are path-form (tests/dr/test_restore_drill.py::name).
        return self.classname

    def matches_node_id(self, node_id: str) -> bool:
        path_part, _, func_part = node_id.partition("::")
        dotted = path_part.removesuffix(".py").replace("/", ".")
        return dotted == self.classname and func_part == self.name


def parse_junit(path: Path) -> list[JunitCase]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as error:
        raise MalformedRegistryError(f"malformed junit XML at {path}: {error}") from error
    cases: list[JunitCase] = []
    for case in tree.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        if case.find("skipped") is not None:
            status = "skipped"
        elif case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        else:
            status = "passed"
        cases.append(JunitCase(classname=classname, name=name, status=status))
    return cases


def find_producer_artifact(artifacts_dir: Path, artifact_name: str, file_name: str) -> Path | None:
    """CC-WS3-004 (Major, round-2 audit): resolves ONLY the contract's exact
    artifact directory/name — `<artifacts_dir>/<artifact_name>/<file_name>`.

    The prior implementation fell back to `artifacts_dir.rglob(file_name)`
    and silently returned WHATEVER matching filename it found first,
    anywhere under artifacts_dir. That is an ambiguous-duplicate hazard: a
    decoy or stale file sharing a producer's junit/meta filename but sitting
    in the WRONG artifact directory could be silently routed to the wrong
    producer instead of correctly reporting that producer's artifact as
    missing. There is no repository-wide (or artifacts-dir-wide) fallback
    anymore — a duplicate filename anywhere other than the exact contract
    path is simply never found, which surfaces as an honest "missing"
    violation rather than an ambiguous, unlogged pick.
    """
    direct = artifacts_dir / artifact_name / file_name
    return direct if direct.exists() else None


@dataclass(frozen=True)
class ProducerEvidence:
    junit_cases: list[JunitCase]
    meta: dict[str, Any]


def producer_evidence_violations(
    contract: dict[str, Any],
    artifacts_dir: Path,
    producer_results: dict[str, str],
    source_sha: str,
    expected_run_id: str | None = None,
    expected_run_attempt: str | None = None,
) -> tuple[list[str], dict[str, ProducerEvidence]]:
    violations: list[str] = []
    producers: dict[str, Any] = contract.get("expected_producers") or {}
    evidence_by_producer: dict[str, ProducerEvidence] = {}

    for producer, spec in producers.items():
        result = producer_results.get(producer)
        if result != "success":
            violations.append(
                f"producer {producer!r} result is {result!r}, not 'success' (fail-closed: any "
                "producer not success fails the verifier)"
            )
            continue

        junit_path = find_producer_artifact(artifacts_dir, spec["junit_artifact"], spec["junit_file"])
        meta_path = find_producer_artifact(artifacts_dir, spec["meta_artifact"], spec["meta_file"])
        if junit_path is None:
            violations.append(f"producer {producer!r}: junit artifact {spec['junit_file']!r} missing")
        if meta_path is None:
            violations.append(f"producer {producer!r}: meta artifact {spec['meta_file']!r} missing")
        if junit_path is None or meta_path is None:
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            violations.append(f"producer {producer!r}: malformed meta JSON: {error}")
            continue
        if not isinstance(meta, dict) or "sha" not in meta:
            violations.append(f"producer {producer!r}: meta JSON missing required 'sha' field")
            continue
        if meta.get("sha") != source_sha:
            violations.append(
                f"producer {producer!r}: meta SHA {meta.get('sha')!r} != resolved source SHA "
                f"{source_sha!r} (checkout/meta/binding mismatch — wrong-run or wrong-SHA artifact)"
            )
        # CC-WS3-004 (Major, round-2 audit): meta.job_id must equal the
        # producer key itself. Without this, artifact-routing being exact
        # (find_producer_artifact, above) is not enough on its own — a
        # correctly-located file could still carry ANOTHER job's metadata
        # (e.g. a copy/paste or upload-step mistake) and be silently
        # accepted as this producer's evidence.
        if meta.get("job_id") != producer:
            violations.append(
                f"producer {producer!r}: meta job_id {meta.get('job_id')!r} != producer id "
                f"{producer!r} (metadata identity mismatch — CC-WS3-004)"
            )
        if expected_run_id is not None and meta.get("run_id") != expected_run_id:
            violations.append(
                f"producer {producer!r}: meta run_id {meta.get('run_id')!r} != this workflow run's "
                f"run_id {expected_run_id!r} (junit-meta from ANOTHER run)"
            )
        # CC-WS3-004: bind run_attempt to the verifier's own current context
        # (GITHUB_RUN_ATTEMPT) — a re-run of a PREVIOUS attempt's producer
        # job could otherwise leave a stale-but-same-run_id artifact behind
        # that this run's download step still happens to pick up.
        if expected_run_attempt is not None and meta.get("run_attempt") != expected_run_attempt:
            violations.append(
                f"producer {producer!r}: meta run_attempt {meta.get('run_attempt')!r} != this "
                f"workflow run's run_attempt {expected_run_attempt!r} (prior-attempt artifact — "
                "CC-WS3-004)"
            )

        cases = parse_junit(junit_path)
        collected = [c for c in cases if c.status != "skipped"]
        floor = spec.get("junit_collection_floor", 0)
        if len(collected) < floor:
            violations.append(
                f"producer {producer!r}: collected {len(collected)} non-skipped test(s), below its "
                f"per-producer floor {floor}"
            )
        evidence_by_producer[producer] = ProducerEvidence(junit_cases=cases, meta=meta)

    return violations, evidence_by_producer


def claim_test_violations(
    registry: Registry, evidence_by_producer: dict[str, ProducerEvidence]
) -> list[str]:
    violations: list[str] = []
    all_cases = [case for evidence in evidence_by_producer.values() for case in evidence.junit_cases]
    for entry in registry.entries:
        if entry.resolution != "same_run":
            continue
        test_role = entry.inputs["test"]
        assert isinstance(test_role, RoleFile)
        node_id = test_role.node_id
        assert node_id is not None
        matches = [case for case in all_cases if case.matches_node_id(node_id)]
        if not matches:
            violations.append(f"{entry.id}: claim test node {node_id!r} not observed in any producer's junit")
            continue
        if any(case.status != "passed" for case in matches):
            bad = [case for case in matches if case.status != "passed"]
            violations.append(
                f"{entry.id}: claim test node {node_id!r} did not PASS this run "
                f"(status: {bad[0].status}; skipped/xfail counts as fail)"
            )
    return violations


def ci_safe_control_violations(
    registry: Registry, evidence_by_producer: dict[str, ProducerEvidence]
) -> list[str]:
    violations: list[str] = []
    all_cases = [case for evidence in evidence_by_producer.values() for case in evidence.junit_cases]
    for entry in registry.entries:
        for control in entry.controls:
            if not control.ci_safe:
                continue
            node_id = control.command
            matches = [case for case in all_cases if case.matches_node_id(node_id)]
            if not matches:
                violations.append(
                    f"{entry.id}: ci_safe control {control.id!r} node {node_id!r} not observed in "
                    "any producer's junit this run"
                )
                continue
            if any(case.status != "passed" for case in matches):
                violations.append(
                    f"{entry.id}: ci_safe control {control.id!r} node {node_id!r} did not pass "
                    f"this run ({control.expected_red_when})"
                )
    return violations


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def run_same_run_mode(args: argparse.Namespace, repo_root: Path) -> list[str]:
    """D1/D2/D3/D4 same-run enforcement -- the ONLY mode this verifier runs.

    2026-08-07: this used to also load and structurally validate
    docs/claims/trust-root.yaml (D6) as a prerequisite for D5's
    external-evidence/authority-record resolution. D5/D6 (the
    owner/auditor-signed authority-record requirement resolved against the
    separate civiccast-audit-control repository) were AI-invented ceremony
    the owner never requested and have been removed outright -- see the
    module docstring above and CHANGELOG.md. D2 blob-drift binding
    immediately below is unaffected and unweakened: it still runs,
    unconditionally, against EVERY registered claim's every input role
    (including claims still marked ``resolution: external_evidence`` in the
    registry) -- that is the half of this mechanism the owner explicitly
    kept.
    """
    registry = load_registry(args.registry)
    violations: list[str] = []
    violations.extend(claim_capability_token_violations(registry))
    violations.extend(scan_marker_violations(repo_root, registry))
    violations.extend(blob_drift_violations(repo_root, registry))

    contract = yaml.safe_load(args.workflow_contract.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise MalformedRegistryError("workflow contract is not a YAML mapping")

    workflow_jobs = parse_workflow_jobs(args.workflow_file)
    violations.extend(workflow_contract_violations(workflow_jobs, contract))

    identity = SourceIdentity(
        event_name=args.event_name,
        pr_head_sha=args.pr_head_sha,
        github_sha=args.github_sha or "",
    )
    try:
        source_sha = resolve_source_sha(identity)
        assert_checkout_matches_source(repo_root, source_sha)
    except ViolationError as error:
        violations.append(str(error))
        return violations
    # CannotCheckError intentionally propagates (exit 2): "offline/no-token
    # = exit 2, never a silent pass" applies to source-identity resolution too.

    if args.producer_results:
        producer_results = json.loads(args.producer_results.read_text(encoding="utf-8"))
    else:
        producer_results = {}

    producer_violations, evidence_by_producer = producer_evidence_violations(
        contract,
        args.artifacts_dir,
        producer_results,
        source_sha,
        expected_run_id=args.run_id,
        expected_run_attempt=args.run_attempt,
    )
    violations.extend(producer_violations)
    violations.extend(claim_test_violations(registry, evidence_by_producer))
    if args.ci_safe_controls:
        violations.extend(ci_safe_control_violations(registry, evidence_by_producer))

    return violations




def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # 2026-08-07: "external-evidence" removed from --mode's choices along
    # with the D5/D6 authority-record verifier code it selected (see the
    # module docstring and CHANGELOG.md). --mode is kept as a required,
    # single-choice argument rather than dropped outright so every existing
    # `--mode same-run` invocation (CI, tests, docs) keeps working
    # unchanged; a future cleanup MAY drop it once nothing still passes it.
    parser.add_argument("--mode", required=True, choices=["same-run"])
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--workflow-contract", type=Path)
    parser.add_argument("--workflow-file", type=Path)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--producer-results", type=Path)
    parser.add_argument("--ci-safe-controls", action="store_true")
    parser.add_argument("--event-name", default="pull_request")
    parser.add_argument("--pr-head-sha")
    parser.add_argument("--github-sha")
    parser.add_argument("--run-id", help="expected GITHUB_RUN_ID; producer meta from another run is rejected")
    parser.add_argument(
        "--run-attempt",
        help="expected GITHUB_RUN_ATTEMPT; producer meta from a prior attempt is rejected (CC-WS3-004)",
    )
    parser.add_argument("--repo-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    repo_root = args.repo_root or find_repo_root(__file__)

    if args.pr_head_sha is None:
        event = os.environ.get("GITHUB_EVENT_NAME", args.event_name)
        args.event_name = event
        args.pr_head_sha = os.environ.get("CLAIMS_PR_HEAD_SHA") or None
    if args.github_sha is None:
        args.github_sha = os.environ.get("GITHUB_SHA", "")
    if args.run_id is None:
        args.run_id = os.environ.get("GITHUB_RUN_ID") or None
    if args.run_attempt is None:
        args.run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT") or None

    try:
        for required in ("workflow_contract", "workflow_file", "artifacts_dir"):
            if getattr(args, required) is None:
                raise MalformedRegistryError(f"--{required.replace('_', '-')} is required for --mode same-run")
        violations = run_same_run_mode(args, repo_root)
    except CannotCheckError as error:
        print(f"CANNOT-CHECK: {error}", file=sys.stderr)
        return 2
    except MalformedRegistryError as error:
        print(f"MALFORMED: {error}", file=sys.stderr)
        return 2

    if violations:
        for line in violations:
            print(f"VIOLATION: {line}")
        print(f"claims-evidence: FAIL ({len(violations)} violation(s))")
        return 1

    print("claims-evidence: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
