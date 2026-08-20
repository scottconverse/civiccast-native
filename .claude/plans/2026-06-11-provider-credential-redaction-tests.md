# Provider Credential Redaction Tests (issue #122 close-out) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Close the remaining gap on #122: explicit tests that the three real provider adapters (Internet Archive, YouTube, SMTP) can never echo credential values through error paths, object reprs, or the provider-readiness surface — plus the one real scrub this exposes (dataclass auto-`repr` leaks secrets).

**Architecture:** A new test class `TestCredentialRedaction` in `tests/platform/test_real_providers.py` (same MockTransport/loopback patterns as the existing contract tests) plus a readiness-without-secret-values API test in `tests/installer/test_installer_api.py`. Production change: `field(repr=False)` on every secret-bearing settings field, so accidental `repr()`/f-string logging of a settings object cannot leak.

**Verified gap (code-read 2026-06-11):** `InternetArchiveSettings`, `YouTubeSettings`, `SmtpSettings` are plain frozen dataclasses — `repr(settings)` today prints `access_key='...'`, `client_secret='...'`, `password='...'` verbatim. No redaction tests exist in `tests/platform/test_real_providers.py` (grep for redaction/caplog: empty).

**Branch:** `work/provider-redaction-tests` from `main`.

---

### Task 1: Redaction tests (failing first)

**Files:**
- Test: `tests/platform/test_real_providers.py` (append `TestCredentialRedaction`)

- [ ] **Step 1: Write the failing tests**

```python
class TestCredentialRedaction:
    """#122: no credential value may surface through reprs or error paths."""

    def test_settings_reprs_never_contain_secret_values(self) -> None:
        ia = InternetArchiveSettings(access_key="ia-access-sentinel", secret_key="ia-secret-sentinel")
        yt = YouTubeSettings(
            client_id="yt-client-id",
            client_secret="yt-secret-sentinel",
            refresh_token="yt-refresh-sentinel",
        )
        smtp = SmtpSettings(
            host="relay.example", from_address="clerk@example.gov",
            username="mailer", password="smtp-secret-sentinel",
        )
        for rendered in (repr(ia), str(ia)):
            assert "ia-access-sentinel" not in rendered
            assert "ia-secret-sentinel" not in rendered
        for rendered in (repr(yt), str(yt)):
            assert "yt-secret-sentinel" not in rendered
            assert "yt-refresh-sentinel" not in rendered
        for rendered in (repr(smtp), str(smtp)):
            assert "smtp-secret-sentinel" not in rendered

    def test_internet_archive_error_path_never_echoes_keys(self) -> None:
        client = InternetArchiveClient(
            InternetArchiveSettings(access_key="ia-access-sentinel", secret_key="ia-secret-sentinel"),
            transport=httpx.MockTransport(lambda _: httpx.Response(403, text="denied")),
        )
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            client.upload(asset_id="meeting-42", payload=b"x")
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "ia-access-sentinel" not in rendered
        assert "ia-secret-sentinel" not in rendered

    def test_youtube_token_error_path_never_echoes_oauth_secrets(self) -> None:
        client = YouTubeClient(
            YouTubeSettings(
                client_id="yt-client-id",
                client_secret="yt-secret-sentinel",
                refresh_token="yt-refresh-sentinel",
            ),
            transport=httpx.MockTransport(lambda _: httpx.Response(401, text="invalid_grant")),
        )
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            client.publish_live(asset_id="meeting-42")
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "yt-secret-sentinel" not in rendered
        assert "yt-refresh-sentinel" not in rendered

    def test_smtp_login_error_path_never_echoes_password(self) -> None:
        class _RefusingSmtp:
            def __init__(self, *_args: object, **_kwargs: object) -> None: ...
            def __enter__(self) -> "_RefusingSmtp": return self
            def __exit__(self, *_exc: object) -> None: ...
            def ehlo(self) -> None: ...
            def starttls(self) -> None: ...
            def login(self, username: str, password: str) -> None:
                raise smtplib.SMTPAuthenticationError(535, b"authentication failed for " + username.encode())
            def send_message(self, _message: object) -> None:
                raise AssertionError("send_message must not be reached after failed login")

        mailbox = SmtpMailbox(
            SmtpSettings(
                host="relay.example", from_address="clerk@example.gov",
                username="mailer", password="smtp-secret-sentinel",
            ),
            smtp_factory=lambda _host, _port: _RefusingSmtp(),  # type: ignore[arg-type,return-value]
        )
        with pytest.raises(smtplib.SMTPAuthenticationError) as excinfo:
            mailbox.send_confirmation(email="resident@example.gov", confirmation_url="https://x/c/1")
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "smtp-secret-sentinel" not in rendered
```

