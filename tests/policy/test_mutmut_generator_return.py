# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Mutation instrumentation must preserve generator yields AND return values."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.policy.patch_mutmut_generator_return import (
    patched_record_trampoline_hit,
    patched_source,
)

# Exact mutmut 3.6.0 generator statement, inside a minimal runnable wrapper.
SOURCE = """def wrapper(*args, **kwargs):
    yield from trampoline(*args, **kwargs)  # type: ignore
"""


def test_wrapper_preserves_generator_return_and_send() -> None:
    def original():
        value = yield "prepare"
        return value

    namespace = {"trampoline": original}
    exec(patched_source(SOURCE, version="3.6.0"), namespace)
    steps = namespace["wrapper"]()
    assert next(steps) == "prepare"
    with pytest.raises(StopIteration) as done:
        steps.send(True)
    assert done.value.value is True


def test_wrapper_preserves_immediate_generator_return() -> None:
    def original():
        if False:
            yield
        return True

    namespace = {"trampoline": original}
    exec(patched_source(SOURCE, version="3.6.0"), namespace)
    with pytest.raises(StopIteration) as done:
        next(namespace["wrapper"]())
    assert done.value.value is True


@pytest.mark.parametrize("selected_result", [True, False, None])
def test_wrapper_preserves_selected_dispatch_result(selected_result: bool | None) -> None:
    def selected_implementation():
        if False:
            yield
        return selected_result

    namespace = {"trampoline": selected_implementation}
    exec(patched_source(SOURCE, version="3.6.0"), namespace)
    with pytest.raises(StopIteration) as done:
        next(namespace["wrapper"]())
    assert done.value.value is selected_result


@pytest.mark.parametrize("version", ["3.5.0", "3.6.1", "4.0.0"])
def test_unknown_version_refused(version: str) -> None:
    with pytest.raises(ValueError, match=r"3\.6\.0"):
        patched_source(SOURCE, version=version)


@pytest.mark.parametrize("source", ["", SOURCE + SOURCE, SOURCE.replace("yield from", "yield")])
def test_unknown_or_ambiguous_template_refused(source: str) -> None:
    with pytest.raises(ValueError, match="template"):
        patched_source(source, version="3.6.0")


def test_patch_is_idempotent() -> None:
    fixed = patched_source(SOURCE, version="3.6.0")
    assert "return (yield from" in fixed
    assert patched_source(fixed, version="3.6.0") == fixed


HIT_SOURCE = """
def record_trampoline_hit(name):
    source_paths = [p.resolve(strict=True) for p in Config.get().source_paths]

    if Config.get().max_stack_depth != -1:
        f = inspect.currentframe()
        c = Config.get().max_stack_depth
        while c and f:
            filename = f.f_code.co_filename
            f = f.f_back
            if "pytest" in filename or "hammett" in filename or "unittest" in filename:
                break
            file_path = Path(filename).resolve(strict=True)
            if any(path in file_path.parents for path in source_paths):
                c -= 1
        if not c:
            return
    mutmut._stats.add(name)
"""


@pytest.fixture
def mutmut_source_dir():
    with tempfile.TemporaryDirectory(prefix="mutmut-frame-") as directory:
        path = Path(directory)
        assert not any(token in str(path).lower() for token in ("pytest", "hammett", "unittest"))
        yield path


def _exec_patched_record_trampoline_hit(namespace):
    exec(patched_record_trampoline_hit(HIT_SOURCE, version="3.6.0"), namespace)
    return namespace["record_trampoline_hit"]


def test_disabled_depth_records_hit_without_resolving():
    source_mock = Mock()
    source_mock.resolve.side_effect = AssertionError("resolve should not run for depth=-1")
    config_mock = Mock()
    config_mock.get.return_value = SimpleNamespace(max_stack_depth=-1, source_paths=[source_mock])
    inspect_mock = Mock()
    inspect_mock.currentframe.side_effect = AssertionError(
        "currentframe should not run for depth=-1"
    )
    stats = set()
    namespace = {
        "Config": config_mock,
        "inspect": inspect_mock,
        "Path": Path,
        "mutmut": SimpleNamespace(_stats=stats),
    }

    fn = _exec_patched_record_trampoline_hit(namespace)
    fn("disabled_hit")

    assert stats == {"disabled_hit"}


def test_finite_depth_one_exhausted_leaves_stats_empty(mutmut_source_dir):
    source_file = mutmut_source_dir / "source.py"
    source_file.write_text("")
    source_mock = Mock()
    source_mock.resolve.return_value = mutmut_source_dir
    config_mock = Mock()
    config_mock.get.return_value = SimpleNamespace(max_stack_depth=1, source_paths=[source_mock])
    fake_frame = SimpleNamespace(
        f_code=SimpleNamespace(co_filename=str(source_file)),
        f_back=None,
    )
    inspect_mock = Mock()
    inspect_mock.currentframe.return_value = fake_frame
    stats = set()
    namespace = {
        "Config": config_mock,
        "inspect": inspect_mock,
        "Path": Path,
        "mutmut": SimpleNamespace(_stats=stats),
    }

    fn = _exec_patched_record_trampoline_hit(namespace)
    fn("depth_one_hit")

    assert stats == set()
    source_mock.resolve.assert_called_once_with(strict=True)


def test_finite_depth_two_with_pytest_break_records_hit(mutmut_source_dir):
    source_file = mutmut_source_dir / "source.py"
    source_file.write_text("")
    source_mock = Mock()
    source_mock.resolve.return_value = mutmut_source_dir
    config_mock = Mock()
    config_mock.get.return_value = SimpleNamespace(max_stack_depth=2, source_paths=[source_mock])
    pytest_frame = SimpleNamespace(
        f_code=SimpleNamespace(co_filename="pytest/runner.py"),
        f_back=None,
    )
    source_frame = SimpleNamespace(
        f_code=SimpleNamespace(co_filename=str(source_file)),
        f_back=pytest_frame,
    )
    inspect_mock = Mock()
    inspect_mock.currentframe.return_value = source_frame
    stats = set()
    namespace = {
        "Config": config_mock,
        "inspect": inspect_mock,
        "Path": Path,
        "mutmut": SimpleNamespace(_stats=stats),
    }

    fn = _exec_patched_record_trampoline_hit(namespace)
    fn("depth_two_hit")

    assert stats == {"depth_two_hit"}
    source_mock.resolve.assert_called_once_with(strict=True)
