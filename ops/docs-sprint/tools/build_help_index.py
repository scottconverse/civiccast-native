"""Build docs/in-app-help/README.md (index of the in-app help specifications) from the files in that folder.

  python ops/docs-sprint/tools/build_help_index.py

Documentation tool, not product code. Counts the rows in each file's Mismatches table.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELP = ROOT / "docs" / "in-app-help"

GROUPS = {
    "Operator console: Run Meeting": [
        "live",
        "facility",
        "controlroom",
        "remotecontribution",
        "channels",
        "cg",
        "cgdesigner",
        "schedule",
        "autoschedule",
        "guide",
        "recording",
    ],
    "Operator console: Review and publish": [
        "assets",
        "missingmedia",
        "medialifecycle",
        "contribute",
        "review",
        "agendas",
        "summary",
        "publish",
        "playback",
        "analytics",
        "epg",
        "underwriting",
        "appadmin",
        "reports",
    ],
    "Operator console: Setup, health and shell": [
        "setup",
        "_shell-signin-and-session",
        "_shell-navigation-and-roles",
        "_shell-shared-components",
        "controlroomsetup",
        "station-profile",
        "commissioning",
        "ai-models",
        "custom-fields",
        "paywall",
        "health",
        "alerts",
        "eas",
        "activitypub",
        "help",
    ],
    "Resident portal": [
        "public-shell",
        "public-home",
        "public-recordings",
        "public-schedule",
        "public-watch",
        "public-player-captions",
        "public-agenda",
        "public-contribute",
        "public-paywall",
        "public-subscribe",
    ],
    "Installer": [
        "installer-gui-checking-computer",
        "installer-gui-download-plan",
        "installer-gui-downloading",
        "installer-gui-setup-wizard",
        "installer-nsis-setup-wizard",
        "installer-nsis-packs-and-verify",
        "installer-nsis-upgrade-database",
        "installer-nsis-activation-selftest",
        "installer-nsis-service-finish",
        "installer-uninstall",
        "installer-failures-and-logs",
        "installer-component-catalog",
        "installer-install-layout",
    ],
}

INTRO = """# In-app help specifications for beta.11

Written by the documentation sprint (2026-10-03) for the incoming coder. **Nothing here has been implemented.** Each file covers one screen, page or installer step of CivicCast beta.10 and has six sections: where the text lives now (source file and line), the current text, what the screen really does, the mismatches between the two, ready-to-paste proposed text, and notes for the coder.

## How to use these files

