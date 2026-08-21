# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: bind the K1 activation self-test's server-binary paths to the
server-pack builder's own pin tables -- on BOTH Rust probe lists, and with
the builder's own staging PREFIXES, never a re-typed copy of either.

K1 activation was failing because ``native_activation.rs``'s
``REQUIRED_STAGED_RUNTIME_FILES`` pointed at ``dependencies/{postgresql,nats,
tsduck,node}`` -- paths nothing ever stages. Commit 6d559f3fa repathed the
three server binaries to their real staged location under
``packs/native-server-binaries/payload/...`` and dropped node. That fix
repointed the self-test's list by hand, but nothing bound that list to where
the pack BUILDER (``scripts/build_native_server_pack.py``) actually stages
the bytes -- so a future change to the builder's staging prefixes (or a
regressed self-test edit) could re-break activation while every existing
test still passed, because no test read both sides together. This module is
that binding, closed from two directions a first pass left open:

1. **The staging PREFIX itself is derived from the builder's source, not
   hard-coded here.** ``_pack_builder_staging_prefixes`` parses the
   ``sources[f"<prefix>/{filename}"] = path`` assignment inside each of
   ``_postgres_sources`` / ``_tsduck_sources`` via
   ``ast`` -- never assumes ``bin`` or ``tsduck/bin`` as literals. If the
   builder ever changes a destination prefix (e.g.
   ``sources[f"bin/{fn}"]`` -> ``sources[f"bin2/{fn}"]``) without touching a
   filename, this guard's derived staged-path set moves with it and a
   Rust list that still says the OLD prefix fails.

2. **``main.rs``'s own probe list is bound too, not just
   ``native_activation.rs``'s.** The flat-activation path also runs
   ``run_native_pre_activation_checks`` in ``main.rs`` -- a SEPARATE
   ``checks`` array of ``(path, args, name, expected)`` tuples that could
   drift back to a ``dependencies/...`` path on its own, independently of
   ``native_activation.rs``, and still pass every other guard. This module
   binds that list to the same builder-declared set, AND asserts the two
   Rust files' own server-binary path sets agree with each other.

SCOPE. This guard covers ONLY the server-binaries pack paths -- the exact
class of entry that broke K1 (``packs/native-server-binaries/payload/...``).
The other required-path entries -- ffmpeg (``dependencies/ffmpeg``), ollama
(``dependencies/ollama``), the embedded Python runtime (``runtime/...``),
the captions-floor model tier (``packs/captions-floor/...``), and the Ollama
model manifests (``models/ollama/manifests/...``) -- are pinned against
their OWN separate pack builders (``build_native_ffmpeg_pack.py``,
``build_native_distribution.py``, the caption-pack builder, the
model-acquisition lock) and are still synced by convention, not by this
guard. They did not break in the K1 incident and are lower priority; a
future task can extend this pattern to them if warranted.

FOLLOW-UP (K1-1 / K1-2, audit findings after the original K1 incident).
Two of the three server-binary probes needed a posture correction on top of
the path-repointing above:

* **K1-1 -- tsp.exe demoted from hard-required to verified-if-present.** The
  runtime treats TSDuck as optional (``egress/ts_relay.py``'s
  ``CIVICCAST_TS_RELAY=auto`` warns and passes udp-ts egress straight through
  when ``tsp`` is unavailable, rather than failing the channel), but
  activation used to hard-require it on both Rust checkpoints -- stricter
  than the thing it was activating. ``test_tsp_is_not_hard_required_on_either_rust_checkpoint``
  and ``test_optional_tsp_path_is_builder_declared_and_agrees_on_both_checkpoints``
  guard the fix: absent tsp.exe must never fail activation, but a present,
  broken one still must.
* **K1-2 -- pg_ctl.exe added alongside postgres.exe.** The self-test checked
  ``postgres.exe`` but the supervisor actually launches PostgreSQL through
  ``pg_ctl.exe`` (``native/supervisor/children.py::postgres_child_spec``).
  ``test_postgres_pins_cover_both_the_self_test_binary_and_the_runtime_launcher``
  now asserts both binaries are required on both Rust checkpoints, not just
  that both are theoretically pinnable.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUST_NATIVE_ACTIVATION = (
    REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "native_activation.rs"
)
RUST_MAIN = REPO_ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs"
SERVER_PACK_BUILDER = REPO_ROOT / "scripts" / "build_native_server_pack.py"

