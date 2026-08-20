#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: only ``civiccast/stream/_ffmpeg.py`` may invoke ffmpeg via subprocess.

ADR 0007 requires every ffmpeg invocation to go through the
``civiccast.stream._ffmpeg`` adapter so command construction, error handling,
version checks, and the security posture (shell=False, explicit list args) live
in one auditable place. This check enforces that contract by parsing every
Python file under ``civiccast/`` and flagging a ``subprocess`` call whose
command argument references the ffmpeg binary.

It is AST-based, not textual: the word "ffmpeg" in a docstring, an error
message, a function name (``_ffmpeg_has_srt``), a ``shutil.which("ffmpeg")``
PATH probe, or a call to the wrapper API (``run_ffmpeg``) is NOT an invocation
and never flags. Only a spawn whose command argument is the ffmpeg binary does.

It resolves imports so the spawn surface is not a blind spot: aliased modules
(``import subprocess as sp``), direct imports (``from subprocess import run``),
shell-string commands (``subprocess.run("ffmpeg ...", shell=True)``), and the
``os.system`` / ``os.popen`` / ``os.exec*`` / ``os.spawn*`` family all count.

Accepted exception: a spawn call carrying ``# noqa: S603`` (or S605/S607) is a
reviewed exception (e.g. the NDI/SDI relays running an operator's bring-your-own
ffmpeg binary). Those are honoured, matching how the codebase already marks them.

Allowed file: ``civiccast/stream/_ffmpeg.py`` (the wrapper itself).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = REPO_ROOT / "civiccast"
ALLOWED_RELATIVE = Path("civiccast") / "stream" / "_ffmpeg.py"

# subprocess entry points that spawn a child process.
_SUBPROCESS_CALLERS = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
)
# os spawn surfaces (matched by attribute prefix: system, popen, exec*, spawn*,
# posix_spawn*) -- os.system("ffmpeg ...") bypasses subprocess entirely.
_OS_SPAWN_PREFIXES = ("system", "popen", "exec", "spawn", "posix_spawn")
# bandit process-spawn suppressions that mark a reviewed exception on the call.
_NOQA_MARKERS = ("# noqa: S603", "# noqa: S605", "# noqa: S607")


def _string_is_ffmpeg_command(value: str) -> bool:
    """True when a string literal invokes the ffmpeg binary.

    Covers both a list element (``"ffmpeg"``) and a shell command line
    (``"ffmpeg -i in.mp4"``) by testing only the FIRST whitespace-delimited
    token, so a filename like ``ffmpeg_out.mp4`` never matches. Because this is
    only ever applied to a spawn call's command argument (never to docstrings or
    error strings), ``"ffmpeg not found"`` is not reachable here.
    """
    stripped = value.strip()
    if not stripped:
        return False
    first = stripped.split()[0].lower()
    return (
        first in {"ffmpeg", "ffmpeg.exe"} or first.endswith("/ffmpeg") or first.endswith("\\ffmpeg")
    )


def _name_is_ffmpeg_binary(identifier: str) -> bool:
    """True when a bare name clearly denotes the ffmpeg binary or its path.

    Matches ``_FFMPEG_EXECUTABLE`` / ``FFMPEG`` / ``ffmpeg_path`` but not the
    wrapper API (``run_ffmpeg``), result/handle types, or exception classes --
    those reference the adapter, they are not a raw binary path.
    """
    upper = identifier.upper()
    if "FFMPEG" not in upper:
        return False
    return (
        upper == "FFMPEG"
        or "EXECUTABLE" in upper
        or upper.endswith("_PATH")
        or upper.endswith("_BIN")
        or upper.endswith("_BINARY")
    )