1. Read the **Mismatches** section first. Each row says what the text claims, what the code really does (with a citation) and how bad it is (blocks work, misleading, cosmetic).
2. Apply the **Proposed text** strings in the file named under *Where the text lives now*. Where a feature is broken, the file gives two versions: honest text for beta.10 as it is, and an `after fix:` version to use once the code is repaired.
3. Before changing a string, search `tests/` and the `*.test.tsx` and `e2e/` files for the old text. Each file's *Notes for the coder* lists the tests that pin strings.
4. Anything marked as needing a **code fix rather than a text fix** is listed in the file but is not a documentation task. The consolidated list is at the end of this page.
5. IDs: `HELP-nn` and `SHELL-nn` come from the screen inventories in `ops/docs-sprint/inventory/`; `NEW-n` ids restart in every file, so cite them as `<file>:NEW-n`.
6. Everything was read from code and checked against the fact-checked User Manual (`docs/USER-MANUAL.md`). Nothing was run on a station; items the writers could not confirm are marked inside each file.
"""

GAPS = [
    (
        "Summary review",
        "Approve sends extra fields the server refuses (expected HTTP 422); approved summaries drop off the list so Export signed record cannot be reached",
        "`summary.md`, manual ch. 5",
    ),
    (
        "Contributors",
        "Send to schedule likely fails for any submission with a requested air date (no time zone on the producer's date); producers never see operator notes",
        "`contribute.md`, manual ch. 3",
    ),
    (
        "Program Guide",
        "Skipped airings are never retried by Refresh guide; the Channel schedule page lists unpublished airings",
        "`guide.md`, manual ch. 3",
    ),
    (
        "Auto-schedule",
        "The screen says items need an operator commit; they are created Published and compiled hourly",
        "`autoschedule.md`, manual ch. 3",
    ),
    (
        "Alerts",
        "Destinations are empty by default and cannot be attached to a rule; several alert kinds (including emergency-alert source down) have no rule",
        "`alerts.md`, manual ch. 8",
    ),
    (
        "Emergency alerts",
        "Polling and auto-surface are off unless CIVICCAST_EAS and CIVICCAST_EAS_AUTO_SURFACE are set and nothing sets them; the portal's emergency box shows a hard-coded placeholder",
        "`eas.md`, `public-shell.md`, manual ch. 8",
    ),
    (
        "Paywall",
        "Saving with the signing-secret box blank erases the stored secret; no tiers or checkout routes; no sign-in email is sent",
        "`paywall.md`, `public-paywall.md`, manual ch. 6",
    ),
    (
        "Resident subscribe",
        "Notices are never sent; the confirmation link is a bare path with no web address and no page serving it; RSS feeds are empty",
        "`public-subscribe.md`, manual ch. 6",
    ),
    ("Playback policy", "Most settings are not enforced on video", "`playback.md`, manual ch. 6"),
    (
        "Analytics",
        'The "Telemetry is off" box points to a Reports tab and a Setup switch that do not exist',
        "`analytics.md`, manual ch. 7",
    ),
    (
        "Live and Channels",
        "The sample test source passes pre-flight from a file with no camera; Take live with a source last checked more than 30 seconds ago is refused before it re-checks",
        "`live.md`, `channels.md`, manual ch. 4",
    ),
    ("Facility", "Sample data only; no way to send a command", "`facility.md`, manual ch. 4"),
    (
        "Sign-in page",
        "The only sign-in is on a page titled First setup",
        "`_shell-signin-and-session.md`, manual ch. 2",
    ),
    (
        "Installer",
        "The setup page and first-run wizard promise AI models download after setup; setup needs the full kit and stops with exit 110 or 123 without it",
        "`installer-nsis-setup-wizard.md`, `installer-gui-download-plan.md`, manual ch. 10",
    ),
    (
        "Installer",
        "The exit 128 and 129 dialogs say nothing was changed; setup has already stopped the service and replaced the program files",
        "`installer-nsis-upgrade-database.md`, manual ch. 10",
    ),
    (
        "Installer",
        "The self-test failure dialog says the failing test is named in the installer log; it is not",
        "`installer-nsis-activation-selftest.md`, manual ch. 10",
    ),
    (
        "Installer",
        "Uninstall deletes the model-pack cache (about 21 GB) that a reinstall cannot re-download (MA-17)",
        "`installer-uninstall.md`, manual ch. 10",
    ),
    (
        "Backup and restore",
        "No `civiccast backup` or `restore` command exists; the DR drill calls the Postgres tools by bare name and most likely fails on native Windows",
        "manual ch. 12",
    ),
    (
        "Service configuration",
        "No installer code writes the service `Environment` registry value that the manual's environment-variable recipe relies on",
        "manual ch. 11 and 12",
    ),
    (
        "Control Room",
        "The sidecar service has no installer; the effect of Mute, Drop and Close room on a guest's sound was not found in code",
        "manual ch. 4 and 11",
    ),
    (
        "Logs",
        "`control_plane.log` and `postgres.log` are never rotated; the support bundle omits worker and control-plane logs",
        "manual ch. 12 and 14",
    ),
    (
        "Health",
        "`/health` shows `degraded` only for a non-current database schema",
        "manual ch. 14",
    ),
    (
        "Live CDN publisher",
        "`civiccast/live/cdn_publisher.py` is not covered in the architecture; unclear whether it is wired into the shipped app",
        "manual ch. 16",
    ),
    (
        "In-app manual",
        "`civiccast/docsite/manual.json` is generated from `docs/USER-MANUAL.md` and must be regenerated; the generator keeps only about 2.8% of the new manual's text, 50 screenshots are missing, and internal links may land on Page not found",
        "`help.md`",
    ),
    (
        "Captions",
        "Live caption audio is dropped when the caption worker falls behind (the top open engine item)",
        "manual Appendix H",
    ),
]


def info(name: str) -> tuple[str, int]:
    text = (HELP / f"{name}.md").read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip()
    m = re.search(r"## Mismatches\n(.*?)(?=\n## |\Z)", text, re.S)
    n = 0
    if m:
        n = sum(
            1
            for ln in m.group(1).splitlines()
            if ln.startswith("|") and not re.match(r"\|\s*(ID|-)", ln)
        )
    return title, n


def main() -> None:
    out = [INTRO]
    total = 0
    for group, names in GROUPS.items():
        out += [f"## {group}", "", "| File | Screen | Mismatches |", "| --- | --- | --- |"]
        for n in names:
            title, count = info(n)
            total += count
            out.append(f"| [{n}.md]({n}.md) | {title} | {count} |")
        out.append("")
    out += [
        f"Total mismatch rows across the files: {total}.",
        "",
        "## Code fixes found while writing the help (not text work)",
        "",
        "These came from the manual writers, the fact-checkers and the help-file writers. Each is a product defect or gap, with the manual chapter or help file that describes it.",
        "",
        "| Area | Problem | Where documented |",
        "| --- | --- | --- |",
    ]
    out += [f"| {a} | {p} | {w} |" for a, p, w in GAPS]
    (HELP / "README.md").write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print("files:", sum(len(v) for v in GROUPS.values()), "mismatch rows:", total)


if __name__ == "__main__":
    main()