#: Where the ``native-server-binaries`` pack extracts to, per the builder's
#: own module docstring (build_native_server_pack.py:8-9): "extracted, at
#: ``<install_root>\\packs\\native-server-binaries\\payload\\bin\\
#: initdb.exe``". This root is NOT itself derived from source (it is a
#: filesystem-layout fact stated in the docstring, not a variable in code);
#: everything below it -- the per-table PREFIX -- is derived, not assumed.
STAGED_PAYLOAD_ROOT = "packs/native-server-binaries/payload"

#: The pin-table dict names this guard covers, in the order their
#: staging loops appear in the builder. NATS JetStream was removed from the
#: product (owner decision 2026-08-20; see ADR 0023, which supersedes ADR
#: 0001), so ``NATS_BIN_PINS`` no longer exists in the builder and is not
#: tracked here.
_TRACKED_PIN_TABLES = ("POSTGRES_BIN_PINS", "TSDUCK_BIN_PINS")

#: The wrong convention the K1 incident shipped: paths nothing ever stages.
#: Belt-and-suspenders at the Python-policy level against reintroducing it,
#: checked against BOTH Rust probe lists. ``dependencies/nats`` stays in this
#: never-reappear list defensively even though NATS is no longer part of the
#: product at all.
_WRONG_LEGACY_PREFIXES = (
    "dependencies/postgresql",
    "dependencies/nats",
    "dependencies/tsduck",
    "dependencies/node",
)


def _load_server_pack_builder():
    """Import ``scripts/build_native_server_pack.py`` by path.

    ``scripts/`` is not an importable package, so this is loaded through
    importlib rather than a plain import -- the point is to read the
    BUILDER's own ``POSTGRES_BIN_PINS`` / ``TSDUCK_BIN_PINS`` dict objects,
    never a re-declared copy of them.
    Matches the convention ``tests/policy/test_shipped_payload_db_driver.py``
    already uses for the same class of script (and the pattern
    ``tests/native/test_build_native_server_pack.py`` /
    ``tests/installer/test_stage_native_server_pack.py`` use for this exact
    module).
    """

    spec = spec_from_file_location(
        "_civiccast_native_server_pack_builder_policy", SERVER_PACK_BUILDER
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _required_staged_runtime_files() -> list[str]:
    """The quoted path entries inside ``native_activation.rs``'s
    ``REQUIRED_STAGED_RUNTIME_FILES``.

    Parsed by reading the Rust source as text and regexing the const's
    array literal, rather than compiling/linking Rust -- this policy suite
    is a host-safe, no-network, no-toolchain slice (see
    ``tests/policy/test_native_pack_source_sha_contract.py`` for the same
    text-based-Rust-parsing convention).
    """

    text = RUST_NATIVE_ACTIVATION.read_text(encoding="utf-8")
    match = re.search(
        r"const REQUIRED_STAGED_RUNTIME_FILES: &\[&str\] = &\[(.*?)\];",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "REQUIRED_STAGED_RUNTIME_FILES const not found in "
        f"{RUST_NATIVE_ACTIVATION.relative_to(REPO_ROOT)} -- did it move or get renamed?"
    )
    entries = re.findall(r'"([^"]+)"', match.group(1))
    assert entries, "REQUIRED_STAGED_RUNTIME_FILES const matched but no quoted entries were found"
    return entries


def _main_rs_pre_activation_check_paths() -> list[str]:
    """The first-element (relative staged path) of every tuple in
    ``main.rs``'s ``run_native_pre_activation_checks::checks`` array.

    ``checks`` is a fixed-size array of ``(&str, &[&str], &str, &str)``
    tuples -- ``(relative_path, argv, probe_name, expected_stdout_needle)``.
    This is a SEPARATE probe list from ``native_activation.rs``'s
    ``REQUIRED_STAGED_RUNTIME_FILES``: the flat-activation path runs both,
    and either one alone drifting back to a ``dependencies/...`` path breaks
    activation, so both need their own binding to the builder (and to each
    other -- see ``test_native_activation_and_main_rs_agree_on_server_binary_paths``).

    Parsed the same text-regex way as ``_required_staged_runtime_files``:
    the array's own declared length (``; N``) and the single closing ``];``
    make the block unambiguous to isolate, and none of the nested
    ``&[...]`` argv literals inside it are followed by ``"`` immediately
    after an unescaped ``(``, so a tuple-opening ``(\\s*"`` match cannot
    mistake an argv/needle string for a tuple's first element.
    """

    text = RUST_MAIN.read_text(encoding="utf-8")
    match = re.search(
        r"let checks: \[\(&str, &\[&str\], &str, &str\); \d+\] = \[(.*?)\];",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "run_native_pre_activation_checks' `checks` array not found in "
        f"{RUST_MAIN.relative_to(REPO_ROOT)} -- did it move, get renamed, or change shape?"
    )
    entries = re.findall(r'\(\s*"([^"]+)"', match.group(1))
    assert entries, "checks array matched but no tuple first-elements were found"
    return entries


def _for_loop_first_target_name(target: ast.expr) -> str | None:
    """The loop variable name bound to each pin dict's key in ``for filename,
    (...) in sorted(<PINS>.items()):`` -- ``filename`` here, extracted
    structurally rather than assumed, so the prefix-assignment matcher below
    can confirm the f-string's substitution really is the loop's own key."""

    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Tuple) and target.elts and isinstance(target.elts[0], ast.Name):
        return target.elts[0].id
    return None


