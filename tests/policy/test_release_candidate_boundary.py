# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: current-release identity must not carry an unlabeled candidate claim.

CC-RC17-002 regression guard. `INSTALL-WINDOWS.md`, `FAQ.md`,
`docs/tester/START-HERE.md`, `docs/tester/lpm-beta-test-handoff.md`, and
`docs/tester/known-limitations.md` all named the public rc15 artifact while
describing rc17-only Ollama auto-provisioning / UAC-resume re-elevation as
current rc15 behavior. This suite proves the control catches that exact
pattern (red, reconstructed from the round-1 audited head at
`236850b8fd20db418b0ec34593d90f78857c7680`) and clears once the behavior is
labeled forthcoming (green).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_MODULE = importlib.import_module("scripts.policy.check_release_candidate_boundary")
evaluate_release_candidate_boundary = _MODULE.evaluate_release_candidate_boundary


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def enforcing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the control to enforcement mode (release identity behind the
    candidate line) so the behavior tests keep proving the control's logic
    after the live release identity advances to rc17 and the module-level
    constants become equal (the designed one-line relax)."""
    monkeypatch.setattr(_MODULE, "CURRENT_PUBLIC_RELEASE_TAG", "v1.0.0-rc15")


def test_unlabeled_ollama_marker_on_release_surface_fails_red(
    tmp_path: Path, enforcing: None
) -> None:
    """Exact round-1 shape: rc15 install page states rc17-only Ollama auto-provisioning
    as plain fact, no forthcoming label anywhere."""
    _write(
        tmp_path / "INSTALL-WINDOWS.md",
        "\n".join(
            [
                "# Install CivicCast On Windows",
                "",
                "> **Release state:** `v1.0.0-rc15` is the validated public Windows beta.",
                "",
                "## What The Setup Path Does",
                "",
                "- First-admin setup and recovery-kit creation.",
                "- The local Ollama AI runtime (reused if a healthy install already exists,",
                "  installed if absent) and the standard summary/translation models.",
                "",
            ]
        ),
    )

    findings = evaluate_release_candidate_boundary(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "INSTALL-WINDOWS.md"
    assert findings[0].marker == "local Ollama AI runtime"


def test_uac_reelevation_marker_wrongly_attributed_to_rc15_fails_red(
    tmp_path: Path, enforcing: None
) -> None:
    """Exact round-1 shape: known-limitations.md called the rc17 UAC-resume
    re-elevation behavior "the rc15 target"."""
    _write(
        tmp_path / "docs" / "tester" / "known-limitations.md",
        "\n".join(
            [
                "# Known Limitations",
                "",
                "> **Release state:** `v1.0.0-rc15` is the validated public Windows beta.",
                "",
                "The rc15 target is a CivicCast administrator-consent prompt. Do not expect",
                "exactly one prompt: if Windows requires a restart mid-setup, the resumed",
                "step re-elevates as a fresh process and shows the Windows prompt again.",
                "",
            ]
        ),
    )

    findings = evaluate_release_candidate_boundary(tmp_path)

    assert len(findings) == 1
    assert findings[0].path == "docs/tester/known-limitations.md"
    assert findings[0].marker == "re-elevates as a fresh"


def test_forthcoming_rc17_candidate_label_in_same_block_clears_it(
    tmp_path: Path, enforcing: None
) -> None:
    _write(
        tmp_path / "INSTALL-WINDOWS.md",
        "\n".join(
            [
                "# Install CivicCast On Windows",
                "",
                "> **Release state:** `v1.0.0-rc15` is the validated public Windows beta.",
                "",
                "## What The Setup Path Does",
                "",
                "- First-admin setup and recovery-kit creation.",
                "- **Forthcoming rc17-candidate behavior — not in the published rc15",
                "  installer:** the local Ollama AI runtime (reused if a healthy install",
                "  already exists, installed if absent).",
                "",
            ]
        ),
    )

    assert evaluate_release_candidate_boundary(tmp_path) == []


def test_qualifier_in_a_different_block_does_not_clear_the_marker(
    tmp_path: Path, enforcing: None
) -> None:
    """A forthcoming label elsewhere in the file must not launder an unlabeled
    claim in a different paragraph -- the label has to sit with the claim it
    covers, or a reader hits the unlabeled sentence and never sees it."""
    _write(
        tmp_path / "FAQ.md",
        "\n".join(
            [
                "# FAQ",
                "",
                "`v1.0.0-rc15` is the current public Windows repair beta.",
                "",
                "It also sets up the local Ollama AI runtime for you automatically.",
                "",
                "Unrelated note: forthcoming rc17-candidate improvements are planned",
                "for the resident portal search feature.",
                "",
            ]
        ),
    )

    findings = evaluate_release_candidate_boundary(tmp_path)

    assert {f.marker for f in findings} == {"local Ollama AI runtime", "sets up the local Ollama"}


def test_marker_wrapped_across_two_source_lines_is_still_caught(
    tmp_path: Path, enforcing: None
) -> None:
    _write(
        tmp_path / "docs" / "USER-MANUAL.md",
        "\n".join(
            [
                "# User Manual",
                "",
                "The public rc15 beta proves a bounded local path.",
                "",
                "The local AI models (Ollama summary and",
                "translation models) are large.",
                "",
            ]
        ),
    )

    findings = evaluate_release_candidate_boundary(tmp_path)

    assert len(findings) == 1
    assert findings[0].marker == "Ollama summary and translation models"
    # Reported against the block's first line since no single source line
    # contains the full (reflowed) phrase.
    assert findings[0].line == 5


def test_markers_outside_the_curated_surface_list_are_not_scanned(
    tmp_path: Path, enforcing: None
) -> None:
    """A doc naming rc15 that isn't a live release-identity surface (e.g. a
    historical evidence log) is out of this control's scope by design."""
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "v1.0.0-rc15-notes.md",
        "\n".join(
            [
                "`v1.0.0-rc15` is the current public beta.",
                "It also sets up the local Ollama AI runtime for you.",
            ]
        ),
    )

    assert evaluate_release_candidate_boundary(tmp_path) == []


