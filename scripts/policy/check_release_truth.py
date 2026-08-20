# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Release-truth checker: validate release claims against the authored manifest.

READ-ONLY DRIFT ALARM, NOT A GATE. This tool reports mismatches between
``docs/releases/release-truth.yaml`` (the sole authored source for release
state), live GitHub release state, and human-facing prose. It blocks nothing,
holds no release authority, and is safe to run from anywhere (native-Windows
program charter section 3; deployed as an external observer in
civiccast-audit-control).

Usage:
    python scripts/policy/check_release_truth.py --manifest docs/releases/release-truth.yaml \
        [--live | --releases-json FILE] [--readme FILE ...]

Checks:
  manifest  exactly one `current`; statuses from the allowed set; every
            `withdrawn` or `superseded` entry names an existing entry in
            `superseded_by`; any entry that supplies `superseded_by` at all
            must reference an existing entry tag; `current` field matches the
            entry marked current; no duplicate tags.
  live      every entry's tag exists as a GitHub release; withdrawn entries'
            release title or body carries the WITHDRAWN marker; the current
            entry's release exists, is not a draft, and is not marked
            WITHDRAWN; any live release tag neither listed nor matched by
            `historical_unlisted_patterns` is drift (a new release must get a
            manifest entry).
  readme    each named file must mention the current tag; any withdrawn tag it
            mentions must have "withdrawn" or "supersede" within 200
            characters of the mention.

Exit 0 = no drift. Exit 1 = drift (one `DRIFT:` line per finding). Exit 2 =
checker could not run (bad manifest/network); failure to check is reported,
never inferred as a pass.

