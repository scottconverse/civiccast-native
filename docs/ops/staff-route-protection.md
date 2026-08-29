# Staff Route Protection

> **TL;DR.** CivicCast post-v1.0 hardening adds first-party bearer-token authentication on `/api/staff/*`, while still requiring loopback binding (`127.0.0.1`) or an authenticating reverse proxy for network and TLS policy. Missing or invalid bearer tokens receive `401 Unauthorized`. Signed-record exports bind the audit fingerprint to the server-verified bearer-token identity, not to operator identity fields supplied by the request body.

This document is the canonical deployment-hardening reference for the operator-only routes in CivicCast. It is referenced from `README.md`, `SECURITY.md`, and the runtime startup reminder logged by `civiccast.app:create_app`.

First-party bearer auth is an identity layer. It does not replace network protection, TLS termination, or proxy policy.

## What Is Exposed

The staff routers mount these operator endpoints:

| Method | Path | Effect |
| :----- | :--- | :----- |
| POST | `/api/staff/assets/upload` | Upload a recorded media file. |
| POST | `/api/staff/assets` | Create an asset row directly. |
| GET | `/api/staff/assets` | List all assets, including not-yet-validated and rejected. |
| GET | `/api/staff/assets/{asset_id}` | Read asset metadata. |
| PATCH | `/api/staff/assets/{asset_id}` | Update title, description, trim, chapters, retention. |
| POST | `/api/staff/schedule` | Create a scheduled premiere or embargo. |
| GET | `/api/staff/schedule` | List scheduled premieres and embargoes. |
| GET | `/api/staff/schedule/{schedule_id}` | Read one scheduled item. |
| POST | `/api/staff/schedule/{schedule_id}/cancel` | Cancel a scheduled item. |
| POST | `/api/staff/live/sessions` | Create an operator live session. |
| POST | `/api/staff/live/sessions/{id}/start-preflight` | Move a live session into pre-flight. |
| POST | `/api/staff/live/sessions/{id}/preflight` | Run the live pre-flight checklist. |
| POST | `/api/staff/live/sessions/{id}/go-on-air` | Start the live stream. |
| POST | `/api/staff/live/sessions/{id}/end-broadcast` | End the live broadcast. |
| POST | `/api/staff/live/sources` | Create a live source descriptor. |
| GET | `/api/staff/live/sources` | List live source descriptors. |
| POST | `/api/staff/live/recording-targets` | Create a recording target. |
| GET | `/api/staff/live/recording-targets` | List recording targets. |
| GET | `/api/staff/summaries/review-items` | List sourced summary drafts awaiting operator review. |
| POST | `/api/staff/summaries/generate` | Generate a sourced summary from committed transcript cues. |
| POST | `/api/staff/summaries/transcript.csv` | Export committed transcript cues as CSV. |
| POST | `/api/staff/summaries/{id}/approve` | Approve a sourced summary for signed-record export. |
| POST | `/api/staff/records` | Export a signed-record PDF/A-3B artifact from an approved summary. |
| GET | `/api/staff/records/{id}/download` | Download the signed-record PDF artifact. |
| GET | `/api/staff/records/{id}/verify` | Verify signed-record metadata. |
| POST | `/api/staff/podcast/episodes` | Generate a podcast episode from an approved asset. |
| POST | `/api/staff/subscribe/dispatch-test` | Dispatch deterministic local subscriber notification proofs. |

These routes now require a staff bearer token at the application layer. Deployments must still keep the API on loopback or behind a reverse proxy so the bearer-token layer is not the only public-network control.

### Deliberately unauthenticated routes

`/health`, `/api/version`, `/api/hardware`, `/api/public/*`, `/docs` and
`/openapi.json` answer without a token. That is a design choice, not an
oversight: the installer sizes a deployment and confirms the service is running
before a station or any staff token exists.

Because they are public, what they disclose is a deliberate contract:

