"""One-off wrapper (NOT part of the repo) for the owner-waived beta.10 publish.

Keeps every check in scripts/release/publish_beta_candidate.py (gh auth, kit
layout, version identity, Authenticode, hashing, 2 GiB cap, draft->verify->
un-draft). Replaces ONLY the Gate A three-lane download/verify, which needs
GitHub artifacts that do not exist for dirty/download-only, and rewrites the
Gate A claims in the notes + release-truth text so they are TRUE.
Owner waiver: Scott, 2026-10-02 ("publish it").
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(r"C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-release")
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("pbc", REPO / "scripts" / "release" / "publish_beta_candidate.py")
pbc = importlib.util.module_from_spec(spec)
sys.modules["pbc"] = pbc
spec.loader.exec_module(pbc)

SRC = "b652084707367d45913807ed2a525f15a9a1e4a4"
CLEAN = "PASS (10 of 10 criteria; local Windows Sandbox run, 2026-10-02)"
DIRTY = "NOT RUN (waived by the owner)"
DL = "NOT RUN (waived by the owner)"


def fake_download(*, repository, gate_a_run_id, build_run_id, dest_dir):
    return {
        "clean": {"verdict": CLEAN, "source_sha": SRC},
        "dirty": {"verdict": DIRTY, "source_sha": SRC, "lane": "dirty"},
        "download-only": {"verdict": DL, "source_sha": SRC, "lane": "download-only"},
    }


def fake_verify(verdicts, *, source_sha):
    if source_sha != SRC:
        raise pbc.PublishError(f"wrapper is pinned to {SRC}, got {source_sha}")


orig_render = pbc.render_notes


def render(**kw):
    text = kw["changelog_text"]
    import re
    m = re.search(r"^## \[1\.0\.0-beta\.10\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        raise pbc.PublishError("beta.10 CHANGELOG section not found")
    kw["changelog_text"] = "## [Unreleased]\n\n" + m.group(1).strip() + "\n\n## [x]\n"
    notes = orig_render(**kw)

    def sub(old_start, new, notes):
        i = notes.find(old_start)
        if i < 0:
            raise pbc.PublishError(f"notes template changed; cannot find {old_start!r}")
        j = notes.find("\n\n", i)
        return notes[:i] + new + notes[j:]

    notes = sub(
        "> **This is a beta candidate",
        "> **This is a beta candidate, not a production release.** It has NOT had a "
        "human acceptance pass. Automated Gate A station-acceptance was run for the "
        "clean-install lane only (see below); the cross-version upgrade and "
        "download-only upgrade lanes were not run and were waived by the owner. "
        "Treat findings as expected; report them rather than assuming the release "
        "is broken.",
        notes,
    )
    notes = notes.replace(
        "## Gate A verdict (all three lanes required PASS)",
        "## Gate A station-acceptance (clean-install lane only; two lanes waived by the owner)",
    )
    notes = sub(
        "- Gate A run:",
        "- Gate A: clean-install lane run locally in Windows Sandbox on 2026-10-02 "
        "against exactly this build and installer (10 of 10 criteria). Its playout-engine "
        "check needed a longer wait than the default harness allows, because the "
        "engine's first packets arrive more than 60 s after its first start on a fresh "
        "install; that run used an extended wait and repeated capture. The "
        "dirty-upgrade and download-only lanes were not run.",
        notes,
    )
    notes = sub(
        "Download `setup.exe`; if you already",
        "Download `setup.exe` and run it. The installer finds the large AI components "
        "it needs and downloads them during installation, with a progress screen for "
        "the big ones; if you already have CivicCast installed, your recordings and "
        "database are kept. Full steps are in INSTALL-WINDOWS.md.",
        notes,
    )
    notes = sub(
        "Candidate identity:",
        "`v1.0.0-beta.8` and `v1.0.0-beta.9` were never published; their work is "
        "included here. Evidence and limits: "
        "https://github.com/scottconverse/civiccast-native/blob/v1.0.0-beta.10/docs/releases/v1.0.0-beta.10-verification.md",
        notes,
    )
    # the template's old USB-bundle sentences end the install paragraph
    for stale in (
        " First-time installs need the USB model bundle (the AI-model runtime is not a download asset on this release -- see INSTALL-WINDOWS.md).",
    ):
        notes = notes.replace(stale, "")
    return notes


orig_truth = pbc.update_release_truth


def truth(*, truth_path, tag, status, notes):
    notes = notes.replace(
        "(all three lanes PASS).",
        "Gate A: clean-install lane PASS (10 of 10, local Windows Sandbox run, "
        "2026-10-02); dirty-upgrade and download-only lanes not run, waived by the owner.",
    )
    return orig_truth(truth_path=truth_path, tag=tag, status=status, notes=notes)


pbc.download_gate_a_verdicts = fake_download
pbc.verify_gate_a_verdicts = fake_verify
pbc.render_notes = render
pbc.update_release_truth = truth
sys.exit(pbc.main(sys.argv[1:]))