This checker's own drift-detection is verified: every drift class above,
including an unlisted live GitHub release carrying no manifest entry, is
covered by a red pytest case in tests/policy/test_release_truth.py, run in
CI's `test` job at every PR head and machine-checked by the claims-evidence
verifier (# claim:ws1-release-truth-checker).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ALLOWED_STATUSES = {"current", "staging", "withdrawn", "superseded", "historical"}
# Statuses that describe a release as no longer the live recommendation MUST
# name the entry that replaced them. "historical" entries predate the
# manifest's superseded_by convention and are exempt (see CONSTRAINT note in
# release-truth.yaml's header).
REQUIRES_SUCCESSOR = {"withdrawn", "superseded"}
# Case-SENSITIVE by design: the withdrawal convention is an uppercase marker in
# the release title or the caution block at the top of the body (like rc13's
# "— WITHDRAWN"). Lowercase prose such as "supersedes the withdrawn rc13" in a
# healthy release must not count (first live run false-positived on exactly that).
WITHDRAWN_MARKER = re.compile(r"\bWITHDRAWN\b")
BODY_MARKER_WINDOW = 300
NEARBY = 200


def _withdrawn_marked(release: dict) -> bool:
    name = release.get("name") or ""
    body_head = (release.get("body") or "")[:BODY_MARKER_WINDOW]
    return bool(WITHDRAWN_MARKER.search(name) or WITHDRAWN_MARKER.search(body_head))


class ManifestShapeError(Exception):
    """Manifest fails structural/type validation before drift checks can run.

    Distinct from a drift finding: this means the checker cannot reliably
    interpret the manifest at all (wrong YAML shape, unparsable regex), so it
    must fail setup (exit 2), never silently skip or misreport as clean.
    """


def fail_setup(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


def load_manifest(path: Path) -> tuple[dict, list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestShapeError(
            f"manifest must be a YAML mapping at the top level, got {type(data).__name__}"
        )

    entries = data.get("entries") or []
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ManifestShapeError("manifest 'entries' must be a list of mappings")

    patterns_raw = data.get("historical_unlisted_patterns") or []
    if not isinstance(patterns_raw, list):
        raise ManifestShapeError(
            "manifest 'historical_unlisted_patterns' must be a list of regex strings"
        )
    for pattern in patterns_raw:
        if not isinstance(pattern, str):
            raise ManifestShapeError(
                "manifest 'historical_unlisted_patterns' entries must be strings, "
                f"got {type(pattern).__name__}: {pattern!r}"
            )
        try:
            re.compile(pattern)
        except re.error as error:
            raise ManifestShapeError(
                f"invalid regex in historical_unlisted_patterns: {pattern!r}: {error}"
            ) from error

    # `tag` is hashed (duplicate detection), indexed (current lookup, live
    # check), and interpolated into messages — it must be a scalar string on
    # every entry before any of that runs, or the checker tracebacks instead
    # of failing setup.
    for entry in entries:
        tag = entry.get("tag")
        if not isinstance(tag, str) or not tag:
            raise ManifestShapeError(
                f"manifest entry {entry!r} must have a non-empty string 'tag' "
                f"(got {tag!r})"
            )

    problems: list[str] = []
    tags = [e.get("tag") for e in entries]
    if len(tags) != len(set(tags)):
        problems.append("manifest: duplicate tags in entries")
    for entry in entries:
        status = entry.get("status")
        tag = entry.get("tag")
        if status not in ALLOWED_STATUSES:
            problems.append(f"manifest: {tag}: invalid status {status!r}")
        successor = entry.get("superseded_by")
        if successor is not None and successor not in tags:
            problems.append(
                f"manifest: {tag}: superseded_by {successor!r} does not name an "
                "existing entry tag"
            )
        if status in REQUIRES_SUCCESSOR and not successor:
            problems.append(
                f"manifest: {status} entry {tag} must name a superseded_by entry "
                f"(got {successor!r})"
            )
    currents = [e["tag"] for e in entries if e.get("status") == "current"]
    if len(currents) != 1:
        problems.append(f"manifest: exactly one current entry required, found {currents}")
    elif data.get("current") != currents[0]:
        problems.append(
            f"manifest: top-level current {data.get('current')!r} != "
            f"current-status entry {currents[0]!r}"
        )
    return data, problems


def fetch_releases(repo: str) -> list[dict]:
    releases: list[dict] = []
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "civiccast-release-truth-checker",
    }
    # Authenticate when a token is available (workflow-provided GITHUB_TOKEN,
    # or a developer's GH_TOKEN) so live checks aren't starved by the
    # unauthenticated GitHub API rate limit. Works fine without one.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for page in (1, 2, 3):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            batch = json.load(response)
        releases.extend(batch)
        if len(batch) < 100:
            break
    return releases


def check_live(manifest: dict, releases: list[dict]) -> list[str]:
    drift: list[str] = []
    by_tag = {r.get("tag_name"): r for r in releases}
    patterns = [re.compile(p) for p in manifest.get("historical_unlisted_patterns") or []]
    entries = {e["tag"]: e for e in (manifest.get("entries") or [])}

    for tag, entry in entries.items():
        release = by_tag.get(tag)
        if release is None:
            drift.append(f"DRIFT: manifest entry {tag} has no live GitHub release")
            continue
        if entry["status"] == "withdrawn" and not _withdrawn_marked(release):
            drift.append(
                f"DRIFT: {tag} is withdrawn in the manifest but its live release "
                "carries no WITHDRAWN marker (uppercase, in title or body head)"
            )
        if entry["status"] == "current":
            if release.get("draft"):
                drift.append(f"DRIFT: current release {tag} is still a draft")
            if _withdrawn_marked(release):
                drift.append(f"DRIFT: current release {tag} is marked WITHDRAWN live")

    for tag in by_tag:
        if tag in entries or any(p.search(tag or "") for p in patterns):
            continue
        drift.append(
            f"DRIFT: live release {tag} has no manifest entry (new releases "
            "require a release-truth entry)"
        )
    return drift


def check_readme(manifest: dict, path: Path) -> list[str]:
    drift: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    current = manifest.get("current") or ""
    if current not in text:
        drift.append(f"DRIFT: {path.name} never mentions the current release {current}")
    for entry in manifest.get("entries") or []:
        if entry.get("status") != "withdrawn":
            continue
        tag = entry["tag"]
        for match in re.finditer(re.escape(tag), text):
            window = text[max(0, match.start() - NEARBY): match.end() + NEARBY]
            if not re.search(r"withdrawn|supersede", window, re.IGNORECASE):
                drift.append(
                    f"DRIFT: {path.name} mentions withdrawn {tag} at offset "
                    f"{match.start()} without withdrawn/supersede context nearby"
                )
                break
    return drift


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--live", action="store_true", help="fetch live GitHub releases")
    parser.add_argument("--releases-json", type=Path, help="offline releases fixture")
    parser.add_argument("--readme", type=Path, action="append", default=[])
    args = parser.parse_args()

    try:
        manifest, problems = load_manifest(args.manifest)
    except ManifestShapeError as error:
        return fail_setup(str(error))
    except (OSError, yaml.YAMLError) as error:
        return fail_setup(f"cannot load manifest: {error}")
    drift = [f"DRIFT: {p}" if not p.startswith("DRIFT") else p for p in problems]

    releases: list[dict] | None = None
    if args.releases_json:
        try:
            raw_releases = json.loads(args.releases_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return fail_setup(f"cannot load releases fixture: {error}")
        if not isinstance(raw_releases, list) or not all(
            isinstance(r, dict) for r in raw_releases
        ):
            return fail_setup("releases fixture must be a JSON list of release objects")
        releases = raw_releases
    elif args.live:
        try:
            releases = fetch_releases(manifest.get("repository", ""))
        except urllib.error.HTTPError as error:
            if error.code == 403:
                return fail_setup(
                    "GitHub API rate limit hit (HTTP 403) while fetching live releases; "
                    "this is a cannot-check condition, not drift — set GITHUB_TOKEN (or "
                    "GH_TOKEN) to authenticate and retry"
                )
            return fail_setup(f"cannot fetch live releases: {error}")
        except OSError as error:
            return fail_setup(f"cannot fetch live releases: {error}")
    if releases is not None and not problems:
        drift.extend(check_live(manifest, releases))

    for readme in args.readme:
        try:
            drift.extend(check_readme(manifest, readme))
        except OSError as error:
            return fail_setup(f"cannot read {readme}: {error}")

    for line in drift:
        print(line)
    print(f"release-truth: {f'DRIFT ({len(drift)} finding(s))' if drift else 'PASS'}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