def test_release_identity_advancing_to_the_candidate_tag_relaxes_the_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one-deliberate-change design point: once CURRENT_PUBLIC_RELEASE_TAG
    is bumped to equal CANDIDATE_CAPABILITY_INTRODUCED_IN, the same unlabeled
    text is current-release fact, not a candidate claim, and clears without
    touching any doc.

    Both the fixture text and the "advanced" value read the module's own
    CANDIDATE_CAPABILITY_INTRODUCED_IN rather than a hard-coded tag. An earlier
    version pinned "v1.0.0-rc17" in three places and went red at the rc18 bump
    for no product reason -- the test is about the EQUALITY of the two
    constants, not about any particular release number.
    """
    candidate_tag = _MODULE.CANDIDATE_CAPABILITY_INTRODUCED_IN
    _write(
        tmp_path / "INSTALL-WINDOWS.md",
        "\n".join(
            [
                f"`{candidate_tag}` is the validated public Windows beta.",
                "The local Ollama AI runtime is set up automatically.",
            ]
        ),
    )
    monkeypatch.setattr(_MODULE, "CURRENT_PUBLIC_RELEASE_TAG", "v1.0.0-rc15")
    assert evaluate_release_candidate_boundary(tmp_path) != []

    monkeypatch.setattr(_MODULE, "CURRENT_PUBLIC_RELEASE_TAG", candidate_tag)

    assert evaluate_release_candidate_boundary(tmp_path) == []


def test_real_docs_pass_after_the_cc_rc17_002_fix() -> None:
    """Integration proof: the actual repo docs, post-fix, clear the control."""
    assert evaluate_release_candidate_boundary() == []


def test_round1_audited_head_docs_fail_the_control(tmp_path: Path, enforcing: None) -> None:
    """Reconstructs the exact round-1 audited-head (236850b8) doc content for
    every CC-RC17-002 surface and proves the control fails against it --
    the red half of red-first, pinned to the real historical text rather
    than a synthetic approximation."""
    round1_texts = {
        "INSTALL-WINDOWS.md": (
            "> **Release state:** `v1.0.0-rc15` is the validated public Windows beta.\n\n"
            "Leave at least **5 GB of free disk space** for the base installation. "
            "The local AI models (Ollama summary and\n"
            "translation models) are large on top of that: roughly 15-20 GB combined\n"
            "(every install downloads the same standard set).\n\n"
            "- The local Ollama AI runtime (reused if a healthy install already exists,\n"
            "  installed if absent) and the standard summary/translation models "
            "(the same three downloads on every install).\n\n"
            "You may still need to approve Windows administrator prompts. Do not expect\n"
            "exactly one prompt: if Windows asks for a restart while setting up the helper,\n"
            "restart and reopen the CivicCast installer or setup instructions, and expect\n"
            "to approve a Windows security prompt again when it resumes — a restart clears\n"
            "the earlier approval, so CivicCast re-elevates as a fresh step rather than\n"
            "carrying the first approval across the reboot. The rc15 candidate re-probes\n"
            "the helper after reboot; it should continue when the helper is ready or show\n"
            "**Set up Windows helper** again when repair is needed.\n"
        ),
        "docs/tester/known-limitations.md": (
            "> **Release state:** `v1.0.0-rc15` is the validated public Windows beta.\n\n"
            "The rc15 target is a CivicCast administrator-consent prompt and no visible\n"
            "helper console. Do not expect exactly one prompt: if Windows requires a\n"
            "restart mid-setup, the resumed step re-elevates as a fresh process and shows\n"
            "the Windows prompt again — that second prompt is expected, not a defect.\n"
        ),
    }
    for relative, text in round1_texts.items():
        _write(tmp_path / relative, text)

    findings = evaluate_release_candidate_boundary(tmp_path)

    assert len(findings) >= 2
    found_paths = {f.path for f in findings}
    assert "INSTALL-WINDOWS.md" in found_paths
    assert "docs/tester/known-limitations.md" in found_paths