def _loop_pins_dict_name(iter_node: ast.expr) -> str | None:
    """The pin-dict name out of a loop header shaped
    ``sorted(<NAME>.items())`` -- ``None`` for anything else, so unrelated
    for-loops elsewhere in the builder are never mistaken for a staging
    loop."""

    if (
        isinstance(iter_node, ast.Call)
        and isinstance(iter_node.func, ast.Name)
        and iter_node.func.id == "sorted"
        and iter_node.args
        and isinstance(iter_node.args[0], ast.Call)
        and isinstance(iter_node.args[0].func, ast.Attribute)
        and iter_node.args[0].func.attr == "items"
        and isinstance(iter_node.args[0].func.value, ast.Name)
    ):
        return iter_node.args[0].func.value.id
    return None


def _sources_assignment_prefix(assign: ast.Assign, loop_var_name: str) -> str | None:
    """If ``assign`` is exactly ``sources[f"<prefix>/{<loop_var_name>}"] =
    ...``, return ``<prefix>``; otherwise ``None``.

    Requires the subscript key to be a two-piece f-string -- one literal
    ``Constant`` prefix followed by exactly one ``FormattedValue`` that
    substitutes the loop's OWN key variable -- so an unrelated ``sources[...]
    = ...`` assignment elsewhere in the loop body (or one keyed on a
    different variable) is never mistaken for the staging destination.
    """

    if len(assign.targets) != 1:
        return None
    target = assign.targets[0]
    if not (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and target.value.id == "sources"
    ):
        return None
    key = target.slice
    if not isinstance(key, ast.JoinedStr) or len(key.values) != 2:
        return None
    constant_part, formatted_part = key.values
    if not (
        isinstance(constant_part, ast.Constant)
        and isinstance(constant_part.value, str)
        and isinstance(formatted_part, ast.FormattedValue)
        and isinstance(formatted_part.value, ast.Name)
        and formatted_part.value.id == loop_var_name
    ):
        return None
    return constant_part.value.rstrip("/")


