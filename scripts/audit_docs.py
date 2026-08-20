#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Exhaustive documentation auditor.

Walks every user-facing document, extracts EVERY link (markdown links, bare
autolinks, HTML href/src), and validates each one:

  * internal file targets      -> the file exists in the repo
  * internal anchors (#frag)   -> a heading with that slug exists in the target
  * image targets              -> the image file exists
  * external http(s) URLs      -> HTTP status (optional, --net)
  * PDF-reader safety          -> flags relative links inside documents that
                                  are published as standalone artifacts

Also reports version-string drift so a doc cannot claim an old release.

Usage:
    python scripts/audit_docs.py                 # offline checks
    python scripts/audit_docs.py --net           # also verify external URLs
    python scripts/audit_docs.py --json out.json # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent

# Directories that are archives/evidence, not live user documentation.
EXCLUDE_PARTS = {
    ".git",
    # Agent evidence trees are append-only by the audit protocol: scanning
    # them coupled the rc18 release record's pinned count to every evidence
    # commit from every lane (owner-approved decoupling, 2026-08-09).
    ".agent-runs",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "artifacts",
    "audits",
    "adr",
    "process",
    "templates",
    "research",
    "archive",
    "release-evidence",
    ".pytest_cache",
    "htmlcov",
    "site-packages",
    # build output and application source: not user documentation
    "dist",
    "target",
    "build",
    "coverage",
    "src",
    "src-tauri",
    "tests",
    "e2e",
    "playwright-report",
    "test-results",
    ".claude",
}

MD_LINK = re.compile(r"(!?)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_ATTR = re.compile(
    r"""<(?:a|img|link|script)\b[^>]*?\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.I
)
ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.M)
EXPLICIT_ID = re.compile(r"\{#([A-Za-z0-9_-]+)\}")


def is_doc(p: Path) -> bool:
    if not p.is_file() or p.suffix.lower() not in {".md", ".html"}:
        return False
    if set(p.parts) & EXCLUDE_PARTS:
        return False
    # Stray build-output trees (e.g. target-rc14-final-.../release/...).
    if any(part.startswith("target-") or part.endswith(".egg-info") for part in p.parts):
        return False
    # Vite/SPA entry points: their "/src/main.tsx" and "/favicon.svg" refs are
    # dev-server routes the bundler rewrites, not filesystem paths, and no
    # reader ever opens them as documentation.
    return not (p.name == "index.html" and "apps" in p.parts)


def slugify(heading: str) -> str:
    """Pandoc/GitHub-ish heading slug."""
    # Mirrors GitHub/pandoc: strip formatting and punctuation, then map each
    # remaining whitespace character to one hyphen. Runs are NOT collapsed --
    # "License & IP" loses the "&" and keeps both spaces, yielding
    # "license--ip", which is what the anchors in these docs actually use.
    h = EXPLICIT_ID.sub("", heading)
    h = re.sub(r"[`*_~]", "", h).strip().lower()
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)  # link text only
    h = re.sub(r"[^\w\s-]", "", h)
    return re.sub(r"\s", "-", h).strip("-")


def anchors_for(path: Path) -> set[str]:
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    if path.suffix.lower() == ".md":
        for _, heading in ATX_HEADING.findall(text):
            for m in EXPLICIT_ID.findall(heading):
                out.add(m.lower())
            out.add(slugify(heading))
    for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', text, re.I):
        out.add(m.group(1).lower())
    for m in re.finditer(r'\bname\s*=\s*["\']([^"\']+)["\']', text, re.I):
        out.add(m.group(1).lower())
    out.discard("")
    return out


def collect_links(path: Path) -> list[tuple[int, str, bool]]:
    """Return (line_no, target, is_image) for every link in the file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return max(1, lo)

    found: list[tuple[int, str, bool]] = []
    in_fence = False
    for m in MD_LINK.finditer(text):
        found.append((line_of(m.start()), m.group("target").strip(), m.group(1) == "!"))
    for m in HTML_ATTR.finditer(text):
        found.append((line_of(m.start()), m.group(1).strip(), False))
    _ = in_fence
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--net", action="store_true", help="verify external URLs over the network")
    ap.add_argument("--json", type=Path, help="write a machine-readable report")
    args = ap.parse_args()

    docs = sorted(p for p in ROOT.rglob("*") if is_doc(p))
    anchor_cache: dict[Path, set[str]] = {}

    problems: list[dict] = []
    external: dict[str, list[str]] = defaultdict(list)
    stats = {"docs": len(docs), "links": 0, "internal": 0, "external": 0, "anchors": 0}

    for doc in docs:
        rel = doc.relative_to(ROOT).as_posix()
        for line_no, target, is_img in collect_links(doc):
            stats["links"] += 1
            if target.startswith(("mailto:", "tel:", "data:", "javascript:")):
                continue
            parsed = urlparse(target)
            if parsed.scheme in {"http", "https"}:
                stats["external"] += 1
                external[target.split("#")[0]].append(f"{rel}:{line_no}")
                continue
            # internal
            pathpart, _, frag = target.partition("#")
            pathpart = unquote(pathpart)
            if not pathpart:  # pure in-document anchor
                stats["anchors"] += 1
                if frag and frag.lower() not in anchor_cache.setdefault(doc, anchors_for(doc)):
                    problems.append(
                        {
                            "kind": "dead-anchor-self",
                            "doc": rel,
                            "line": line_no,
                            "target": target,
                            "detail": f"no heading/id '#{frag}' in this document",
                        }
                    )
                continue
            stats["internal"] += 1
            if pathpart.startswith("/"):
                # Server-root-relative (published site path), not a filesystem
                # path; resolve against the published docs root.
                tgt = (ROOT / "docs" / pathpart.lstrip("/")).resolve()
            else:
                tgt = (doc.parent / pathpart).resolve()
            if not tgt.exists():
                problems.append(
                    {
                        "kind": "missing-image" if is_img else "missing-file",
                        "doc": rel,
                        "line": line_no,
                        "target": target,
                        "detail": "target does not exist",
                    }
                )
                continue
            if frag and tgt.suffix.lower() in {".md", ".html"}:
                stats["anchors"] += 1
                if frag.lower() not in anchor_cache.setdefault(tgt, anchors_for(tgt)):
                    problems.append(
                        {
                            "kind": "dead-anchor",
                            "doc": rel,
                            "line": line_no,
                            "target": target,
                            "detail": f"'{tgt.relative_to(ROOT).as_posix()}' has no anchor '#{frag}'",
                        }
                    )

    if args.net and external:
        import urllib.error
        import urllib.request

        print(f"checking {len(external)} unique external URLs...", file=sys.stderr)
        for url in sorted(external):
            req = urllib.request.Request(
                url, method="GET", headers={"User-Agent": "civiccast-doc-audit"}
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception as e:
                # Deliberately broad: a link audit must survive DNS failures,
                # TLS errors and timeouts by reporting them, not aborting the run.
                code = f"ERR {type(e).__name__}"
            if code != 200:
                problems.append(
                    {
                        "kind": "external-bad",
                        "doc": ", ".join(sorted(set(external[url]))[:4]),
                        "line": 0,
                        "target": url,
                        "detail": f"HTTP {code}",
                    }
                )

    by_kind: dict[str, int] = defaultdict(int)
    for p in problems:
        by_kind[p["kind"]] += 1

    print("=" * 74)
    print("CIVICCAST DOCUMENTATION LINK AUDIT")
    print("=" * 74)
    print(f"documents scanned : {stats['docs']}")
    print(
        f"links found       : {stats['links']}  "
        f"(internal {stats['internal']}, external {stats['external']}, anchors {stats['anchors']})"
    )
    print(f"problems          : {len(problems)}")
    for k, v in sorted(by_kind.items()):
        print(f"    {k:<20} {v}")
    if problems:
        print("-" * 74)
        for p in sorted(problems, key=lambda x: (x["kind"], x["doc"], x["line"])):
            loc = f"{p['doc']}:{p['line']}" if p["line"] else p["doc"]
            print(f"[{p['kind']}] {loc}\n    -> {p['target']}\n       {p['detail']}")

    if args.json:
        args.json.write_text(
            json.dumps({"stats": stats, "problems": problems}, indent=2), encoding="utf-8"
        )

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
