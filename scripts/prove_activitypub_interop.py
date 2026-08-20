#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Run a controlled ActivityPub interoperability proof with GoToSocial.

The proof intentionally keeps production SSRF guardrails intact. Local HTTP and
loopback targets are accepted only inside this script by calling the ActivityPub
remote parser with its explicit lab allowances.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import BaseServer
from typing import Literal
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import BaseModel, ConfigDict, Field

from civiccast.activitypub.keys import public_key_pem_from_private_key
from civiccast.activitypub.remote import ActivityPubRemoteError, remote_actor_from_document
from civiccast.activitypub.signatures import signed_request_headers

ROOT = Path(__file__).resolve().parent.parent
RUN_ID = "2026-05-21-activitypub-product-completion"
DEFAULT_EVIDENCE_DIR = ROOT / ".agent-runs" / RUN_ID / "evidence"
DEFAULT_IMAGE = "superseriousbusiness/gotosocial:latest"
DEFAULT_PORT = 18080
DEFAULT_LOCAL_ACTOR_PORT = 18090

InteropStatus = Literal["planned", "blocked", "passed"]
StepStatus = Literal["planned", "blocked", "passed"]


class InteropStep(BaseModel):
    """One command or network probe in the interop proof."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    status: StepStatus
    command: str = Field(min_length=1)
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    evidence: str = ""


class InteropProofResult(BaseModel):
    """Machine-readable ActivityPub interop proof evidence."""

    model_config = ConfigDict(extra="forbid")

    status: InteropStatus
    image: str
    generated_at_unix: int
    live_follow_exercised: bool = False
    proof_level: Literal["planned", "real_actor_document", "blocked"]
    steps: list[InteropStep]


def run_command(
    args: list[str],
    *,
    name: str,
    timeout: int,
    command_display: str | None = None,
) -> InteropStep:
    """Run a command and return sanitized evidence."""

    display = command_display or " ".join(args)
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return InteropStep(
            name=name,
            status="blocked",
            command=display,
            returncode=1,
            stderr=str(exc),
            evidence=str(exc),
        )
    stdout = clean_output(proc.stdout)
    stderr = clean_output(proc.stderr)
    return InteropStep(
        name=name,
        status="passed" if proc.returncode == 0 else "blocked",
        command=display,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        evidence=stdout
        or stderr
        or ("command passed" if proc.returncode == 0 else "command failed"),
    )


def clean_output(value: str) -> str:
    """Trim command output without leaking control characters into evidence."""

    return value.replace("\x00", "").strip()[:4000]


def plan(image: str) -> InteropProofResult:
    return InteropProofResult(
        status="planned",
        image=image,
        generated_at_unix=int(time.time()),
        proof_level="planned",
        steps=[
            InteropStep(
                name="docker-version",
                status="planned",
                command="docker version --format {{.Server.Version}}",
                evidence="Checks local Docker daemon availability.",
            ),
            InteropStep(
                name="gotosocial-container",
                status="planned",
                command=f"docker run {image}",
                evidence="Starts a disposable GoToSocial container on 127.0.0.1.",
            ),
            InteropStep(
                name="gotosocial-actor",
                status="planned",
                command="GET /users/civiccastpeer",
                evidence="Fetches a real GoToSocial actor document and parses it with CivicCast lab-mode remote actor validation.",
            ),
        ],
    )


def execute(
    image: str,
    evidence_dir: Path,
    port: int,
    local_actor_port: int,
    *,
    pull: bool,
) -> InteropProofResult:
    steps: list[InteropStep] = []
    container = f"civiccast-ap-interop-{int(time.time())}"
    docker = run_command(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        name="docker-version",
        timeout=30,
    )
    steps.append(docker)
    if docker.status != "passed":
        return _write_result(evidence_dir, image, steps, "blocked", "blocked")

    if pull:
        pull_step = run_command(["docker", "pull", image], name="docker-pull", timeout=300)
        steps.append(pull_step)
        if pull_step.status != "passed":
            return _write_result(evidence_dir, image, steps, "blocked", "blocked")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    local_actor_url = f"http://host.docker.internal:{local_actor_port}/ap/actor"
    with _local_actor_server(
        port=local_actor_port,
        actor_url=local_actor_url,
        public_key_pem=public_key_pem_from_private_key(key),
    ) as server_step:
        steps.append(server_step)
        if server_step.status != "passed":
            return _write_result(evidence_dir, image, steps, "blocked", "blocked")
        run_step = run_command(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                container,
                "--add-host=host.docker.internal:host-gateway",
                "-p",
                f"127.0.0.1:{port}:8080",
                "-e",
                f"GTS_HOST=localhost:{port}",
                "-e",
                f"GTS_ACCOUNT_DOMAIN=localhost:{port}",
                "-e",
                "GTS_PROTOCOL=http",
                "-e",
                "GTS_DB_TYPE=sqlite",
                "-e",
                "GTS_DB_ADDRESS=/gotosocial/storage/sqlite.db",
                "-e",
                "GTS_LETSENCRYPT_ENABLED=false",
                "-e",
                "GTS_HTTP_CLIENT_ALLOW_IPS=0.0.0.0/0,::/0",
                "-e",
                "GTS_HTTP_CLIENT_INSECURE_OUTGOING=true",
                image,
            ],
            name="gotosocial-container-start",
            timeout=60,
        )
        steps.append(run_step)
        if run_step.status != "passed":
            return _write_result(evidence_dir, image, steps, "blocked", "blocked")
        return _execute_against_running_gotosocial(
            container=container,
            image=image,
            evidence_dir=evidence_dir,
            port=port,
            local_actor_url=local_actor_url,
            private_key=key,
            steps=steps,
        )


def _execute_against_running_gotosocial(
    *,
    container: str,
    image: str,
    evidence_dir: Path,
    port: int,
    local_actor_url: str,
    private_key: rsa.RSAPrivateKey,
    steps: list[InteropStep],
) -> InteropProofResult:
    try:
        steps.append(_wait_for_gotosocial(port))
        if steps[-1].status != "passed":
            return _write_result(evidence_dir, image, steps, "blocked", "blocked")
        password = "cc-" + secrets.token_urlsafe(18)
        create_step = run_command(
            [
                "docker",
                "exec",
                container,
                "/gotosocial/gotosocial",
                "admin",
                "account",
                "create",
                "--username",
                "civiccastpeer",
                "--email",
                "civiccastpeer@example.invalid",
                "--password",
                password,
            ],
            name="gotosocial-account-create",
            timeout=60,
            command_display=(
                "docker exec <container> /gotosocial/gotosocial admin account create "
                "--username civiccastpeer --email civiccastpeer@example.invalid --password <redacted>"
            ),
        )
        steps.append(create_step)
        if create_step.status != "passed":
            return _write_result(evidence_dir, image, steps, "blocked", "blocked")
        confirm_step = run_command(
            [
                "docker",
                "exec",
                container,
                "/gotosocial/gotosocial",
                "admin",
                "account",
                "confirm",
                "--username",
                "civiccastpeer",
            ],
            name="gotosocial-account-confirm",
            timeout=60,
        )
        steps.append(confirm_step)
        if confirm_step.status != "passed":
            return _write_result(evidence_dir, image, steps, "blocked", "blocked")
        fetch_step = _fetch_and_parse_actor(
            port,
            local_actor_url=local_actor_url,
            private_key=private_key,
        )
        steps.append(fetch_step)
        if steps[-1].status == "passed":
            return _write_result(
                evidence_dir,
                image,
                steps,
                "passed",
                "real_actor_document",
            )
        steps.append(_container_logs(container))
        return _write_result(evidence_dir, image, steps, "blocked", "blocked")
    finally:
        cleanup = run_command(
            ["docker", "rm", "-f", container],
            name="cleanup-container",
            timeout=45,
            command_display=f"docker rm -f {container}",
        )
        cleanup_path = evidence_dir / "activitypub-interop-cleanup.json"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        cleanup_path.write_text(cleanup.model_dump_json(indent=2) + "\n", encoding="utf-8")


@contextmanager
def _local_actor_server(
    *,
    port: int,
    actor_url: str,
    public_key_pem: str,
):
    account = f"civiccast-lab@host.docker.internal:{port}"
    document = {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1",
        ],
        "id": actor_url,
        "type": "Application",
        "preferredUsername": "civiccast-lab",
        "inbox": f"{actor_url.rsplit('/ap/actor', 1)[0]}/ap/inbox",
        "outbox": f"{actor_url.rsplit('/ap/actor', 1)[0]}/ap/outbox",
        "publicKey": {
            "id": f"{actor_url}#main-key",
            "owner": actor_url,
            "publicKeyPem": public_key_pem,
        },
    }
    webfinger = {
        "subject": f"acct:{account}",
        "aliases": [actor_url],
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": actor_url,
            }
        ],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/robots.txt":
                self._send_bytes(b"User-agent: *\nAllow: /\n", "text/plain")
                return
            if parsed.path == "/.well-known/webfinger":
                resource = parse_qs(parsed.query).get("resource", [""])[0]
                if resource != f"acct:{account}":
                    self.send_response(404)
                    self.end_headers()
                    return
                self._send_json(webfinger, "application/jrd+json")
                return
            if parsed.path != "/ap/actor":
                self.send_response(404)
                self.end_headers()
                return
            self._send_json(document, "application/activity+json")

        def _send_json(self, payload: dict[str, object], content_type: str) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self._send_bytes(body, content_type)

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server: BaseServer | None = None
    thread: threading.Thread | None = None
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield InteropStep(
            name="local-civiccast-key-server",
            status="passed",
            command=f"serve {actor_url}",
            evidence=(
                "Started lab-only HTTP CivicCast actor, webfinger, and public-key "
                "endpoint for GoToSocial signed fetch verification."
            ),
        )
    except OSError as exc:
        yield InteropStep(
            name="local-civiccast-key-server",
            status="blocked",
            command=f"serve {actor_url}",
            returncode=1,
            evidence=str(exc),
        )
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)


def _wait_for_gotosocial(port: int) -> InteropStep:
    url = f"http://127.0.0.1:{port}/nodeinfo/2.0"
    deadline = time.time() + 90
    last_error = ""
    while time.time() < deadline:
        try:
            response = httpx.get(url, headers={"Host": f"localhost:{port}"}, timeout=5)
            if response.status_code < 500:
                return InteropStep(
                    name="gotosocial-ready",
                    status="passed",
                    command=f"GET {url}",
                    returncode=response.status_code,
                    evidence=f"GoToSocial responded with HTTP {response.status_code}.",
                )
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(2)
    return InteropStep(
        name="gotosocial-ready",
        status="blocked",
        command=f"GET {url}",
        returncode=1,
        evidence=last_error or "GoToSocial did not respond before timeout.",
    )


def _fetch_and_parse_actor(
    port: int,
    *,
    local_actor_url: str,
    private_key: rsa.RSAPrivateKey,
) -> InteropStep:
    url = f"http://localhost:{port}/users/civiccastpeer"
    headers = signed_request_headers(
        method="GET",
        url=url,
        body=b"",
        private_key=private_key,
        key_id=f"{local_actor_url}#main-key",
    )
    headers["Accept"] = "application/activity+json, application/ld+json"
    try:
        response = httpx.get(url, headers=headers, timeout=45, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        return InteropStep(
            name="gotosocial-signed-actor-fetch",
            status="blocked",
            command=f"GET {url}",
            returncode=1,
            evidence=f"Could not fetch GoToSocial actor document: {exc}",
        )
    if not isinstance(payload, dict):
        return InteropStep(
            name="gotosocial-signed-actor-fetch",
            status="blocked",
            command=f"GET {url}",
            returncode=response.status_code,
            evidence="GoToSocial actor response was not a JSON object.",
        )
    actor_id = payload.get("id")
    try:
        actor = remote_actor_from_document(
            payload,
            expected_actor_url=actor_id if isinstance(actor_id, str) else None,
            allow_http=True,
            allow_local=True,
        )
    except ActivityPubRemoteError as exc:
        return InteropStep(
            name="gotosocial-actor-parse",
            status="blocked",
            command=f"parse {url}",
            returncode=1,
            evidence=f"CivicCast rejected the GoToSocial actor document in lab mode: {exc}",
        )
    return InteropStep(
        name="gotosocial-actor-parse",
        status="passed",
        command=f"parse {url}",
        returncode=response.status_code,
        evidence=(
            "CivicCast parsed a real GoToSocial actor document in lab mode: "
            f"actor={actor.actor_id}; inbox={actor.inbox}; key={actor.public_key_id}."
        ),
    )


def _container_logs(container: str) -> InteropStep:
    return run_command(
        ["docker", "logs", "--tail", "160", container],
        name="gotosocial-container-logs",
        timeout=30,
        command_display=f"docker logs --tail 160 {container}",
    )


def _write_result(
    evidence_dir: Path,
    image: str,
    steps: list[InteropStep],
    status: InteropStatus,
    proof_level: Literal["planned", "real_actor_document", "blocked"],
) -> InteropProofResult:
    result = InteropProofResult(
        status=status,
        image=image,
        generated_at_unix=int(time.time()),
        live_follow_exercised=False,
        proof_level=proof_level,
        steps=steps,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "activitypub-interop.json").write_text(
        result.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown(evidence_dir / "activitypub-interop.md", result)
    return result


def _write_markdown(path: Path, result: InteropProofResult) -> None:
    lines = [
        "# ActivityPub interop proof",
        "",
        f"Status: `{result.status}`",
        f"Proof level: `{result.proof_level}`",
        f"GoToSocial image: `{result.image}`",
        f"Live follow exercised: `{str(result.live_follow_exercised).lower()}`",
        "",
        "The automated proof starts a disposable GoToSocial container when Docker is available, creates a local account through the official container CLI, signs the actor fetch through a lab-only CivicCast actor/WebFinger origin, fetches the GoToSocial actor document, and validates it through CivicCast's lab-mode ActivityPub remote actor parser. The script does not record credentials and does not loosen production URL guardrails.",
        "",
        "## Steps",
        "",
    ]
    for step in result.steps:
        lines.extend(
            [
                f"### {step.name}",
                "",
                f"- Status: `{step.status}`",
                f"- Command: `{step.command}`",
                f"- Return code: `{step.returncode}`",
                f"- Evidence: {step.evidence or 'none'}",
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run Docker-backed proof")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="GoToSocial container image")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="localhost port")
    parser.add_argument(
        "--local-actor-port",
        type=int,
        default=DEFAULT_LOCAL_ACTOR_PORT,
        help="host port for the lab-only CivicCast actor key endpoint",
    )
    parser.add_argument("--no-pull", action="store_true", help="do not pull the image")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="directory for evidence JSON/Markdown",
    )
    args = parser.parse_args(argv)

    if not args.execute:
        result = plan(args.image)
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "activitypub-interop.json").write_text(
            result.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        _write_markdown(args.evidence_dir / "activitypub-interop.md", result)
    else:
        result = execute(
            args.image,
            args.evidence_dir,
            args.port,
            args.local_actor_port,
            pull=not args.no_pull,
        )
    print(result.model_dump_json(indent=2))
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