def _pack_builder_staging_prefixes(source_text: str) -> dict[str, str]:
    """Map each of ``_TRACKED_PIN_TABLES`` to the staging-destination PREFIX
    ``scripts/build_native_server_pack.py`` actually writes for it.

    Parsed via ``ast`` from the builder's own
    ``for filename, ... in sorted(<PINS>.items()): ... sources[f"<prefix>/
    {filename}"] = path`` loops -- never hard-coded. This is the P2 fix: a
    prior version of this guard hard-coded ``bin`` / ``tsduck/bin`` as
    literals matching what the builder happened to say at review time, which
    meant a future prefix change in the builder (filenames unchanged) would
    silently pass this test while the Rust self-test kept requiring the OLD
    staged path -- i.e. a re-break of K1 this test would not have caught.
    Deriving the prefix from the builder's own AST closes that gap: the
    derived staged-path set moves WITH the builder.
    """

    tree = ast.parse(source_text, filename=str(SERVER_PACK_BUILDER))
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        pins_name = _loop_pins_dict_name(node.iter)
        if pins_name not in _TRACKED_PIN_TABLES:
            continue
        loop_var_name = _for_loop_first_target_name(node.target)
        assert loop_var_name is not None, (
            f"unrecognized for-loop target shape while parsing the {pins_name} staging loop"
        )
        prefix = None
        for stmt in node.body:
            for candidate in ast.walk(stmt):
                if isinstance(candidate, ast.Assign):
                    found = _sources_assignment_prefix(candidate, loop_var_name)
                    if found is not None:
                        prefix = found
                        break
            if prefix is not None:
                break
        assert prefix is not None, (
            f"could not find sources[f'<prefix>/{{{loop_var_name}}}'] = ... inside the "
            f"{pins_name} staging loop -- did build_native_server_pack.py's staging shape change?"
        )
        assert pins_name not in prefixes, f"{pins_name} is iterated by more than one for-loop"
        prefixes[pins_name] = prefix
    missing = set(_TRACKED_PIN_TABLES) - prefixes.keys()
    assert not missing, f"could not locate a staging loop for: {sorted(missing)}"
    return prefixes


def _builder_declared_staged_server_binary_paths(
    module: object, prefixes: dict[str, str]
) -> set[str]:
    """The staged server-binary paths the pack BUILDER actually declares:
    ``{STAGED_PAYLOAD_ROOT}/{prefix}/{filename}`` for every filename key in
    each pin table, using the table's OWN AST-derived prefix (see
    ``_pack_builder_staging_prefixes``) rather than an assumed literal."""

    paths: set[str] = set()
    for pins_name in _TRACKED_PIN_TABLES:
        pins = getattr(module, pins_name)
        prefix = prefixes[pins_name]
        for filename in pins:
            paths.add(f"{STAGED_PAYLOAD_ROOT}/{prefix}/{filename}")
    return paths


def _declared_server_binary_paths() -> set[str]:
    """Convenience: load the builder, derive its staging prefixes, and
    return the resulting builder-declared staged-path set in one call."""

    module = _load_server_pack_builder()
    prefixes = _pack_builder_staging_prefixes(SERVER_PACK_BUILDER.read_text(encoding="utf-8"))
    return _builder_declared_staged_server_binary_paths(module, prefixes)


def test_self_test_server_binary_paths_are_all_builder_declared() -> None:
    """The core guard on ``native_activation.rs``: the self-test may only
    require server binaries the pack builder actually stages there, at the
    prefix the builder actually writes.

    A future pack-layout change (a renamed pin, a moved staging prefix, a
    dropped binary) that stops matching ``REQUIRED_STAGED_RUNTIME_FILES``
    fails THIS test instead of silently re-breaking K1 activation.
    """

    required = _required_staged_runtime_files()
    server_binary_entries = [
        entry for entry in required if entry.startswith(f"{STAGED_PAYLOAD_ROOT}/")
    ]
    assert server_binary_entries, (
        f"no {STAGED_PAYLOAD_ROOT}/ entries found in REQUIRED_STAGED_RUNTIME_FILES -- "
        "did the K1 fix get reverted?"
    )

    declared = _declared_server_binary_paths()

    for entry in server_binary_entries:
        assert entry in declared, (
            f"activation self-test requires {entry!r} but "
            "scripts/build_native_server_pack.py's pin tables never stage that path -- "
            "this is exactly the K1 defect class (self-test and builder drifted apart)"
        )


def test_main_rs_pre_activation_checks_server_binary_paths_are_all_builder_declared() -> None:
    """The same core guard, applied to ``main.rs``'s SEPARATE
    ``run_native_pre_activation_checks::checks`` array.

    The flat-activation path runs both native_activation.rs's self-test AND
    main.rs's pre-activation checks. If only main.rs's list drifted back to
    a ``dependencies/...`` path, activation would break while
    ``test_self_test_server_binary_paths_are_all_builder_declared`` stayed
    green, because it only reads native_activation.rs. This closes that gap.
    """

    entries = _main_rs_pre_activation_check_paths()
    server_binary_entries = [
        entry for entry in entries if entry.startswith(f"{STAGED_PAYLOAD_ROOT}/")
    ]
    assert server_binary_entries, (
        f"no {STAGED_PAYLOAD_ROOT}/ entries found in main.rs's pre-activation checks -- "
        "did the K1 fix get reverted there too?"
    )

    declared = _declared_server_binary_paths()

    for entry in server_binary_entries:
        assert entry in declared, (
            f"main.rs's pre-activation checks require {entry!r} but "
            "scripts/build_native_server_pack.py's pin tables never stage that path -- "
            "this is exactly the K1 defect class (probe list and builder drifted apart)"
        )


