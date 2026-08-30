# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Timeout contract for the stdlib Ollama client (field evidence 2026-08-29).

Candidate #17 (32GB CPU-only reference station): POST /api/staff/summaries/generate
503'd at ~120.6s (cold) and ~120.2s (warm, model already loaded) even though Ollama's
own /api/completion succeeded and returned a real completion. The client's blanket
120s socket timeout was killing the HTTP read out from under a generation that Ollama
went on to finish -- a completed answer thrown away, not a hung request. These tests
pin the fix: a live generate call gets a much longer socket budget than a cheap
metadata call (/api/tags, /api/version), so a legitimate slow local CPU generation
(measured 94-366s+ on the same hardware class) has room to actually return.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import patch

import pytest

from civiccast.ai_runtime.ollama_client import (
    DEFAULT_GENERATE_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    OllamaRuntimeUnavailableError,
    generate_with_ollama,
    get_ollama_model_manifest,
)


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _ok_response(payload: dict[str, Any]) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


class TestGenerateTimeoutBudget:
    def test_generate_uses_the_long_budget_by_default(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
            captured["timeout"] = timeout
            return _ok_response({"response": "ok"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            text = generate_with_ollama(model="gemma4:e4b", prompt="hello")

        assert text == "ok"
        # The old fixed 120s socket timeout discarded a completion Ollama had
        # already finished computing on real CPU-only hardware (measured
        # 94-366s+). The default must be well above that measured range.
        assert captured["timeout"] == DEFAULT_GENERATE_TIMEOUT_SECONDS
        assert captured["timeout"] >= 300

    def test_generate_honors_an_explicit_override(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
            captured["timeout"] = timeout
            return _ok_response({"response": "ok"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            generate_with_ollama(model="gemma4:e4b", prompt="hello", timeout=900)

        assert captured["timeout"] == 900

    def test_generate_still_raises_the_unified_error_on_a_genuine_timeout(self) -> None:
        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
            raise TimeoutError("timed out")

        with (
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
            pytest.raises(OllamaRuntimeUnavailableError),
        ):
            generate_with_ollama(model="gemma4:e4b", prompt="hello")

    def test_cheap_metadata_calls_keep_the_short_budget(self) -> None:
        # /api/tags and /api/version must still fail fast when Ollama is down --
        # the long generate budget must not leak into the daemon-liveness checks.
        captured: list[float | None] = []

        def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
            captured.append(timeout)
            url = request.full_url
            if url.endswith("/api/tags"):
                return _ok_response(
                    {
                        "models": [
                            {
                                "name": "gemma4:e4b",
                                "digest": "a" * 64,
                                "details": {},
                            }
                        ]
                    }
                )
            return _ok_response({"version": "0.9.0"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            manifest = get_ollama_model_manifest("gemma4:e4b")

        assert manifest.model == "gemma4:e4b"
        assert captured == [DEFAULT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS]
        assert all(t < DEFAULT_GENERATE_TIMEOUT_SECONDS for t in captured)
