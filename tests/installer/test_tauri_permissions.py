from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_TAURI = REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri"
PERMISSIONS = SRC_TAURI / "permissions" / "installer-actions.toml"
MAIN_RS = SRC_TAURI / "src" / "main.rs"

_GENERATE_HANDLER = re.compile(r"tauri::generate_handler!\s*\[(?P<body>[^\]]*)\]", re.DOTALL)


def _camel_case(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def registered_command_names() -> set[str]:
    """Every command name ``main.rs`` actually registers with Tauri, in BOTH
    the ``snake_case`` form the Rust function uses and the ``camelCase`` form
    the frontend's ``invokeNativeInstallerAny`` fallback list also tries.

    Derived from the source on purpose rather than restated here. The previous
    version of this test asserted that a hardcoded set was a SUBSET (``<=``) of
    the allow-list, which is structurally blind to exactly the defect class it
    was meant to guard: four commands (``open_installer_log``,
    ``native_hardware_inventory``, ``start_acquisition``,
    ``retry_acquisition_component``) were registered in ``generate_handler!``
    and never added to ``installer-actions.toml``, so the Tauri ACL denied
    every call to them at runtime while the subset assertion stayed green.
    """

    source = MAIN_RS.read_text(encoding="utf-8")
    match = _GENERATE_HANDLER.search(source)
    assert match is not None, f"no tauri::generate_handler![...] block found in {MAIN_RS}"
    names = {
        stripped
        for entry in match.group("body").split(",")
        if (stripped := entry.strip()) and not stripped.startswith("//")
    }
    assert names, f"tauri::generate_handler![...] in {MAIN_RS} parsed to an empty command set"
    return names | {_camel_case(name) for name in names}


def allowed_command_names() -> set[str]:
    data = tomllib.loads(PERMISSIONS.read_text(encoding="utf-8"))
    permission = next(
        item for item in data["permission"] if item["identifier"] == "allow-installer-actions"
    )
    return set(permission["commands"]["allow"])


def test_installer_tauri_permissions_match_registered_commands_exactly() -> None:
    registered = registered_command_names()
    allowed = allowed_command_names()

    missing = sorted(registered - allowed)
    extra = sorted(allowed - registered)
    assert not missing, (
        "installer-actions.toml does not allow every command main.rs registers; "
        f"the Tauri ACL will deny these at runtime: {missing}"
    )
    assert not extra, (
        f"installer-actions.toml allows command names main.rs does not register: {extra}"
    )
    assert registered == allowed
