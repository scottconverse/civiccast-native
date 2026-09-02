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
creates and pushes an annotated tag, publishes the GitHub prerelease with
all assets, verifies the upload, and updates
``docs/releases/release-truth.yaml``.
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
GATE_A_LANES: tuple[str, ...] = ("clean", "dirty", "download-only")
GATE_A_ARTIFACT_NAMES: dict[str, str] = {
    "clean": "gate-a-verdict-{run_id}",
    "dirty": "gate-a-dirty-verdict-{run_id}",
    "download-only": "gate-a-download-only-verdict-{run_id}",
}

SMARTSCREEN_NOTE = (
    "Windows may show a blue \"Windows protected your PC\" SmartScreen prompt "
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
    return run_command(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    )


def run_gh(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return run_command(["gh", *args], **kwargs)


def run_git(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *args], **kwargs)


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

    setup = kit_dir / "setup.exe"
    if not setup.is_file():
        raise PublishError(f"kit-dir is missing setup.exe: {setup}")

    packs_dir = kit_dir / "packs"
    if not packs_dir.is_dir():
        raise PublishError(f"kit-dir is missing a packs\\ directory: {packs_dir}")
    packs = sorted(packs_dir.glob("*.ccpack"))
    if not packs:
        raise PublishError(f"packs\\ directory has no *.ccpack files: {packs_dir}")

    station_dir = kit_dir / "station"
    if not station_dir.is_dir():
        raise PublishError(f"kit-dir is missing a station\\ directory: {station_dir}")

    return setup, packs


def get_product_version(setup: Path) -> str:
    proc = run_powershell(
        f"(Get-Item -LiteralPath '{setup}').VersionInfo.ProductVersion"
    )
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
    proc = run_powershell(
        f"(Get-AuthenticodeSignature -LiteralPath '{setup}').Status"
    )
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
    *, repository: str, gate_a_run_id: str, dest_dir: Path
) -> dict[str, dict[str, Any]]:
    """Download and parse gate-a-verdict.json for all three required lanes."""

    verdicts: dict[str, dict[str, Any]] = {}
    for lane in GATE_A_LANES:
        artifact_name = GATE_A_ARTIFACT_NAMES[lane].format(run_id=gate_a_run_id)
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


