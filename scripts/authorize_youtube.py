#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""IT setup helper: obtain a YouTube refresh token through desktop PKCE consent."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from civiccast.installer.service import _restrict_secret_file

SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


def authorize(client_path: Path, output: Path, account: str) -> bool:
    """Keep codes/tokens off stdout; write only a new, access-restricted file."""
    if output.exists():
        raise ValueError("Output already exists; choose a new file to preserve it.")
    client = json.loads(client_path.read_text(encoding="utf-8"))["installed"]
    client_id, client_secret = client["client_id"], client["client_secret"]
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    result: dict[str, bool] = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            # Default request logging would expose the authorization code.
            pass

        def do_GET(self) -> None:
            request = urlsplit(self.path)
            query = parse_qs(request.query)
            if request.path != "/callback" or not secrets.compare_digest(
                query.get("state", [""])[0], state
            ):
                self.send_error(400, "Invalid authorization response")
                return
            result["ok"] = False
            if query.get("code") and not query.get("error"):
                try:
                    response = httpx.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "code": query["code"][0],
                            "code_verifier": verifier,
                            "redirect_uri": redirect,
                            "grant_type": "authorization_code",
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    token = response.json()
                    refresh = token.get("refresh_token")
                    if not refresh or SCOPE not in token.get("scope", "").split():
                        raise ValueError("Required permission or refresh token missing.")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    # Restrict the empty file BEFORE writing any credentials.
                    # Exclusive creation preserves any existing credential file.
                    with output.open("x", encoding="utf-8", newline="\n") as file:
                        try:
                            _restrict_secret_file(output)
                            json.dump(
                                {
                                    "client_id": client_id,
                                    "client_secret": client_secret,
                                    "refresh_token": refresh,
                                },
                                file,
                                indent=2,
                            )
                            file.write("\n")
                        except Exception:
                            file.close()
                            output.unlink(missing_ok=True)
                            raise
                    result["ok"] = True
                except Exception:
                    # Never print provider exception bodies or credential values.
                    print("Authorization failed; no credentials logged.", flush=True)
            body = (
                "CivicCast YouTube authorization "
                + ("complete. Return to the setup helper." if result["ok"] else "failed.")
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    with http.server.HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/callback"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge.decode().rstrip("="),
                "code_challenge_method": "S256",
                "login_hint": account,
            }
        )
        if not webbrowser.open(url):
            raise RuntimeError("Could not open the system browser.")
        print("Complete Google consent in your browser within 10 minutes.", flush=True)
        deadline = time.monotonic() + 600
        while not result and time.monotonic() < deadline:
            server.handle_request()
    return result.get("ok", False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--account", required=True, help="Station's Google email address")
    args = parser.parse_args()
    try:
        if authorize(args.client_json, args.output, args.account):
            print("Saved protected credentials. Enter their three fields in Setup > YouTube.")
            return 0
    except (Exception, KeyboardInterrupt):
        pass
    print("Not authorized. Check client type, test-user access and browser consent; retry.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
