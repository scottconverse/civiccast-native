#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish a native-Windows beta-candidate release.

Owner decision 2026-09-02: the coordinating agent cuts beta-candidate
releases going forward. Every green build gets tagged and published on the
PUBLIC repo ``scottconverse/civiccast-native`` as a GitHub pre-release,
because the beta tester (Sergio, "LPM") checks GitHub daily for new
versions. The existing ``v1.0.0-beta.1`` release has NO assets (it was
USB-delivered). GitHub release assets are capped at 2 GB/file; the ~21 GB
AI-model bundle (the ``station\\`` directory in the kit) therefore never
goes on a release -- with PRs #127/#126 merged, the installer reuses AI
models already on the machine (upgrade case) or the USB bundle (first-install
case). Runtime packs are each under 2 GB and DO go on the release.

Every step below is fail-closed: any check failure refuses (raises
``PublishError``, printed and exit 1) before doing anything past that point.
Nothing here ever merges, tags, or publishes anything on this agent's own
initiative outside of what this script's caller explicitly invoked it to do
-- see the module docstring boundary at the bottom of this file's ``main``
for the ``--dry-run`` vs live distinction.

Usage::

    python scripts/release/publish_beta_candidate.py \\
        --kit-dir C:\\CivicCastTester\\kit-staging\\<sha> \\
        --source-sha <sha> \\
        --build-run-id <id> \\
        --gate-a-run-id <id> \\
        --tag v1.0.0-beta.N \\
        [--dry-run] \\
        --truth-status current|staging

``--dry-run`` writes the rendered notes, sidecar, and SHA256SUMS.txt to
``artifacts/release/<tag>/`` and touches no GitHub or git remote state at
all -- no tag, no push, no mutating ``gh`` call. Without ``--dry-run`` it
publishes in an order that can never leave an orphan tag: pre-flight every
asset under GitHub's 2 GiB cap, create the release as a DRAFT targeting
``--source-sha`` with all assets (a draft has no tag), verify every asset's
name and size on the fetched draft (deleting the draft on any mismatch),
then un-draft it -- the one step that creates the public tag, atomically
with its release -- and finally update ``docs/releases/release-truth.yaml``.
No ``git tag``/``git push`` is ever run by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.render_release_notes import render_native_beta_candidate_notes  # noqa: E402

DEFAULT_REPOSITORY = "scottconverse/civiccast-native"
# GitHub's documented per-file release-asset cap is 2 GiB
# (docs.github.com "Managing releases in a repository": "Each file included
# in a release must be under 2 GiB"). Enforced as a pre-flight BEFORE any
# remote mutation so a >= 2 GiB pack can never surface as a half-created
# release.
GITHUB_ASSET_LIMIT_BYTES = 2 * 1024**3
# Release asset naming contract. scripts/download_windows_release_artifacts.ps1's
# NativeCandidate mode and tests/policy/test_windows_release_downloader.py pin
# the downloader's literals against THESE constants so the two cannot drift.
SETUP_ASSET_NAME = "setup.exe"
SHA256SUMS_ASSET_NAME = "SHA256SUMS.txt"
SIDECAR_SUFFIX = ".sidecar.json"
PACK_SUFFIX = ".ccpack"
GATE_A_LANES: tuple[str, ...] = ("clean", "dirty", "download-only")
GATE_A_ARTIFACT_NAMES: dict[str, str] = {
    "clean": "gate-a-verdict-{run_id}",
    "dirty": "gate-a-dirty-verdict-{run_id}",
    "download-only": "gate-a-download-only-verdict-{run_id}",
}

SMARTSCREEN_NOTE = (
    'Windows may show a blue "Windows protected your PC" SmartScreen prompt '
    "on a freshly published installer. This is reputation, not the signature: "
    "a newly issued certificate has no SmartScreen download history yet. The "
    "prompt shows the verified publisher (Scott Converse) and fades as "
    "download volume accrues. See docs/tester/SMARTSCREEN-WALKTHROUGH.md for "
    "the click-through and how to verify the signature yourself first."
)


class PublishError(RuntimeError):
    """A fail-closed refusal. The caller prints this and exits nonzero."""


