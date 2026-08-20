# SPDX-License-Identifier: Apache-2.0
"""The bootstrap's own status messages must name controls the app will render.

`headless-bootstrap.ps1` writes the first-run state the installer app reads.
The app picks its primary button from that state: on the Windows-helper lane a
pending reboot makes the button read "Resume after reboot", and otherwise it
reads "Set up Windows helper".

So a state that *says* "Choose Set up Windows helper" while *also* reporting a
pending reboot instructs the operator to click a control the same state
guarantees will not appear. That shipped: on a pristine guest the first-run
screen said "choose Set up Windows helper" twice while the only button read
"Resume after reboot".

This guard is about the pairing, not the wording -- either half may be
reworded, but they may not contradict each other.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO / "civiccast/apps/installer/src-tauri/resources/headless-bootstrap.ps1"

# Write-State <lane> <status> <message> <rebootRequired>
WRITE_STATE = re.compile(
    r"""Write-State\s+"(?P<lane>[^"]*)"\s+"(?P<status>[^"]*)"\s+"(?P<message>[^"]*)"\s+(?P<reboot>\$true|\$false)""",
)

HELPER_CONTROL = "Set up Windows helper"


def _states() -> list[re.Match[str]]:
    matches = list(WRITE_STATE.finditer(BOOTSTRAP.read_text(encoding="utf-8")))
    assert matches, "no Write-State calls parsed -- the guard would pass vacuously"
    return matches


def test_bootstrap_script_is_present() -> None:
    assert BOOTSTRAP.exists(), f"missing {BOOTSTRAP}"


def test_no_state_names_a_control_its_reboot_flag_suppresses() -> None:
    offenders = [
        f"lane={m.group('lane')!r} status={m.group('status')!r}: {m.group('message')[:90]!r}"
        for m in _states()
        if HELPER_CONTROL in m.group("message") and m.group("reboot") == "$true"
    ]
    assert not offenders, (
        "A bootstrap state tells the operator to choose "
        f"{HELPER_CONTROL!r} while reporting a pending reboot, which makes the "
        "app render 'Resume after reboot' instead. The instruction names a "
        "control that will not exist:\n" + "\n".join(offenders)
    )


def test_guard_would_catch_the_shipped_pairing() -> None:
    # Mutation check: the regex and the rule actually fire on the real defect.
    sample = (
        'Write-State "wsl2" "blocked" "Windows Subsystem for Linux is not set up '
        "on this computer yet. Open CivicCast Installer and choose Set up Windows "
        'helper - Windows will show one or two admin approval prompts." $true'
    )
    match = WRITE_STATE.search(sample)
    assert match is not None, "regex failed to parse a real Write-State call"
    assert HELPER_CONTROL in match.group("message")
    assert match.group("reboot") == "$true"