def test_native_activation_and_main_rs_agree_on_server_binary_paths() -> None:
    """The two Rust probe lists must name the SAME server-binary paths as
    each other, not just each independently be builder-valid.

    Independent validity alone would let one file pin a DIFFERENT (but still
    builder-declared) server binary than the other -- e.g. one list checking
    ``pg_ctl.exe`` while the other still checks ``postgres.exe`` at a
    renamed/moved layout -- without either binding above noticing. Pinning
    the two sets equal to each other closes that.
    """

    required = _required_staged_runtime_files()
    required_server = {entry for entry in required if entry.startswith(f"{STAGED_PAYLOAD_ROOT}/")}

    checks = _main_rs_pre_activation_check_paths()
    checks_server = {entry for entry in checks if entry.startswith(f"{STAGED_PAYLOAD_ROOT}/")}

    assert required_server == checks_server, (
        "native_activation.rs's REQUIRED_STAGED_RUNTIME_FILES and main.rs's "
        "run_native_pre_activation_checks disagree on which server-binary paths to "
        f"require: only in native_activation.rs: {sorted(required_server - checks_server)}; "
        f"only in main.rs: {sorted(checks_server - required_server)}"
    )


def test_postgres_pins_cover_both_the_self_test_binary_and_the_runtime_launcher() -> None:
    """K1-2 fix: the self-test now checks BOTH ``bin/postgres.exe`` and
    ``bin/pg_ctl.exe`` -- the runtime actually launches PostgreSQL through
    ``pg_ctl.exe`` (``native/supervisor/children.py::postgres_child_spec``
    builds ``argv=[pg_ctl_path, "start", ...]``; pg_ctl then spawns
    postgres.exe as its child). Both are keys in ``POSTGRES_BIN_PINS`` (staged
    at the same prefix) and both must now appear in every hard-required probe
    list on both Rust checkpoints -- checking only postgres.exe was a
    coverage gap (K1-2), not just a stylistic choice.
    """

    module = _load_server_pack_builder()
    assert "postgres.exe" in module.POSTGRES_BIN_PINS
    assert "pg_ctl.exe" in module.POSTGRES_BIN_PINS

    for entry in ("bin/postgres.exe", "bin/pg_ctl.exe"):
        expected = f"{STAGED_PAYLOAD_ROOT}/{entry}"
        assert expected in _required_staged_runtime_files(), (
            f"{expected!r} must be in native_activation.rs's REQUIRED_STAGED_RUNTIME_FILES (K1-2)"
        )
        assert expected in _main_rs_pre_activation_check_paths(), (
            f"{expected!r} must be in main.rs's run_native_pre_activation_checks (K1-2)"
        )


def _native_activation_optional_verified_if_present_paths() -> list[str]:
    """The quoted path entries inside ``native_activation.rs``'s
    ``OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES`` (K1-1: tsp.exe demoted
    from hard-required to verified-if-present, matching
    ``egress/ts_relay.py``'s ``CIVICCAST_TS_RELAY=auto`` warn-and-pass
    posture). Parsed the same text-regex way as
    ``_required_staged_runtime_files``.
    """

    text = RUST_NATIVE_ACTIVATION.read_text(encoding="utf-8")
    match = re.search(
        r"const OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES: &\[&str\] = &\[(.*?)\];",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES const not found in "
        f"{RUST_NATIVE_ACTIVATION.relative_to(REPO_ROOT)} -- did the K1-1 fix get reverted?"
    )
    entries = re.findall(r'"([^"]+)"', match.group(1))
    assert entries, (
        "OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES const matched but no quoted entries were found"
    )
    return entries


