# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Exercise setup-helper callback security without contacting Google."""

from __future__ import annotations

import importlib.util
import json
import threading
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "youtube_authorize_helper", Path(__file__).parents[1] / "scripts/authorize_youtube.py"
)
assert _SPEC is not None and _SPEC.loader is not None
helper = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helper)


@pytest.mark.parametrize("outcome", ["success", "missing-scope", "declined"])
def test_callback_validates_state_scope_and_protects_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: str,
) -> None:
    client = tmp_path / "client.json"
    client.write_text(
        json.dumps({"installed": {"client_id": "fake-client", "client_secret": "fake-secret"}})
    )
    output = tmp_path / "authorized.json"
    requests = []
    workers = []
    errors = []
    protected = []

    def protect(path: Path) -> None:
        # The file must be empty while permission changes are applied.
        protected.append(path.read_text())

    def exchange(url: str, *, data: dict[str, str], timeout: int) -> httpx.Response:
        requests.append(data)
        assert url == "https://oauth2.googleapis.com/token"
        assert timeout == 30
        assert len(data["code_verifier"]) >= 43
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "refresh_token": "fake-refresh",
                "scope": helper.SCOPE if outcome == "success" else "",
            },
        )

    def browser(url: str) -> bool:
        auth = parse_qs(urlsplit(url).query)
        callback = urlsplit(auth["redirect_uri"][0])
        assert auth["code_challenge_method"] == ["S256"]
        assert auth["access_type"] == ["offline"]

        def send() -> None:
            try:
                connection = HTTPConnection(callback.hostname, callback.port, timeout=10)
                connection.request("GET", callback.path + "?state=wrong&code=untrusted")
                response = connection.getresponse()
                assert response.status == 400
                response.read()
                assert not requests
                query = {"state": auth["state"][0]}
                query.update(
                    {"error": "access_denied"} if outcome == "declined" else {"code": "fake-code"}
                )
                connection.request("GET", callback.path + "?" + urlencode(query))
                response = connection.getresponse()
                assert response.status == 200
                response.read()
                connection.close()
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=send)
        workers.append(worker)
        worker.start()
        return True

    monkeypatch.setattr(helper, "_restrict_secret_file", protect)
    monkeypatch.setattr(helper.httpx, "post", exchange)
    monkeypatch.setattr(helper.webbrowser, "open", browser)
    assert helper.authorize(client, output, "station@example.org") is (outcome == "success")
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()
    assert not errors
    if outcome == "success":
        assert protected == [""]
        assert json.loads(output.read_text())["refresh_token"] == "fake-refresh"
    else:
        assert not output.exists()
        assert not protected
    captured = capsys.readouterr()
    assert all(
        secret not in captured.out + captured.err
        for secret in ("fake-code", "fake-refresh", "fake-secret")
    )


def test_existing_credentials_are_preserved(tmp_path: Path) -> None:
    output = tmp_path / "authorized.json"
    output.write_text("original")
    with pytest.raises(ValueError, match="already exists"):
        helper.authorize(tmp_path / "unused-client.json", output, "station@example.org")
    assert output.read_text() == "original"