(add `import smtplib` to the test-file imports.)

- [ ] **Step 2: Run, expect the repr test to FAIL** (dataclass auto-repr leaks); error-path tests may already pass — that is fine, they pin the behavior.

Run: `pytest tests/platform/test_real_providers.py::TestCredentialRedaction -q`

- [ ] **Step 3: Scrub — `field(repr=False)` on secret fields**

`civiccast/archive/internet_archive.py`: `access_key: str = field(repr=False)`, `secret_key: str = field(repr=False)` (add `field` to the dataclasses import).
`civiccast/syndicate/youtube.py`: `client_secret: str = field(repr=False)`, `refresh_token: str = field(repr=False)`.
`civiccast/subscribe/smtp.py`: `password: str | None = field(default=None, repr=False)`.
(Keep field order/defaults valid for dataclass rules.)

- [ ] **Step 4: Run the whole file**

Run: `pytest tests/platform/test_real_providers.py -q` — ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/platform/test_real_providers.py civiccast/archive/internet_archive.py civiccast/syndicate/youtube.py civiccast/subscribe/smtp.py
git commit -s -m "test(providers): credential redaction proof + repr scrub for IA/YouTube/SMTP settings (closes #122 gap)"
```

### Task 2: Readiness-without-secret-values check

**Files:**
- Test: `tests/installer/test_installer_api.py` (append)

- [ ] **Step 1: Write the test** — set sentinel env secrets, call the readiness endpoint, assert no sentinel appears anywhere in the serialized response:

```python
def test_provider_readiness_never_echoes_secret_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    sentinels = {
        "CIVICCAST_IA_ACCESS_KEY": "ia-access-sentinel",
        "CIVICCAST_IA_SECRET_KEY": "ia-secret-sentinel",
        "CIVICCAST_YOUTUBE_CLIENT_ID": "yt-client-id-sentinel",
        "CIVICCAST_YOUTUBE_CLIENT_SECRET": "yt-secret-sentinel",
        "CIVICCAST_YOUTUBE_REFRESH_TOKEN": "yt-refresh-sentinel",
        "CIVICCAST_SMTP_HOST": "relay.example",
        "CIVICCAST_SMTP_FROM": "clerk@example.gov",
        "CIVICCAST_SMTP_USERNAME": "mailer-sentinel",
        "CIVICCAST_SMTP_PASSWORD": "smtp-secret-sentinel",
    }
    for name, value in sentinels.items():
        monkeypatch.setenv(name, value)
    client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

    response = client.get("/api/staff/installer/provider-readiness")

    assert response.status_code == 200
    for name, value in sentinels.items():
        if name in ("CIVICCAST_SMTP_HOST", "CIVICCAST_SMTP_FROM"):
            continue  # operator-visible config, not credentials
        assert value not in response.text, f"{name} value leaked into provider readiness"
```

- [ ] **Step 2: Run** — expected PASS (pins the surface); if it fails, that is a real leak: scrub it in `build_provider_readiness_report` before proceeding.

- [ ] **Step 3: Full installer + platform suites** — `pytest tests/installer tests/platform -q` ALL PASS.

- [ ] **Step 4: Commit, push, PR, merge** (same flow as prior PRs; reference issue #122 with `closes #122` in the PR body).

---

## Self-review
- #122's left-to-do was: redaction tests + readiness-without-secret-values check + scrub echo paths. Task 1 covers tests + the one real echo path found (dataclass repr); Task 2 covers readiness. Error-path tests pin str/repr of raised exceptions for all three adapters.
