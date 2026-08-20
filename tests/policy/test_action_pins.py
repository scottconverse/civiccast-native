# SPDX-License-Identifier: Apache-2.0
"""Guard the action-pin resolution check (gate-civiccast C3).

The check exists because actions/download-artifact@v7.0.1 (a nonexistent tag)
shipped in rc8 and only failed on a real tag build. These tests prove the
extractor is correct and — critically — that a nonexistent ref IS flagged (so
the guard can actually go red), without hitting the network.
"""

from __future__ import annotations

from scripts.policy.check_action_pins import (
    Pin,
    check_action_pins,
    collect_pins,
    iter_action_pins,
)

SAMPLE = """
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v7.0.1
      - name: local
        uses: ./.github/actions/thing
      - uses: docker://alpine:3.20
      - uses: owner/repo/sub/path@v1.2.3
      - uses: dtolnay/rust-toolchain@stable
"""


def test_iter_action_pins_extracts_external_only():
    pins = iter_action_pins(SAMPLE, "sample.yml")
    got = {(p.action, p.ref) for p in pins}
    assert ("actions/checkout", "v4") in got
    assert ("actions/download-artifact", "v7.0.1") in got
    assert ("owner/repo/sub/path", "v1.2.3") in got
    assert ("dtolnay/rust-toolchain", "stable") in got
    # local composite action and docker image are skipped
    assert all(not p.action.startswith(".") for p in pins)
    assert all(not p.action.startswith("docker:") for p in pins)


def test_repo_drops_action_subpath():
    assert Pin("owner/repo/sub/path", "v1", "f", 1).repo == "owner/repo"
    assert Pin("actions/checkout", "v4", "f", 1).repo == "actions/checkout"


def test_nonexistent_ref_is_flagged(tmp_path):
    # Simulate a workflow dir with the exact rc8 defect.
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "release.yml").write_text(
        "jobs:\n  j:\n    steps:\n"
        "      - uses: actions/download-artifact@v7.0.1\n"
        "      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )

    def resolver(repo: str, ref: str) -> bool:
        # download-artifact has no v7.0.1; everything else resolves.
        return not (repo == "actions/download-artifact" and ref == "v7.0.1")

    problems = check_action_pins(root=tmp_path, resolver=resolver)
    assert len(problems) == 1
    assert "download-artifact@v7.0.1" in problems[0]
    assert "release.yml" in problems[0]


def test_all_resolving_pins_pass(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "jobs:\n  j:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    assert check_action_pins(root=tmp_path, resolver=lambda repo, ref: True) == []


def test_current_repo_pins_are_wellformed():
    # Static guard on the real workflows: every pin parses to owner/repo@ref.
    for pin in collect_pins():
        assert "/" in pin.action, f"{pin.file}:{pin.line} action has no owner/repo"
        assert pin.ref, f"{pin.file}:{pin.line} empty ref"


def test_gh_ref_exists_distinguishes_404_from_transient_errors(monkeypatch):
    # audit-lite: a transient GitHub error must NOT be treated as a missing ref
    # (that would false-fail the required PR gate). Only a confirmed 404 fails closed.
    import types

    import scripts.policy.check_action_pins as cap

    def responder(returncode, msg):
        def _run(cmd, **kwargs):
            return types.SimpleNamespace(
                returncode=returncode, stdout="{}" if returncode == 0 else "", stderr=msg
            )

        return _run

    # Confirmed 404 on every endpoint -> genuinely missing -> False (fails closed).
    monkeypatch.setattr(cap.subprocess, "run", responder(1, "gh: Not Found (HTTP 404)"))
    assert cap._gh_ref_exists("actions/download-artifact", "v7.0.1") is False
    # Transient/network/5xx -> inconclusive -> True (fails open, no false CI failure).
    monkeypatch.setattr(cap.subprocess, "run", responder(1, "error connecting to api.github.com"))
    assert cap._gh_ref_exists("actions/checkout", "v4") is True
    # Found -> True.
    monkeypatch.setattr(cap.subprocess, "run", responder(0, ""))
    assert cap._gh_ref_exists("actions/checkout", "v4") is True
