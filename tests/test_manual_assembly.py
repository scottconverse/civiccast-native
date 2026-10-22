"""Keep executable manual examples intact during documentation assembly."""

import runpy
from pathlib import Path


def test_windows_paths_in_fenced_commands_are_not_rewritten():
    root = Path(__file__).resolve().parents[1]
    wrap = runpy.run_path(str(root / "ops/docs-sprint/tools/build_manual.py"))["wrap_paths"]
    example = "```powershell\nGet-Content -LiteralPath 'C:\\ProgramData\\CivicCast\\install-progress.log'\n```"
    assert wrap(example) == example
    assert wrap(r"Directory: C:\ProgramData\CivicCast") == r"Directory: `C:\ProgramData\CivicCast`"