def _node_references_ffmpeg(node: ast.AST, command_vars: set[str]) -> bool:
    """True if an argument subtree references the ffmpeg binary."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Constant)
            and isinstance(sub.value, str)
            and _string_is_ffmpeg_command(sub.value)
        ):
            return True
        if isinstance(sub, ast.Name) and (sub.id in command_vars or _name_is_ffmpeg_binary(sub.id)):
            return True
    return False


def _ffmpeg_command_vars(tree: ast.AST) -> set[str]:
    """Names assigned a value that references the ffmpeg binary.

    Catches ``cmd = [_FFMPEG_EXECUTABLE, ...]`` so a later ``subprocess.run(cmd)``
    is still recognised as an ffmpeg invocation.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _node_references_ffmpeg(node.value, set()):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


class _SpawnContext:
    """The process-spawn call surfaces reachable in one module, resolved from its
    imports so aliases and direct imports are not a blind spot.

    ``import subprocess as sp`` -> ``sp.run`` counts; ``from subprocess import
    run`` -> a bare ``run(...)`` counts; ``os.system`` / ``os.popen`` count.
    """

    def __init__(self, tree: ast.AST) -> None:
        self.subprocess_modules: set[str] = {"subprocess"}
        self.os_modules: set[str] = {"os"}
        self.direct_spawn_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        self.subprocess_modules.add(alias.asname or "subprocess")
                    elif alias.name == "os":
                        self.os_modules.add(alias.asname or "os")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    for alias in node.names:
                        if alias.name in _SUBPROCESS_CALLERS:
                            self.direct_spawn_names.add(alias.asname or alias.name)
                elif node.module == "os":
                    for alias in node.names:
                        if alias.name.startswith(_OS_SPAWN_PREFIXES):
                            self.direct_spawn_names.add(alias.asname or alias.name)

    def is_spawn_call(self, func: ast.AST) -> bool:
        if isinstance(func, ast.Name):
            return func.id in self.direct_spawn_names
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = func.value.id
            if module in self.subprocess_modules and func.attr in _SUBPROCESS_CALLERS:
                return True
            if module in self.os_modules and func.attr.startswith(_OS_SPAWN_PREFIXES):
                return True
        return False


def _violations(file_path: Path) -> list[tuple[int, str]]:
    """Return [(line_number, line_text), ...] for ffmpeg spawn invocations."""
    source = file_path.read_text(encoding="utf-8", errors="replace")
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Unparseable files can't be audited here; lint/type-check catch those.
        return []

    context = _SpawnContext(tree)
    command_vars = _ffmpeg_command_vars(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and context.is_spawn_call(node.func)):
            continue
        # Honour a reviewed exception marked on any line the call spans.
        end_line = getattr(node, "end_lineno", node.lineno)
        span = lines[node.lineno - 1 : end_line]
        if any(marker in line for line in span for marker in _NOQA_MARKERS):
            continue
        arguments: list[ast.AST] = list(node.args)
        arguments.extend(kw.value for kw in node.keywords if kw.arg in {"args", None})
        if any(_node_references_ffmpeg(arg, command_vars) for arg in arguments):
            text = lines[node.lineno - 1].rstrip() if node.lineno - 1 < len(lines) else ""
            hits.append((node.lineno, text))
    return hits


def main() -> int:
    if not SCAN_ROOT.exists():
        print(f"check_ffmpeg_wrapper: scan root {SCAN_ROOT} does not exist. PASS (vacuous).")
        return 0

    violations: list[tuple[Path, int, str]] = []
    for py_file in SCAN_ROOT.rglob("*.py"):
        if py_file.relative_to(REPO_ROOT) == ALLOWED_RELATIVE:
            continue
        for line_num, line_text in _violations(py_file):
            violations.append((py_file.relative_to(REPO_ROOT), line_num, line_text))

    if violations:
        print("check_ffmpeg_wrapper: FAIL")
        print(f"  ffmpeg may only be invoked from {ALLOWED_RELATIVE.as_posix()} (ADR 0007).")
        print("  Violations:")
        for path, line_num, line_text in violations:
            print(f"    {path.as_posix()}:{line_num}  {line_text}")
        return 1

    print(
        f"check_ffmpeg_wrapper: PASS — only {ALLOWED_RELATIVE.as_posix()} invokes ffmpeg via subprocess."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