# ---------------------------------------------------------------------------
# Injectable process runner. Tests monkeypatch this single seam to fake every
# `gh`, `git`, and PowerShell subprocess call without touching the network or
# a real git remote.
# ---------------------------------------------------------------------------
def run_command(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    return subprocess.run(cmd, **kwargs)


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return run_command(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def run_gh(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return run_command(["gh", *args], **kwargs)


# ---------------------------------------------------------------------------
# (a) Layout + version verification
# ---------------------------------------------------------------------------
def verify_layout(kit_dir: Path) -> tuple[Path, list[Path]]:
    """Require setup.exe, packs\\*.ccpack (>=1), and a station\\ dir.

    Matches what .github/workflows/native-beta-candidate-artifacts.yml says
    a kit at C:\\CivicCastTester\\kit-staging\\<sha>\\ contains.
    """

    if not kit_dir.is_dir():
        raise PublishError(f"kit-dir does not exist or is not a directory: {kit_dir}")

    setup = kit_dir / SETUP_ASSET_NAME
    if not setup.is_file():
        raise PublishError(f"kit-dir is missing setup.exe: {setup}")

    packs_dir = kit_dir / "packs"
    if not packs_dir.is_dir():
        raise PublishError(f"kit-dir is missing a packs\\ directory: {packs_dir}")
    packs = sorted(packs_dir.glob(f"*{PACK_SUFFIX}"))
    if not packs:
        raise PublishError(f"packs\\ directory has no *.ccpack files: {packs_dir}")

    station_dir = kit_dir / "station"
    if not station_dir.is_dir():
        raise PublishError(f"kit-dir is missing a station\\ directory: {station_dir}")

    return setup, packs


def get_product_version(setup: Path) -> str:
    proc = run_powershell(f"(Get-Item -LiteralPath '{setup}').VersionInfo.ProductVersion")
    if proc.returncode != 0:
        raise PublishError(
            f"could not read setup.exe ProductVersion via PowerShell: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    version = (proc.stdout or "").strip()
    if not version:
        raise PublishError(f"setup.exe ProductVersion came back empty: {setup}")
    return version


def get_native_source_version() -> str:
    from civiccast._native_version import __version__ as native_version

    return native_version


def verify_version_identity(setup: Path, tag: str) -> str:
    """Require setup.exe ProductVersion == source-tree version == tag (no 'v').

    Returns the agreed version string. Any mismatch refuses.
    """

    if not tag.startswith("v"):
        raise PublishError(f"--tag must start with 'v': {tag!r}")
    tag_version = tag[1:]

    product_version = get_product_version(setup)
    source_version = get_native_source_version()

    if product_version != tag_version:
        raise PublishError(
            f"setup.exe ProductVersion {product_version!r} does not match "
            f"tag {tag!r} (expected {tag_version!r})."
        )
    if source_version != tag_version:
        raise PublishError(
            f"civiccast._native_version.__version__ {source_version!r} does "
            f"not match tag {tag!r} (expected {tag_version!r})."
        )
    return tag_version


# ---------------------------------------------------------------------------
# (b) Authenticode verification
# ---------------------------------------------------------------------------
def verify_signature(setup: Path) -> None:
    proc = run_powershell(f"(Get-AuthenticodeSignature -LiteralPath '{setup}').Status")
    if proc.returncode != 0:
        raise PublishError(
            f"could not run Get-AuthenticodeSignature on {setup}: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    status = (proc.stdout or "").strip()
    if status != "Valid":
        raise PublishError(
            f"setup.exe Authenticode signature status is {status!r}, expected "
            "'Valid' (see CODE_SIGNING_POLICY.md)."
        )


# ---------------------------------------------------------------------------
# (c) Gate A verdict verification
# ---------------------------------------------------------------------------
def download_gate_a_verdicts(
    *, repository: str, gate_a_run_id: str, build_run_id: str, dest_dir: Path
) -> dict[str, dict[str, Any]]:
    """Download and parse gate-a-verdict.json for all three required lanes.

    ``gate_a_run_id`` selects WHICH workflow run's artifacts to fetch from
    (the positional argument to ``gh run download``); ``build_run_id`` names
    WHICH artifact to fetch, because gate-a-station-acceptance.yml's own
    ``run_id`` step output is the build run being validated
    (``github.event.inputs.run_id``), not the Gate A workflow's own run id --
    so every ``gate-a*-verdict-<id>`` artifact it uploads is suffixed with
    the build run id, even though those artifacts live on the Gate A run.
    Confirmed live: Gate A run 33713004718 (validating build 33711079441)
    uploads artifacts named ``gate-a-verdict-33711079441``,
    ``gate-a-dirty-verdict-33711079441``,
    ``gate-a-download-only-verdict-33711079441`` -- never
    ``*-33713004718``. Formatting the artifact name with ``gate_a_run_id``
    (the original code) looks for an artifact that can never exist whenever
    the two run ids differ, which the existing test suite never caught
    because its fakes never modeled a real Gate A run's artifact names.
    """

    verdicts: dict[str, dict[str, Any]] = {}
    for lane in GATE_A_LANES:
        artifact_name = GATE_A_ARTIFACT_NAMES[lane].format(run_id=build_run_id)
        lane_dir = dest_dir / lane
        lane_dir.mkdir(parents=True, exist_ok=True)
        proc = run_gh(
            [
                "run",
                "download",
                gate_a_run_id,
                "-R",
                repository,
                "-n",
                artifact_name,
                "-D",
                str(lane_dir),
            ]
        )
        if proc.returncode != 0:
            raise PublishError(
                f"could not download Gate A verdict artifact {artifact_name!r} "
                f"for lane {lane!r} (run {gate_a_run_id}): "
                f"{(proc.stderr or proc.stdout or '').strip()}"
            )
        verdict_path = lane_dir / "gate-a-verdict.json"
        if not verdict_path.is_file():
            raise PublishError(
                f"downloaded Gate A artifact {artifact_name!r} does not contain "
                f"gate-a-verdict.json for lane {lane!r}."
            )
        try:
            verdicts[lane] = json.loads(verdict_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PublishError(
                f"gate-a-verdict.json for lane {lane!r} is not valid JSON: {exc}"
            ) from exc
    return verdicts


def verify_gate_a_verdicts(verdicts: dict[str, dict[str, Any]], *, source_sha: str) -> None:
    """Require all three lanes PASS and share the same source_sha == --source-sha."""

    missing = [lane for lane in GATE_A_LANES if lane not in verdicts]
    if missing:
        raise PublishError(f"missing Gate A verdict(s) for lane(s): {missing}")

    for lane in GATE_A_LANES:
        doc = verdicts[lane]
        verdict = doc.get("verdict")
        if verdict != "PASS":
            raise PublishError(f"Gate A lane {lane!r} did not PASS (verdict: {verdict!r}).")
        doc_sha = doc.get("source_sha")
        if doc_sha != source_sha:
            raise PublishError(
                f"Gate A lane {lane!r} verdict source_sha {doc_sha!r} does not "
                f"match --source-sha {source_sha!r}."
            )
        # The clean-lane document carries no "lane" field at all
        # (gate_a_verdict.py's build_verdict_document only stamps "lane" when
        # lane != "clean"); dirty/download-only must self-report their lane.
        doc_lane = doc.get("lane", "clean")
        if doc_lane != lane:
            raise PublishError(
                f"Gate A lane {lane!r} verdict document reports lane {doc_lane!r} instead."
            )

    shas = {verdicts[lane].get("source_sha") for lane in GATE_A_LANES}
    if len(shas) != 1:
        raise PublishError(f"Gate A lane verdicts do not share the same source_sha: {shas}")


# ---------------------------------------------------------------------------
# (d) Hashing + manifest
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_sha256sums(files: list[Path]) -> str:
    lines = [f"{sha256_file(path)}  {path.name}" for path in files]
    return "\n".join(lines) + "\n"


def build_sidecar(setup: Path, *, signed: bool) -> dict[str, Any]:
    """Match the shape scripts/policy/check_sidecar_attestation_integrity.py
    and scripts/download_windows_release_artifacts.ps1 already read: a real
    sha256, install_manifest.signed (verified against real Authenticode
    evidence, never a bare flag), and attestation always null (this release
    chain carries no cosign/Sigstore step -- CODE_SIGNING_POLICY.md, ADR
    0022).
    """

    return {
        "sha256": sha256_file(setup),
        "attestation": None,
        "install_manifest": {"signed": signed},
    }


# ---------------------------------------------------------------------------
# (e) Release notes
# ---------------------------------------------------------------------------
def extract_changelog_unreleased(changelog_text: str) -> str:
    match = re.search(
        r"^## \[Unreleased\]\s*$(.*?)(?=^## \[|\Z)",
        changelog_text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1).strip()


def build_run_url(repository: str, run_id: str) -> str:
    return f"https://github.com/{repository}/actions/runs/{run_id}"


def render_notes(
    *,
    tag: str,
    source_sha: str,
    repository: str,
    build_run_id: str,
    gate_a_run_id: str,
    verdicts: dict[str, dict[str, Any]],
    changelog_text: str,
    assets: list[dict[str, Any]],
) -> str:
    lane_verdicts = {lane: verdicts[lane]["verdict"] for lane in GATE_A_LANES}
    return render_native_beta_candidate_notes(
        tag=tag,
        source_sha=source_sha,
        build_run_url=build_run_url(repository, build_run_id),
        gate_a_run_url=build_run_url(repository, gate_a_run_id),
        lane_verdicts=lane_verdicts,
        changelog_unreleased=extract_changelog_unreleased(changelog_text),
        assets=assets,
        smartscreen_note=SMARTSCREEN_NOTE,
    )


# ---------------------------------------------------------------------------
# (f) Publish (or dry-run)
# ---------------------------------------------------------------------------
def verify_gh_auth() -> None:
    """Refuse before anything else if `gh` has no working GitHub login.

    Every later step (Gate A artifact download, draft create, verify,
    un-draft) goes through `gh`; an unauthenticated CLI would otherwise
    surface as a confusing mid-flow failure.
    """

    proc = run_gh(["auth", "status"])
    if proc.returncode != 0:
        raise PublishError(
            "gh is not authenticated (`gh auth status` failed) -- run "
            "`gh auth login` before publishing: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )


def preflight_asset_limits(asset_paths: list[Path]) -> None:
    """Refuse BEFORE any remote mutation if any asset is >= GitHub's 2 GiB cap.

    Prints the complete asset set (name + bytes) so the operator sees exactly
    what would be uploaded.
    """

    print("publish_beta_candidate: release asset set (pre-flight):")
    oversize: list[str] = []
    for path in asset_paths:
        size = path.stat().st_size
        flag = "  OVERSIZE" if size >= GITHUB_ASSET_LIMIT_BYTES else ""
        print(f"  {path.name}  {size:,} bytes{flag}")
        if size >= GITHUB_ASSET_LIMIT_BYTES:
            oversize.append(f"{path.name} ({size:,} bytes)")
    if oversize:
        raise PublishError(
            "asset(s) at or above GitHub's 2 GiB per-file release-asset cap "
            f"({GITHUB_ASSET_LIMIT_BYTES:,} bytes); refusing before any remote "
            f"mutation: {', '.join(oversize)}"
        )


def _gh_error(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stderr or proc.stdout or "").strip()


def delete_draft_release(*, repository: str, tag: str) -> bool:
    """Best-effort delete of a draft release. Returns True on success.

    A draft release has no tag, so deleting it leaves nothing behind. Never
    raises: this runs on an already-failing path, and the original failure
    is what must be reported.
    """

    proc = run_gh(["release", "delete", tag, "-R", repository, "--yes"])
    return proc.returncode == 0


def create_draft_release(
    *,
    repository: str,
    tag: str,
    source_sha: str,
    title: str,
    notes_file: Path,
    asset_paths: list[Path],
) -> None:
    """Create the release as a DRAFT targeting source_sha, with every asset.

    A draft creates NO tag. The public tag is created atomically with the
    release only when `undraft_release` flips `--draft=false`, so a failure
    anywhere before that leaves no orphan tag. On failure here the (possibly
    partially created) draft is deleted best-effort and the failure raised.
    """

    proc = run_gh(
        [
            "release",
            "create",
            tag,
            "-R",
            repository,
            "--draft",
            "--target",
            source_sha,
            "--prerelease",
            "--title",
            title,
            "--notes-file",
            str(notes_file),
            *[str(p) for p in asset_paths],
        ]
    )
    if proc.returncode != 0:
        deleted = delete_draft_release(repository=repository, tag=tag)
        cleanup = "draft deleted" if deleted else "no draft to delete / delete failed"
        raise PublishError(
            f"gh release create (draft) failed for {tag}; {cleanup}; no tag was "
            f"created: {_gh_error(proc)}"
        )


def verify_draft_assets(*, repository: str, tag: str, asset_paths: list[Path]) -> None:
    """Fetch the draft and assert it is still a draft and every expected
    asset is present with a matching size. On ANY mismatch the draft is
    deleted (best-effort) and the mismatch raised -- no tag exists yet, so
    nothing is left behind.
    """

    proc = run_gh(["release", "view", tag, "-R", repository, "--json", "assets,isDraft"])
    if proc.returncode != 0:
        delete_draft_release(repository=repository, tag=tag)
        raise PublishError(
            f"could not fetch draft release {tag} to verify assets (draft deleted): "
            f"{_gh_error(proc)}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        delete_draft_release(repository=repository, tag=tag)
        raise PublishError(
            f"gh release view returned non-JSON output (draft deleted): {exc}"
        ) from exc

    problems: list[str] = []
    if payload.get("isDraft") is not True:
        problems.append("release is not a draft (isDraft != true) -- refusing to continue")
    remote_by_name = {a["name"]: a for a in payload.get("assets", [])}
    for local_path in asset_paths:
        remote = remote_by_name.get(local_path.name)
        if remote is None:
            problems.append(f"missing asset {local_path.name!r}")
            continue
        local_size = local_path.stat().st_size
        remote_size = remote.get("size")
        if remote_size != local_size:
            problems.append(
                f"asset {local_path.name!r} size mismatch: local {local_size} bytes, "
                f"GitHub reports {remote_size} bytes"
            )
    if problems:
        deleted = delete_draft_release(repository=repository, tag=tag)
        cleanup = (
            "draft deleted, no tag created"
            if deleted
            else "DRAFT DELETE FAILED -- remove it by hand"
        )
        raise PublishError(
            f"draft release {tag} failed asset verification ({cleanup}): " + "; ".join(problems)
        )


def undraft_release(*, repository: str, tag: str) -> None:
    """Flip the verified draft to a public prerelease. This is the single
    step that creates the public tag, atomically with the release.

    On failure the draft is deliberately NOT deleted: un-draft may have
    partially applied server-side and deleting could remove a now-public
    release. Report loudly instead.
    """

    proc = run_gh(["release", "edit", tag, "-R", repository, "--draft=false"])
    if proc.returncode != 0:
        raise PublishError(
            f"gh release edit --draft=false failed for {tag}; the verified DRAFT "
            "is left in place (not deleted, since un-draft may have partially "
            "applied). Before choosing a recovery, run "
            f"`gh release view {tag} -R {repository} --json isDraft,url` to learn "
            "whether the release actually went public; then either publish or "
            f"delete it by hand: {_gh_error(proc)}"
        )


# ---------------------------------------------------------------------------
# (g) release-truth.yaml update
# ---------------------------------------------------------------------------
def update_release_truth(*, truth_path: Path, tag: str, status: str, notes: str) -> str:
    """Add a new entry for tag with the given status; flip the previous
    `current` entry to `superseded` (naming this tag) if status == current.

    Returns a human-readable diff-like summary of the edit (never mutates
    silently).
    """

    if status not in ("current", "staging"):
        raise PublishError(f"--truth-status must be 'current' or 'staging', got {status!r}")

    text = truth_path.read_text(encoding="utf-8")
    summary_lines = [f"docs/releases/release-truth.yaml edits for {tag} (status={status}):"]

    new_entry_lines = [
        f"  - tag: {tag}",
        f"    status: {status}",
        "    notes: >-",
        f"      {notes}",
    ]
    entries_marker = "\nentries:\n"
    idx = text.index(entries_marker)
    insert_at = idx + len(entries_marker)
    text = text[:insert_at] + "\n".join(new_entry_lines) + "\n" + text[insert_at:]
    summary_lines.append(f"  + added entry: tag={tag} status={status}")

    if status == "current":
        current_match = re.search(r"^current:\s*(\S+)\s*$", text, re.MULTILINE)
        if not current_match:
            raise PublishError("release-truth.yaml has no top-level 'current:' field.")
        previous_current_tag = current_match.group(1)
        if previous_current_tag != tag:
            text = re.sub(
                r"^current:\s*\S+\s*$",
                f"current: {tag}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
            summary_lines.append(f"  ~ current: {previous_current_tag} -> {tag}")

            entry_pattern = re.compile(
                rf"(- tag: {re.escape(previous_current_tag)}\n(?:.*\n)*?    status: )current(\s*\n)"
            )

            def _flip(match: re.Match[str]) -> str:
                return f"{match.group(1)}superseded{match.group(2)}    superseded_by: {tag}\n"

            new_text, count = entry_pattern.subn(_flip, text, count=1)
            if count != 1:
                raise PublishError(
                    f"could not locate the previous current entry {previous_current_tag!r} "
                    "in release-truth.yaml to flip it to superseded."
                )
            text = new_text
            summary_lines.append(
                f"  ~ {previous_current_tag}: status current -> superseded (superseded_by: {tag})"
            )

    truth_path.write_text(text, encoding="utf-8", newline="\n")
    return "\n".join(summary_lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit-dir", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--build-run-id", required=True)
    parser.add_argument("--gate-a-run-id", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--truth-status", required=True, choices=("current", "staging"))
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _run(args)
    except PublishError as exc:
        print(f"publish_beta_candidate: REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


def _run(args: argparse.Namespace) -> None:
    repo_root: Path = args.repo_root
    kit_dir: Path = args.kit_dir
    tag: str = args.tag
    source_sha: str = args.source_sha
    repository: str = args.repository

    print("publish_beta_candidate: verifying gh authentication")
    verify_gh_auth()

    print(f"publish_beta_candidate: verifying kit layout at {kit_dir}")
    setup, packs = verify_layout(kit_dir)

    print("publish_beta_candidate: verifying version identity")
    version = verify_version_identity(setup, tag)
    print(f"publish_beta_candidate: version {version} agrees (setup.exe, source tree, tag)")

    print("publish_beta_candidate: verifying Authenticode signature")
    verify_signature(setup)
    print("publish_beta_candidate: signature Valid")

    print(f"publish_beta_candidate: downloading Gate A verdicts for run {args.gate_a_run_id}")
    gate_a_dir = repo_root / "artifacts" / "release" / tag / "gate-a-verdicts"
    verdicts = download_gate_a_verdicts(
        repository=repository,
        gate_a_run_id=args.gate_a_run_id,
        build_run_id=args.build_run_id,
        dest_dir=gate_a_dir,
    )
    verify_gate_a_verdicts(verdicts, source_sha=source_sha)
    print("publish_beta_candidate: Gate A PASS on all three lanes, source_sha agrees")

    print("publish_beta_candidate: hashing assets and building manifest")
    all_files = [setup, *packs]
    sha256sums = build_sha256sums(all_files)
    sidecar = build_sidecar(setup, signed=True)
    sidecar_filename = f"{setup.name}{SIDECAR_SUFFIX}"

    # SHA256SUMS.txt and the sidecar are release assets too. Write them to the
    # local out_dir FIRST (local files only -- no remote state) so the asset
    # table below can carry their real bytes/hash, and so the pre-flight size
    # check covers the complete asset set. Same in dry-run and live mode.
    out_dir = repo_root / "artifacts" / "release" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = out_dir / sidecar_filename
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8", newline="\n")
    sha256sums_path = out_dir / SHA256SUMS_ASSET_NAME
    sha256sums_path.write_text(sha256sums, encoding="utf-8", newline="\n")
    asset_paths = [setup, *packs, sha256sums_path, sidecar_path]

    # Pre-flight: every asset under GitHub's 2 GiB cap, full set listed --
    # BEFORE any remote mutation, in dry-run and live mode alike.
    preflight_asset_limits(asset_paths)

    changelog_path = repo_root / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    asset_table = [
        {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in asset_paths
    ]
    notes = render_notes(
        tag=tag,
        source_sha=source_sha,
        repository=repository,
        build_run_id=args.build_run_id,
        gate_a_run_id=args.gate_a_run_id,
        verdicts=verdicts,
        changelog_text=changelog_text,
        assets=asset_table,
    )

    notes_file = out_dir / "RELEASE-NOTES.md"
    notes_file.write_text(notes, encoding="utf-8", newline="\n")
    title = f"CivicCast {tag} (Beta Candidate)"
    asset_names = " ".join(p.name for p in asset_paths)

    if args.dry_run:
        print(f"publish_beta_candidate: DRY RUN -- artifacts written to {out_dir}")
        print(
            "publish_beta_candidate: DRY RUN -- would publish, in this order "
            "(no tag is ever pushed by hand; un-draft creates it atomically):"
        )
        print(
            f"  1. gh release create {tag} -R {repository} --draft --target {source_sha} "
            f"--prerelease --title '{title}' --notes-file {notes_file} {asset_names}"
        )
        print(
            f"  2. gh release view {tag} -R {repository} --json assets,isDraft  "
            "(verify every asset name + size; on mismatch: gh release delete "
            f"{tag} --yes, refuse)"
        )
        print(
            f"  3. gh release edit {tag} -R {repository} --draft=false  "
            "(creates the public tag with the release)"
        )
        print("publish_beta_candidate: DRY RUN -- would update release-truth.yaml:")
        truth_summary = _dry_run_truth_summary(
            repo_root=repo_root, tag=tag, status=args.truth_status
        )
        print(truth_summary)
        print("publish_beta_candidate: DRY RUN complete. No GitHub or git remote state touched.")
        return

    # ---- Live path (never exercised by this agent against real GitHub; see
    # the module docstring and the task's Testing boundary). Order is
    # draft -> verify -> un-draft so that no public tag can exist without its
    # verified release: a draft has no tag, and un-draft creates the tag
    # atomically with the release. ----
    print(f"publish_beta_candidate: creating DRAFT release {tag} targeting {source_sha}")
    create_draft_release(
        repository=repository,
        tag=tag,
        source_sha=source_sha,
        title=title,
        notes_file=notes_file,
        asset_paths=asset_paths,
    )

    print("publish_beta_candidate: verifying draft assets (name + size)")
    verify_draft_assets(repository=repository, tag=tag, asset_paths=asset_paths)
    print("publish_beta_candidate: all assets present on the draft with matching sizes")

    print(f"publish_beta_candidate: un-drafting {tag} (creates the public tag + prerelease)")
    undraft_release(repository=repository, tag=tag)

    truth_path = repo_root / "docs" / "releases" / "release-truth.yaml"
    truth_notes = (
        f"Published by publish_beta_candidate.py, source {source_sha}, "
        f"build run {args.build_run_id}, Gate A run {args.gate_a_run_id} "
        "(all three lanes PASS)."
    )
    summary = update_release_truth(
        truth_path=truth_path, tag=tag, status=args.truth_status, notes=truth_notes
    )
    print(summary)
    print(f"publish_beta_candidate: DONE. {tag} published as a GitHub prerelease.")


def _dry_run_truth_summary(*, repo_root: Path, tag: str, status: str) -> str:
    """Render what update_release_truth() would do, without writing it.

    Reads the real file, applies the edit in memory only, and reports the
    same summary update_release_truth() would print -- so a dry run shows
    its full intended effect without mutating anything.
    """

    import tempfile

    truth_path = repo_root / "docs" / "releases" / "release-truth.yaml"
    original = truth_path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "release-truth.yaml"
        scratch.write_text(original, encoding="utf-8")
        return update_release_truth(
            truth_path=scratch,
            tag=tag,
            status=status,
            notes=f"(dry run) would be published for {tag}.",
        )


if __name__ == "__main__":
    sys.exit(main())