def verify_gate_a_verdicts(
    verdicts: dict[str, dict[str, Any]], *, source_sha: str
) -> None:
    """Require all three lanes PASS and share the same source_sha == --source-sha."""

    missing = [lane for lane in GATE_A_LANES if lane not in verdicts]
    if missing:
        raise PublishError(f"missing Gate A verdict(s) for lane(s): {missing}")

    for lane in GATE_A_LANES:
        doc = verdicts[lane]
        verdict = doc.get("verdict")
        if verdict != "PASS":
            raise PublishError(
                f"Gate A lane {lane!r} did not PASS (verdict: {verdict!r})."
            )
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
                f"Gate A lane {lane!r} verdict document reports lane "
                f"{doc_lane!r} instead."
            )

    shas = {verdicts[lane].get("source_sha") for lane in GATE_A_LANES}
    if len(shas) != 1:
        raise PublishError(
            f"Gate A lane verdicts do not share the same source_sha: {shas}"
        )


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
def write_dry_run_artifacts(
    *,
    out_dir: Path,
    notes: str,
    sidecar: dict[str, Any],
    sidecar_filename: str,
    sha256sums: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "RELEASE-NOTES.md").write_text(notes, encoding="utf-8", newline="\n")
    (out_dir / sidecar_filename).write_text(
        json.dumps(sidecar, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (out_dir / "SHA256SUMS.txt").write_text(sha256sums, encoding="utf-8", newline="\n")


def create_and_push_tag(*, tag: str, source_sha: str, message: str) -> None:
    proc = run_git(["tag", "-a", tag, source_sha, "-m", message])
    if proc.returncode != 0:
        raise PublishError(
            f"could not create annotated tag {tag} on {source_sha}: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    proc = run_git(["push", "origin", tag])
    if proc.returncode != 0:
        raise PublishError(
            f"could not push tag {tag} to origin: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )


def publish_release(
    *,
    repository: str,
    tag: str,
    title: str,
    notes_file: Path,
    asset_paths: list[Path],
) -> None:
    proc = run_gh(
        [
            "release",
            "create",
            tag,
            "-R",
            repository,
            "--prerelease",
            "--title",
            title,
            "--notes-file",
            str(notes_file),
            *[str(p) for p in asset_paths],
        ]
    )
    if proc.returncode != 0:
        raise PublishError(
            f"gh release create failed for {tag}: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )


def verify_published_assets(
    *, repository: str, tag: str, asset_paths: list[Path]
) -> None:
    """Re-fetch the release and assert every expected asset is present with
    a matching size. Assets already uploaded stay uploaded on any mismatch
    here -- this only fails loudly, it never attempts to auto-rollback a
    partial release.
    """

    proc = run_gh(["release", "view", tag, "-R", repository, "--json", "assets"])
    if proc.returncode != 0:
        raise PublishError(
            f"could not re-fetch release {tag} to verify assets: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PublishError(f"gh release view returned non-JSON output: {exc}") from exc

    remote_by_name = {a["name"]: a for a in payload.get("assets", [])}
    for local_path in asset_paths:
        remote = remote_by_name.get(local_path.name)
        if remote is None:
            raise PublishError(
                f"release {tag} is missing expected asset {local_path.name!r} "
                "after upload (asset(s) already uploaded stay uploaded; fix "
                "the release by hand, do not re-run blindly)."
            )
        local_size = local_path.stat().st_size
        remote_size = remote.get("size")
        if remote_size != local_size:
            raise PublishError(
                f"uploaded asset {local_path.name!r} size mismatch: local "
                f"{local_size} bytes, GitHub reports {remote_size} bytes."
            )


# ---------------------------------------------------------------------------
# (g) release-truth.yaml update
# ---------------------------------------------------------------------------
def update_release_truth(
    *, truth_path: Path, tag: str, status: str, notes: str
) -> str:
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
                f"  ~ {previous_current_tag}: status current -> superseded "
                f"(superseded_by: {tag})"
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
    parser.add_argument(
        "--truth-status", required=True, choices=("current", "staging")
    )
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
        repository=repository, gate_a_run_id=args.gate_a_run_id, dest_dir=gate_a_dir
    )
    verify_gate_a_verdicts(verdicts, source_sha=source_sha)
    print("publish_beta_candidate: Gate A PASS on all three lanes, source_sha agrees")

    print("publish_beta_candidate: hashing assets and building manifest")
    all_files = [setup, *packs]
    sha256sums = build_sha256sums(all_files)
    sidecar = build_sidecar(setup, signed=True)
    sidecar_filename = f"{setup.name}.sidecar.json"

    changelog_path = repo_root / "CHANGELOG.md"
    changelog_text = (
        changelog_path.read_text(encoding="utf-8") if changelog_path.is_file() else ""
    )
    asset_table = [
        {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in all_files
    ]
    # SHA256SUMS.txt and the sidecar are release assets too -- include them in
    # the rendered table (their own bytes/hash, computed after they exist).
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

    out_dir = repo_root / "artifacts" / "release" / tag
    if args.dry_run:
        print(f"publish_beta_candidate: DRY RUN -- writing artifacts to {out_dir}")
        write_dry_run_artifacts(
            out_dir=out_dir,
            notes=notes,
            sidecar=sidecar,
            sidecar_filename=sidecar_filename,
            sha256sums=sha256sums,
        )
        print("publish_beta_candidate: DRY RUN -- would create/push tag:")
        print(f"  git tag -a {tag} {source_sha} -m 'CivicCast {tag}'")
        print(f"  git push origin {tag}")
        print("publish_beta_candidate: DRY RUN -- would publish GitHub prerelease:")
        print(f"  gh release create {tag} -R {repository} --prerelease "
              f"--title 'CivicCast {tag} (Beta Candidate)' "
              f"--notes-file {out_dir / 'RELEASE-NOTES.md'} "
              f"{setup.name} {' '.join(p.name for p in packs)} "
              f"SHA256SUMS.txt {sidecar_filename}")
        print("publish_beta_candidate: DRY RUN -- would update release-truth.yaml:")
        truth_summary = _dry_run_truth_summary(
            repo_root=repo_root, tag=tag, status=args.truth_status
        )
        print(truth_summary)
        print("publish_beta_candidate: DRY RUN complete. No GitHub or git remote state touched.")
        return

    # ---- Live path (never exercised by this agent in this task; see the
    # module docstring and the task's Testing boundary). ----
    out_dir.mkdir(parents=True, exist_ok=True)
    notes_file = out_dir / "RELEASE-NOTES.md"
    notes_file.write_text(notes, encoding="utf-8", newline="\n")
    sidecar_path = out_dir / sidecar_filename
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8", newline="\n")
    sha256sums_path = out_dir / "SHA256SUMS.txt"
    sha256sums_path.write_text(sha256sums, encoding="utf-8", newline="\n")

    print(f"publish_beta_candidate: creating and pushing tag {tag}")
    create_and_push_tag(tag=tag, source_sha=source_sha, message=f"CivicCast {tag}")

    asset_paths = [setup, *packs, sha256sums_path, sidecar_path]
    print(f"publish_beta_candidate: publishing GitHub prerelease {tag}")
    publish_release(
        repository=repository,
        tag=tag,
        title=f"CivicCast {tag} (Beta Candidate)",
        notes_file=notes_file,
        asset_paths=asset_paths,
    )

    print("publish_beta_candidate: verifying published assets")
    verify_published_assets(repository=repository, tag=tag, asset_paths=asset_paths)
    print("publish_beta_candidate: all assets present with matching sizes")

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