def _main_rs_optional_verified_if_present_path() -> str:
    """The staged-relative path ``main.rs``'s
    ``run_native_optional_verified_if_present_checks`` probes (K1-1's
    counterpart check in the flat-activation path's SEPARATE probe list).
    """

    text = RUST_MAIN.read_text(encoding="utf-8")
    match = re.search(
        r"fn run_native_optional_verified_if_present_checks.*?"
        r'let relative = "([^"]+)";',
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "run_native_optional_verified_if_present_checks' probed path not found in "
        f"{RUST_MAIN.relative_to(REPO_ROOT)} -- did the K1-1 fix get reverted or renamed?"
    )
    return match.group(1)


def test_tsp_is_not_hard_required_on_either_rust_checkpoint() -> None:
    """K1-1: tsp.exe must not appear in either Rust file's HARD-required
    server-binary probe list -- the runtime treats TSDuck as optional
    (``egress/ts_relay.py``'s ``CIVICCAST_TS_RELAY=auto`` warns and passes
    udp-ts egress through rather than failing the channel when ``tsp`` is
    unavailable), and activation must not be stricter than the runtime it is
    activating.
    """

    required = _required_staged_runtime_files()
    assert not any("tsp.exe" in entry for entry in required), (
        "native_activation.rs's REQUIRED_STAGED_RUNTIME_FILES must not hard-require tsp.exe "
        "(K1-1: TSDuck is optional at runtime)"
    )

    checks = _main_rs_pre_activation_check_paths()
    assert not any("tsp.exe" in entry for entry in checks), (
        "main.rs's run_native_pre_activation_checks must not hard-require tsp.exe "
        "(K1-1: TSDuck is optional at runtime)"
    )


def test_optional_tsp_path_is_builder_declared_and_agrees_on_both_checkpoints() -> None:
    """K1-1's positive half: tsp.exe must still be VERIFIED when staged, at
    the real builder-declared path, and both Rust checkpoints must probe the
    identical path -- so a future edit cannot silently stop verifying a
    present-but-broken TSDuck copy, or let the two checkpoints drift apart
    on where they look for it.
    """

    optional = _native_activation_optional_verified_if_present_paths()
    assert len(optional) == 1, (
        "expected exactly one optional-verified-if-present entry (tsp.exe); "
        f"got {optional!r} -- update this test if that intentionally changed"
    )
    native_activation_path = optional[0]
    assert native_activation_path.startswith(f"{STAGED_PAYLOAD_ROOT}/"), (
        f"optional tsp.exe path must be under {STAGED_PAYLOAD_ROOT}/, got {native_activation_path!r}"
    )

    declared = _declared_server_binary_paths()
    assert native_activation_path in declared, (
        f"native_activation.rs's optional tsp.exe path {native_activation_path!r} is not "
        "declared by scripts/build_native_server_pack.py's pin tables"
    )

    main_rs_path = _main_rs_optional_verified_if_present_path()
    assert main_rs_path == native_activation_path, (
        "native_activation.rs's OPTIONAL_VERIFIED_IF_PRESENT_RUNTIME_FILES and main.rs's "
        "run_native_optional_verified_if_present_checks disagree on the staged tsp.exe path: "
        f"{native_activation_path!r} vs {main_rs_path!r}"
    )


def test_required_staged_runtime_files_never_reintroduces_the_wrong_dependencies_convention() -> (
    None
):
    """Belt-and-suspenders on ``native_activation.rs``: the pre-fix
    ``dependencies/{postgresql,nats,tsduck,node}`` convention -- paths
    nothing ever stages -- must never reappear in the Rust self-test's
    required-file list."""

    required = _required_staged_runtime_files()
    for wrong in _WRONG_LEGACY_PREFIXES:
        assert not any(entry.startswith(wrong) for entry in required), (
            f"REQUIRED_STAGED_RUNTIME_FILES must never re-point at {wrong!r} -- "
            "nothing stages there (this is the exact K1 defect)"
        )


def test_main_rs_pre_activation_checks_never_reintroduces_the_wrong_dependencies_convention() -> (
    None
):
    """The same belt-and-suspenders check, applied to ``main.rs``'s
    pre-activation checks list."""

    entries = _main_rs_pre_activation_check_paths()
    for wrong in _WRONG_LEGACY_PREFIXES:
        assert not any(entry.startswith(wrong) for entry in entries), (
            f"main.rs's pre-activation checks must never re-point at {wrong!r} -- "
            "nothing stages there (this is the exact K1 defect)"
        )
