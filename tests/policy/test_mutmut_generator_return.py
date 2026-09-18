# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Mutation instrumentation must preserve generator yields AND return values."""

import pytest

from scripts.policy.patch_mutmut_generator_return import patched_source

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