| Route | Discloses | Deliberately does NOT disclose |
| :---- | :-------- | :----------------------------- |
| `/health` | Version, schema currency, readiness | Anything about the host |
| `/api/version` | Version string | — |
| `/api/hardware` | CPU cores/brand, total and free RAM, GPU/VRAM, OS kind/release/architecture, network hostname, disk **volume** and its size | The operating-system account name. The disk path is reduced to its volume anchor (`C:\` / `/`); it used to be the probed home directory, which named the logged-in user to any caller. |

The **hostname** is disclosed on purpose — it is how a person tells one station
from another. It is a machine name, not an account name, and CivicCast does not
derive it from the logged-in user. If a station is named after a person
(`scotts-pc`), that name is public on this endpoint; rename the host, or put the
API behind the reverse proxy this document already requires.

`civiccast doctor` still prints the real probed path — it runs on the box, for
the person who owns it. The redaction applies to the public HTTP surface only,
and `tests/test_hardware_disclosure.py` pins it there.

## Identity Protection

Each staff request must include:

```http
Authorization: Bearer <staff-token>
```

The app verifies the token before dispatching the request to any `/api/staff/*` handler and stores the verified operator identity on `request.state.operator_identity`. Summary approvals and signed-record exports use that server-owned identity for audit fingerprints; request payloads cannot choose the operator identity that the audit chain records.

For the standard standalone setup path, the operator console Setup screen
prepares durable local storage, applies migrations, creates the first admin,
and generates the printable recovery kit. `/api/setup/*` is admitted by
loopback alone (the control plane binds `127.0.0.1` only, so it is
unreachable from the network by construction); open the console from the
station itself before choosing **Prepare storage**.

The lifecycle CLI remains the technical-administrator override and recovery
path for scripted deployments. Use it only after storage is already configured
through managed local setup or `DATABASE_URL`:

```bash
uv run alembic upgrade head
uv run civiccast token issue --operator-id operator-1 --display-name "Operator One"
```

The command prints the bearer value once. Store it in the operator's credential
manager, or ask CivicCast to store it in the OS credential store:

```bash
uv run civiccast token issue --operator-id operator-1 --display-name "Operator One" --save-keyring
```

Use lifecycle commands for routine operations:

```bash
uv run civiccast token list
uv run civiccast token revoke <token-id> --reason "operator offboarded"
uv run civiccast token rotate <token-id> --save-keyring
```

The database stores a per-token salt, PBKDF2-SHA256 hash, issued-at timestamp,
last-used-at timestamp, revocation timestamp, revocation reason, rotation
lineage, scopes, and append-only audit rows for issue/use/revoke/rotate events.

If no database-backed lifecycle store is configured, staff routes fail closed
unless an explicit legacy environment-token configuration is provided:

```bash
TOKEN="$(civiccast token generate-env)"
export CIVICCAST_STAFF_TOKENS="$TOKEN:operator-1:Operator One:meeting_operator"
```

The value is a semicolon-separated list of
`token:operator_id:display_name:role[,role...]` entries. Generate each bearer
secret with `civiccast token generate-env`. Startup enforces the current
versioned shape and rejects obvious low-complexity values, but string validation
cannot prove randomness; operators must use the generator. This compatibility
path does not provide database-backed revocation,
rotation, last-used tracking, or lifecycle audit rows. If neither the lifecycle
store nor the compatibility environment is configured, staff routes fail closed
with `401 Unauthorized`. CivicCast does not enable any public default operator
token in normal runtime. The deterministic `operator-token-a` fixture is available
only when tests explicitly opt in with
`CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN=1`; that test-only switch also permits
short fixture tokens and must never be enabled at a station.

## Network Protection

### A. Loopback Only

Bind FastAPI to `127.0.0.1` only. Reach the operator console from the same host, or through an SSH tunnel.

```bash
uv run uvicorn civiccast.app:app --host 127.0.0.1 --port 8000
```

To suppress the runtime startup reminder once you have confirmed loopback binding:

```bash
CIVICCAST_AUTH_ACK=1 uv run uvicorn civiccast.app:app --host 127.0.0.1 --port 8000
```

The `CIVICCAST_AUTH_ACK` env var only suppresses the log line. It does not mint tokens, configure TLS, or configure proxy auth.

## Failed-Authentication Throttling

Staff bearer authentication allows ten failed verifications per observed peer
IP in a 60-second sliding window by default. The first ten failures return
`401`. After the budget is exhausted, exact full-token misses receive `429`
with `Retry-After` without expensive verification and without entering a queue.
Exact full-token matches bypass the failed-guess control, so valid tokens remain
accepted even when an operator shares a proxy or NAT with a noisy client.

Tune the budget with `CIVICCAST_AUTH_RATE_LIMIT` and the window with
`CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS`.
The key covers all `/api/staff/*` routes for one direct peer; changing token
text or paths does not create a fresh budget.

The limiter is process-local and intentionally ignores forwarded-address
headers. Behind a reverse proxy, CivicCast observes the proxy as its peer.
Configure the proxy's trusted-client-address handling before keying any ingress
limit by client address; never trust a public `X-Forwarded-For` value directly.
Also bound staff-route request rate and connections at ingress. The in-process
budget does not aggregate multiple CivicCast workers or distributed source IPs.

Lifecycle tokens issued by this version retain the salted PBKDF2 hash as the
authoritative verifier and also store a SHA-256 fingerprint of the generated
high-entropy full secret for exact admission. An active lifecycle token issued
before fingerprint support must be rotated once from the host:

```bash
uv run civiccast token rotate <token-id> --save-keyring
```

Use the newly printed secret. CivicCast rejects the legacy active token with
this rotation instruction when the peer still has failure budget; an already
saturated peer receives `429` first and should honor `Retry-After`. Rotation can
always be performed directly from the host. CivicCast never treats the public
token ID as proof that a secret is valid.

For nginx that directly observes client connections, a starting point in the
`http` context is:

```nginx
limit_req_zone $binary_remote_addr zone=civiccast_staff:10m rate=5r/s;
limit_conn_zone $binary_remote_addr zone=civiccast_staff_conn:10m;
```

Then add these controls to the authenticated `/api/staff/` location:

```nginx
limit_req zone=civiccast_staff burst=10 nodelay;
limit_conn civiccast_staff_conn 10;
```

Adjust these values to measured operator-console traffic. If another proxy or
load balancer sits in front of nginx, establish its trusted real-IP module
configuration first or the limit will collapse every caller into one key.

### B. Reverse Proxy

Front the FastAPI app with `nginx`, `Traefik`, `Caddy`, or another reverse proxy that enforces network-layer policy on `/api/staff/*` and, if desired, `/docs` and `/redoc`. The proxy can use HTTP basic auth, mTLS, an OIDC/OAuth integration, or a session cookie scheme. The CivicCast bearer token remains required by the application after the proxy passes the request through.

A minimal `nginx` example for HTTP basic auth on the staff routes:

```nginx
server {
    listen 443 ssl http2;
    server_name civiccast.example.org;

    location ~ ^/(api/public|api/version|api/hardware|health|docs|openapi.json) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/staff/ {
        auth_basic "CivicCast Operator";
        auth_basic_user_file /etc/nginx/htpasswd-civiccast;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

When fronted by a proxy, bind FastAPI to loopback so only the proxy can reach it:

```bash
CIVICCAST_AUTH_ACK=1 uv run uvicorn civiccast.app:app --host 127.0.0.1 --port 8000
```

## What Not To Do

- Do not run `uvicorn civiccast.app:app --host 0.0.0.0 --port 8000` on a publicly-routable host without a proxy.
- Do not set `CIVICCAST_AUTH_ACK=1` to make the warning go away on a host bound to `0.0.0.0` with no proxy. The deployment is unsafe even with bearer-token auth.
- Do not rely on obscurity such as a non-default port or an unadvertised hostname.

## Reporting

If you discover that a CivicCast deployment is exposing `/api/staff/*` to the public internet without auth, please:

1. Stop the server.
2. Apply loopback binding or reverse-proxy protection from this document.
3. If you suspect the exposure was abused, see `SECURITY.md` for the vulnerability-reporting flow.
