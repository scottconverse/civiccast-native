# Security and privacy {#ch-security}

This chapter is for the IT person responsible for who can use CivicCast, what the station exposes to the network, what it records about residents, and how to operate its current beta.11 security controls. It covers sign-in and roles, staff access tokens, the first-admin and recovery model, network exposure, reverse proxies and TLS, the public and staff parts of the web API, subscriber and viewer privacy, data retention, signing and checksums, and security limitations with practical precautions.

Beta.11 was published on 2026-10-08 as a GitHub pre-release for testing, not as a production release. The [current verification record](https://github.com/scottconverse/civiccast-native/blob/main/docs/releases/v1.0.0-beta.11-verification.md) lists package checks and their limits. This manual does not claim the station is hardened for the open internet.

## Before you start

- You need Administrator rights on the station computer, and the Setup admin role in the console for the staff-token API calls.
- Most commands below need the CivicCast command-line program. The installer does not add it to PATH, so use the full path: `<INSTDIR>\runtime\Lib\site-packages\bin\civiccast.exe` (`<INSTDIR>` is the folder CivicCast was installed to). In this chapter `$cc` stands for that path.
- Token commands need the database address in the `DATABASE_URL` environment variable. Read it from the registry value `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl` in an elevated PowerShell window, use it only in that window, and never write it to a file or a ticket, because it contains the database password:

```powershell
$cc = "<INSTDIR>\runtime\Lib\site-packages\bin\civiccast.exe"
$env:DATABASE_URL = (Get-ItemProperty 'HKLM:\SOFTWARE\CivicCast\Native').DatabaseUrl
```

## The security model in one page

- The station is built to be used **on the station computer itself**. The web application and the database both listen on `127.0.0.1` only (verified below). Nothing in the program listens for other computers on its own.
- Anyone who can sign in to the console is a **staff user** with one or more of five roles.
- Every staff action in the web API needs an `Authorization: Bearer <token>` header. There is no username-and-password login for the API itself.
- Residents use the **public** parts of the API, which need no sign-in.
- The Windows service runs as LocalSystem (the most powerful local account). This was accepted by the owner (decision record ADR 0021) and is listed in the limitations below.

## Roles

CivicCast has five staff roles. A token carries one or more of them. The details of which screens each role opens are in [Appendix F](#app-roles) and in [Chapter 2](#ch-signing-in).

| Role id | Label in the console |
| --- | --- |
| `setup_admin` | Setup admin |
| `meeting_operator` | Meeting operator |
| `records_clerk` | Records clerk |
| `publish_operator` | Publish operator |
| `support_admin` | Support admin |

Rules the code enforces:

- The scope words `admin` and `operator` are aliases that grant all five roles.
- A token with no scopes has no roles.
- A request without a token gets HTTP 401 with `Staff identity is required for this action.`
- A request with a token that lacks the needed role gets HTTP 403 with `This action requires one of these CivicCast roles: <role ids>.`
- The console cannot grant roles to people. Roles are decided when a token is issued.

## Manage staff tokens

A **staff token** is a long secret string that a program or script sends to prove it is a particular staff member with particular roles. There are three kinds.

| Kind | Looks like | Where it is stored | How you retire it |
| --- | --- | --- | --- |
| Console token | Created when someone signs in at the console | `station-state.json`, as a salted hash | Sign out, or the station evicts it (see below) |
| Database token | `ccst_<id>_<secret>` | Database. Only a PBKDF2-SHA256 hash (210,000 iterations) plus a SHA-256 fingerprint is kept; the secret is shown once. | `civiccast token revoke` or `rotate` |
| Environment token | `ccenv1_` followed by 43 characters | The `CIVICCAST_STAFF_TOKENS` environment variable | Remove it from the variable and restart the service |

### Issue a database token

1. Open an elevated PowerShell window and set `$cc` and `DATABASE_URL` as shown above.
2. Run:

```powershell
& $cc token issue --operator-id clerk-jones --display-name "Pat Jones" --scopes records_clerk,publish_operator --json
```

`--operator-id` and `--display-name` are required. `--scopes` takes a comma-separated list of role ids or the aliases above; its default is `operator`, which is all five roles. Give people only the roles they need. `--save-keyring` stores the token in the Windows credential store under the service name `civiccast.staff-token`. `--json` prints machine-readable output.

3. Copy the secret that is printed. It is printed once and cannot be shown again. Deliver it to its owner through a channel you trust, not through the same ticket that names the person.
4. Check it works. In PowerShell, on the station:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/staff/auth/me -Headers @{ Authorization = "Bearer <the token>" }
```

You should see the operator's name and roles.

### List, revoke and rotate

- `& $cc token list` shows token metadata (never secrets). Add `--json` for scripts.
- `& $cc token revoke <token_id> --reason "left the clerk's office"` makes the token fail from then on. `--reason` defaults to `operator-requested` and is saved in the audit record. `<token_id>` is the public id shown by `token list`.
- `& $cc token rotate <token_id>` revokes that token and issues a replacement for the same operator with the same scopes. It prints the new secret once. `--save-keyring` saves it to the credential store.

The database records audit events for `issued`, `used`, `revoked` and `rotated`.

> **Known issue (beta.11):** A database token issued before the fingerprint was introduced cannot be matched. If `token list` shows a token that no longer authenticates after an upgrade, rotate it.

### Environment tokens

Generate one with `& $cc token generate-env`. To use it, add it to `CIVICCAST_STAFF_TOKENS` in the service environment (see [Chapter 12](#ch-operations)) in the form `token:operator_id:Display Name:role[,role]`, with several entries separated by semicolons (`;`), and restart the service. Roles are required: an entry with no role stops the station from starting.

> **Known issue (beta.11):** On a station that has its database (every native station), the code checks database and console tokens first and accepts an environment token only when `CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB=1` is also set in the service environment. The code treats that as a recovery setting. Without it, an environment token is rejected with `Invalid staff bearer token.` Prefer database tokens (`token issue`).

> **Warning:** The server cannot revoke an environment token. The console's **Sign out** only makes that browser forget it. To retire one, remove it from the variable and restart the service, which takes the channels off the air.

### Failed attempts are limited

A wrong token counts against the client's address: 10 failures in 60 seconds by default (`CIVICCAST_AUTH_RATE_LIMIT` and `CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS`). After that the server answers HTTP 429 with a `Retry-After` header, and the console shows `Too many failed attempts to authenticate with the staff API. Wait N seconds, then try again.` A request with no token at all does not count. A valid token still works while the limit is active. The counts live inside the running process and reset when it restarts. CivicCast's own code ignores forwarded-address headers, so it counts failures against the address the web server reports. The web server (uvicorn) is started with its default settings, which replace that address with the `X-Forwarded-For` value when the connection comes from `127.0.0.1`. In a test with uvicorn 0.47 (not the shipped 0.51.0) we saw exactly that. So behind a reverse proxy on the same computer, failures are counted against the proxy's address if the proxy sends no such header, and against the visitor's address if it does.

> **Known issue (beta.11):** The memory the limiter uses to remember addresses has no upper bound (audit finding B-010). It only matters if someone sends very many bad requests from very many addresses, which cannot happen if the staff API stays on loopback as this chapter advises.

## Understand sign-in, setup and recovery

### First setup and the recovery kit

The first time the console is opened on the station computer it shows **First setup**. Creating the first admin there makes:

- the first-admin username and password (the password must have at least 12 characters), and
- a **recovery kit**: 8 one-time recovery codes.

The **Save kit** button downloads a plain-text file that contains the admin password and all 8 codes. The console blocks navigation and sign-out until the kit is confirmed.

> **Warning:** Treat the recovery kit like a master key. Print it and keep it in a locked drawer or a safe, or keep it in your password manager. Do not leave it in the Downloads folder, a shared drive or an e-mail.

Routine sign-in uses the admin username and password on the `/setup` page (**Admin sign-in**). If the password is lost, **Use recovery code** burns one of the 8 codes and sets a new password; it takes two clicks and warns you each time. The other browsers that are signed in stay signed in.

### What the server enforces

- **Sign-in and setup only work from the station computer.** The routes under `/api/setup/*` check that the request came from the loopback address. A request from another computer gets HTTP 403 and the console shows **First setup can only be done from the station computer itself**. After setup is complete, most of these routes also require a staff token; only the signed-out view of the station state, sign-in (`login`) and recovery (`recover`) stay open to a request from the station computer.
- The station keeps up to **20** console sessions at once and evicts the oldest when a 21st is created. The evicted browser sees **You were signed out**. In testing we could not confirm that sessions expire by time.
- The two API calls `POST /api/staff/installer/sessions/revoke-others` and `POST /api/staff/installer/recovery-kit/regenerate` (Setup admin) end the other console sessions and make a new kit (new codes; the old codes stop working at once). The console has buttons for both: **Sign out other sessions** and **Regenerate recovery kit** in the Security card of the Station Profile screen, visible to the Setup admin role.
- For a lost password with no usable recovery codes, use the local administrator procedure below. Do not use `CIVICCAST_ALLOW_FIRST_ADMIN_RESET`: it reruns setup and can replace station settings.

### Administrator password reset

The computer's owner or an authorized local Windows administrator can reset the existing first administrator without the old password or recovery codes. This is an offline maintenance operation, not a web API. It preserves the administrator's username, station settings, PostgreSQL database, recordings and other media. It revokes every first-admin console session and all old recovery codes. Separately issued staff API tokens are unchanged; retire those separately if compromise is suspected.

1. Schedule a short outage and close any manually launched CivicCast server. On the station computer, open **PowerShell → Run as administrator**.
2. Stop the supervisor and run the installed command (replace `<INSTDIR>` with your installation folder):

   ```powershell
   Stop-Service CivicCastSupervisor
   & "<INSTDIR>\runtime\python.exe" -I -m civiccast.cli admin reset-password
   ```

3. Enter the new password twice at the hidden prompts (12–256 characters). Never put it in command arguments, environment variables, a script or a ticket. Cancelling or mismatching the prompts changes nothing.
4. After success, run `Start-Service CivicCastSupervisor`, sign in with the displayed existing username and new password, then open **Station Profile → Security → Regenerate recovery kit**. Save the new kit safely; all previous recovery codes are invalid.

The command checks the actual elevated Windows token, the stopped supervisor's LocalSystem identity, and its registered environment. It holds the supervisor's exclusive Windows mutex throughout recovery, so service starts and another recovery cannot write concurrently. It targets LocalSystem's protected `station-state.json`, or an absolute local `CIVICCAST_STATION_STATE_PATH` configured for the service or machine; the invoking user's profile and environment are ignored. Relative, network, linked and junction paths are refused. Nonstandard service identities need IT support rather than guessing a state file.

Before changing credentials it creates an ACL-protected `*.before-admin-reset.bak` beside the state file, then replaces the state atomically. The backup contains old credential hashes and session hashes: keep it restricted, do not attach it to support requests, and remove it after confirming access and your normal station backup. Restoring it also restores the old credentials and sessions. A missing or corrupt state file is refused, not reinitialized. If recovery reports a failure, retain the backup, correct the reported condition and retry; restart the supervisor when maintenance is complete. No database password or DPAPI secret is read; the new password is never echoed, logged or stored in plaintext.

> **Known issue (beta.11):** The loopback test looks only at the address the connection came from. If you put a reverse proxy **on the same computer**, every request it forwards arrives from `127.0.0.1` and passes the test, including requests from the internet, unless the proxy sends an `X-Forwarded-For` header (the web server then substitutes that address; see "Failed attempts are limited"). Do not rely on that: many proxies send no such header unless told to. The code's own comment warns about this. If you use a proxy, it must refuse every path that begins with `/api/setup/`. Also, the loopback routes do not check the `Host` or `Origin` of a request (audit finding E-006), so a web page opened in a browser on the station computer could in principle talk to them through a DNS-rebinding trick during first setup. Do not browse the web from the station computer, and complete first setup before the computer is used for anything else.

## Know what the station exposes to the network

### What listens, and where

| Service | Bind address | Port | Notes |
| --- | --- | --- | --- |
| Control plane (web API, console, portal) | `127.0.0.1` | 8000 | The address is fixed in code. There is no setting that changes it. |
| Postgres | `127.0.0.1` | first free of 5432, 5433, 5434, 5435, 5544 | Password logins only (`scram-sha-256`). No TLS. |
| Ollama | `127.0.0.1` | 11434 | Environment `OLLAMA_NO_CLOUD=1` is set for it. |

We searched the program for a wildcard bind (`0.0.0.0`) and found none. Both the installer text (`INSTALL-WINDOWS.md`) and the code say the console address is not reachable from another computer.

### What the firewall rule opens

The installer adds a Windows Firewall rule named **CivicCast (Native) Portal/API (TCP 8000)**. It is an inbound allow rule for TCP port 8000, limited to the program `<INSTDIR>\runtime\python.exe`, enabled on **all** firewall profiles (domain, private and public) and with no restriction on the remote address.

> **Known issue (beta.11):** Today this rule exposes nothing, because nothing listens on 8000 except on `127.0.0.1`. But it is broader than the station needs (audit finding E-009). If a setting or a later version ever changed the bind address, port 8000 would be open to every network the computer joins. If you want the rule to say what you mean, disable it in **Windows Defender Firewall with Advanced Security** and check that the station still works from the station computer. We have not tested a station with the rule removed.

Outbound traffic is not restricted by CivicCast.

### Other web protections

- **CORS** (which web sites may call the API from a browser) is deny-all by default. Allow specific sites with `CIVICCAST_CORS_ALLOWED_ORIGINS` as a list of exact origins. A wildcard `*` is refused as a startup error.
- Responses carry a `Content-Security-Policy` that begins `default-src 'self'` and adds narrower rules (for example `object-src 'none'` and `frame-ancestors 'none'`), plus `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. A response that already sets one of these headers keeps its own value.
- Native stations set `CIVICCAST_LAN_ONLY_STATION=1`. With it, the API documentation pages `/docs` and `/redoc` are off, and `/openapi.json` needs a staff token.
- `CIVICCAST_AUTH_ACK=1` only silences a start-up warning about authentication. It does not change who can sign in.

## Know the public and staff parts of the API

The web API has distinct groups of paths. Which group a path is in decides who may call it.

| Path group | Who can call it | What it is |
| --- | --- | --- |
| `/api/staff/*` | A staff bearer token, by role | Everything the operator console does. |
| `/api/setup/*` | The station computer only; after setup, also a staff token | First setup, sign-in, recovery. |
| `/api/public/*` | Anyone who can reach port 8000 | Resident features. Groups: agendas, app, assets (published ones only), cg, channels, contribute, contribution, egress, embed, live, manual, paywall, playback-policy, podcast, programlog, reports/as-run, schedule/coming-up, search, subscribe. |
| `/api/webhooks/stripe` | Stripe, with a signature | Payment events. |
| `/media/*` | Anyone | Media files for the portal. |
| `/ap/*` | Anyone | ActivityPub (federation) endpoints. Federation mode is `disabled` unless `CIVICCAST_ACTIVITYPUB_MODE` is set. |
| `/health`, `/api/health`, `/api/version`, `/api/hardware` | Anyone | Health, version and hardware summaries. |

The staff middleware gates every path that begins with `/api/staff/`. The public asset lists show only assets that are published.

> **Known issue (beta.11):** There is no setting that turns off the public contributor routes (`/api/public/contribute`); the router is always included. Anyone who can reach the port can use them. See the limitations section.

> **Known issue (beta.11):** `GET /api/hardware` needs no sign-in and returns the computer's host name (audit finding B-012). Treat the host name as public.

## Put a reverse proxy and TLS in front

The control plane speaks plain HTTP only. It has no setting for a TLS certificate. If anything outside the station computer needs to reach it (for example residents on their own devices), a reverse proxy has to terminate TLS. Because the control plane listens only on loopback, the proxy must run on the **same computer**.

1. Install nginx, Caddy or Traefik on the station computer. The product does not install or manage one.
2. Forward only the paths you intend to publish (the public portal and `/api/public/*` paths you need, plus `/media/*`). Test the resident portal through the proxy.
3. Refuse these at the proxy: `/api/setup/*`, `/api/staff/*`, `/openapi.json`, `/docs`, `/redoc`, and, unless you use Stripe, `/api/webhooks/stripe`.
4. Do not publish `/api/public/contribute*` while the upload limits are as described under limitations below.
5. If you must reach `/api/staff/*` from another computer, add your own proxy login (basic authentication, a client certificate or single sign-on) in front. The bearer token is still required; the proxy login is an extra layer, not a replacement.
6. Set `CIVICCAST_LOCAL_MEDIA_BASE_URL` to the public address that residents use, so media links are correct.
7. Set `CIVICCAST_TRUSTED_PROXY_CIDRS` and `CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS` to your proxy's address range only if you need the original viewer address to be honoured; see [Appendix C](#app-settings) for what each does.

> **Warning:** Do not use a proxy that forwards everything. The pitfall under "What the server enforces" above makes `/api/setup/*` reachable from the internet through such a proxy.

**Internal certificates are a different thing.** The station contains a local certificate authority for mutual TLS between its own internal programs (the identities `civiccast-api` and `civiccast-worker`). Certificates last 90 days and show `rotation_due` in the last 30 days. Renew one with `& $cc cert rotate <identity>` (add `--json` for scripts). The root folder is `CIVICCAST_CERT_ROOT`, default `.civiccast\certs` under the service account's home. These certificates are not the HTTPS certificate for a browser and cannot be used as one.

## Protect subscribers and viewers

### Viewer analytics

- The portal's analytics beacons are stored **without** an IP address, a session identifier or a viewer identifier. A stored event has an event id, event name, time, app target, channel id, content id and a short list of safe properties (such as country, region, state, device, platform and caption language). String values are truncated to 160 characters.
- A beacon is accepted for storage only when `CIVICCAST_PUBLIC_ANALYTICS_KEY` or `CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS` is set. Otherwise the beacon is accepted and dropped, which is "telemetry off". A beacon larger than 16,384 bytes is refused.
- Stored events are kept for up to 366 days (`CIVICCAST_ANALYTICS_RETENTION_DAYS`, range 1 to 366).

### Subscribers

- A subscriber's e-mail address is stored encrypted with AES-GCM. Confirmation and unsubscribe links carry signed tokens.
- The encryption key and the token secret come from the pair `CIVICCAST_SUBSCRIBE_TOKEN_SECRET` and `CIVICCAST_SUBSCRIBE_ENCRYPTION_KEY` (set both or neither). If you set neither, the station creates a durable file `subscribe-secrets.json` (in `CIVICCAST_CONFIG_DIR` or `.civiccast` under the service account's home).
- The e-mail confirmation token is not shown in the API reply.

> **Warning:** Back up that key. A database restored without it keeps encrypted addresses that nobody can read ([Chapter 12](#ch-operations)).

> **Known issue (beta.11):** The confirmation token for a webhook subscription **is** returned in the API reply (a known gap).

> **Known issue (beta.11):** By default the e-mail, webhook, YouTube, Internet Archive and NAS providers are mock or local providers. Real ones are chosen with `CIVICCAST_PROVIDER_<KIND>=real`, where the kind is `MAIL`, `WEBHOOK`, `YOUTUBE`, `INTERNET_ARCHIVE` or `LOCAL_NAS` (see [Appendix C](#app-settings)); choosing a real provider without its credentials makes the station fail fast at start-up. Until you switch the mail provider, no subscriber e-mail is actually sent.

## Retain and delete data

| Data | Kept | Source |
| --- | --- | --- |
| Live-caption working audio (native beta.11 runtime) | Processed chunks are deleted; at most 12 queued completed segments per channel, plus in-flight inputs and the segment being written. Native live operation does not run the optional age-based retention sweep. | `captions/tap_worker.py`, runtime wiring |
| Live-caption text and delivery tracking (native beta.11 runtime) | Rolling 300 seconds and at most 512 cues; no permanent per-cue review rows or evidence WAVs | `captions/stabilize.py`, `egress/caption_feed.py` |
| Recorded-caption review and original recordings | Existing recording/review workflow remains unchanged; live working limits do not delete archived tracks or recordings | `captions/vod.py`, recording workflow |
| Historical beta.10 caption-retention audit | The beta.10 audit found that `caption-retention-audit.jsonl` was not rotated. Native beta.11 live captioning does not enable the optional age-based retention sweep. | `captions/retention.py`, `captions/tap_worker.py` |
| Analytics events | Up to 366 days (default; range 1 to 366) | analytics store |
| Playout health telemetry | Not trimmed automatically; trim with `civiccast egress trim-health --older-than-days N` | CLI |
| Staff token audit events, alert history, as-run records | No deletion setting found | not found |

Live captions are off by default, and `CIVICCAST_CAPTION_TAP=off` forces them off. The native beta.11 runtime separates transient live caption work from recorded-caption review. It does not make the live worker or broadcast readiness depend on archive-wide review/evidence retention discovery. No live review/evidence archive is created by ordinary live captioning; this does not change recorded captions or original recordings.

> **Historical finding (published beta.10):** Audit findings B-003, B-004, B-005 and B-009 recorded unbounded live-caption evidence growth. Beta.11 changes the native live path: it does not run that archive sweep, writes no per-cue evidence, deletes processed chunks and bounds the queued audio and rolling caption history. Those are current source behaviors, not a long-duration package observation. The beta.11 package's test scope is in the current verification record.

Where residents' own data may be requested for deletion, we found no console screen or command that deletes a subscriber or a viewer's records. Ask the coder to confirm before you promise a deletion process.

## Check what you install: signing and checksums

- **The installer** is signed with Authenticode through Azure Trusted (Artifact) Signing. The policy file `CODE_SIGNING_POLICY.md` names the signer as Scott Converse. Windows SmartScreen may still show a reputation warning for a new publisher. To check a download:

```powershell
Get-AuthenticodeSignature .\CivicCast-Setup.exe | Format-List Status, SignerCertificate
Get-FileHash .\CivicCast-Setup.exe -Algorithm SHA256
```

The status should read `Valid`. Compare the hash with the line for that file in `SHA256SUMS.txt` on the beta.11 release page. The current verification record states the published installer carries a valid signature and the asset hashes match `SHA256SUMS.txt`. Replace the file name with the real one.

- **Sidecar.** The release also has a `setup.exe.sidecar.json` file with checksum metadata. It is plain metadata and is not separately signed (`attestation` is `null`). `civiccast installer verify-package --artifact <file> --sidecar <file> [--json]` checks a file against it.
- **Packs.** The large components (`.ccpack` files) carry ed25519 signatures that the installer verifies. The installer also checks a SHA-256 for each file, rejects names containing `..` and rejects reparse points (Windows links). The pack index is pinned to the product version, so an older pack cannot be offered to a newer product.
- **Build downloads** are pinned by hash, and the application's Python packages are installed with `--require-hashes`.
- **No sigstore/cosign.** The owner decided against it (decision record ADR 0022).

> **Known issue (beta.11):** All packs are signed by one key that has no expiry and no rotation procedure (audit finding E-012). If a pack were ever to be signed by a stolen key, the installer would accept it. Download beta releases only from the project's GitHub release page.

> **Historical beta.10 audit finding (repository settings):** The 2026-10-02 audit reported that signing secrets were not restricted to a protected environment, action versions used mutable tags and `main` was not protected. Those observations describe repository settings at the audit date, not their current state. For every release, trust only the official release page, verify the installer's signature and compare its hash with the release checksum file.

## Historical beta.10 security audit findings

The entries below summarize the whole-repository audit dated 2026-10-02 (`audit-lite-whole-repo-beta10-2026-10-02`). They preserve that audit's findings and severities; later beta.11 code and installer changes mean they are not a current release review. Current configuration and safety instructions appear in the operating chapters above. Finding numbers are the audit's.

| Finding | What is wrong | What you do |
| --- | --- | --- |
| B-001 (Critical) | An anonymous visitor's contributor upload is accepted and written to disk **before** the size limits are checked, so a flood of uploads can fill the disk. | Keep the public contributor portal off the internet. Do not forward `/api/public/contribute*` at a proxy. Use the upload limits (`CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES`, `CIVICCAST_CONTRIBUTOR_UPLOAD_DIR_MAX_BYTES`, `CIVICCAST_CONTRIBUTOR_UPLOAD_PER_IP_MAX_BYTES`, `CIVICCAST_CONTRIBUTOR_UPLOAD_RATE_LIMIT` default 10, `CIVICCAST_CONTRIBUTOR_SUBMISSION_RATE_LIMIT`) as a second layer. Watch free space. |
| E-001, B-002 | A webhook subscription can be pointed at an internal address (server-side request forgery) and its signing secret is guessable. | Webhook delivery happens only when `CIVICCAST_PROVIDER_WEBHOOK=real`. Leave it unset unless you need it, and keep the public subscribe routes off the internet. |
| E-006 | The loopback setup routes do not check `Host` or `Origin`. | Finish first setup before the computer is used for anything else. Do not browse the web from the station computer. |
| Proxy pitfall (design, not an audit finding) | A reverse proxy on the same computer defeats the loopback tests. | The proxy must refuse `/api/setup/*` and `/api/staff/*` (see above). |
| E-007 | The service and every child run as LocalSystem. Owner-accepted (ADR 0021). | Treat the station computer as a single-purpose appliance. Give no one else a login on it. |
| B-006 | Any signed-in local user can wedge the supervisor's control pipe. Playout is not affected, but the supervisor's status, start, stop and restart verbs stop answering. | Allow only administrators to log in to the station. Windows `sc.exe` still starts and stops the service. |
| E-003 | The installer opens log and URL paths through `cmd.exe /C start`; an `&` in such a path can run a command. Exploiting it needs earlier write access to the installer's state. | Do not run the installer from a folder whose name or content an untrusted person controls. |
| E-004, E-005 | The dependency vulnerability scan checks a lock file that differs from what ships (37 of 81 pins differ), and an allow-list entry has expired. | Treat the shipped Python packages as not independently scanned. Watch the release notes for updates. |
| E-009 | The firewall rule is broader than needed. | See "What the firewall rule opens". |
| E-011 | The embedded Python is 3.12.10. The audit states, from memory and not verified online, that this was the last 3.12 build with binary installers, so the shipped interpreter may not get further stdlib security fixes. | Keep the station off untrusted networks until a later release replaces it. |
| E-012, E-002 | One pack-signing key with no expiry; build secrets and branch not protected. | See "Check what you install". |
| B-010 | The failed-login limiter has no memory bound. | Keep `/api/staff/*` on loopback. |
| B-012 | `/api/hardware` shows the host name to anyone. | Treat the host name as public. |
| B-019 | `civiccast model set-provider-key --key <value>` puts the key on the command line, visible to other programs in the process list. | Supply the key in the `CIVICCAST_PROVIDER_API_KEY` environment variable instead. |
| B-003, B-004, B-005, B-009 | Historical beta.10 caption data growth (see retention). | Beta.11 removes automatic live review/evidence accumulation and bounds live working state; verify the candidate before deployment. |
| A-001, A-008 | The audit reported a program-change watchdog gap and no free-space guard on the 60 GB cache. Beta.11 includes a rollover watchdog and cache free-space guard; their code behavior is described in [Chapter 12](#ch-operations). | The audit findings are historical; current runtime reliability still depends on exact-package evidence. |
| C-001 | Automated tests were red in about 110 places at the time of the audit. | Historical audit result only; it does not describe the beta.11 test state. |

> **Note:** The beta.10 audit also discussed operational items such as alerts with no destination, the disaster-recovery drill's `pg_dump` dependency and log rotation. See their current operating guidance in [Chapter 12](#ch-operations).

> **Warning:** The three rules to keep: (1) the staff API stays on loopback, (2) the public contributor portal stays off the internet, (3) only the signed installer from the official release page is ever run.

### Report a security problem

Report a suspected vulnerability privately, as `SECURITY.md` in the repository describes. Do not open a public issue. The policy states that a report is acknowledged within 72 hours.

## If it did not work

| What you see | Cause | What to do |
| --- | --- | --- |
| `No DATABASE_URL configured` or a database connection error from `civiccast token ...` | `DATABASE_URL` not set in this window | Set it as shown in "Before you start". |
| `Staff identity is required for this action.` (401) | No `Authorization: Bearer` header | Send the header. |
| `This action requires one of these CivicCast roles: ...` (403) | The token lacks the role | Issue a token with the role. |
| `Too many failed attempts to authenticate with the staff API. Wait N seconds, then try again.` (429) | 10 bad tokens in 60 seconds from one address | Wait. Check the token. |
| A token you issued is rejected | Revoked, rotated, or issued before the fingerprint change | `token list`, then `token rotate`. |
| Console says **First setup can only be done from the station computer itself** | You opened the console from another computer | Use the station computer or a remote-desktop session on it. |
| **You were signed out** | The oldest of 20 sessions was evicted, or the station's sign-in state was reset | Sign in again. |
| `Invalid admin username or password.` | Wrong credentials | Use the recovery kit's password or one of the 8 codes. |
| A signed installer shows `NotSigned` or a hash that does not match `SHA256SUMS.txt` | Corrupt or altered download | Do not run it. Download again from the release page. |

## Related

- [Signing in and finding your way around](#ch-signing-in)
- [Running it day to day](#ch-operations)
- [Configuring the station](#ch-configuration)
- [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations)
- [Troubleshooting matrix](#ch-troubleshooting)
- [Appendix C: settings](#app-settings), [Appendix F: roles](#app-roles), [Appendix H: measured evidence](#app-evidence)

<!-- SOURCES: civiccast/auth/middleware.py, tokens.py, roles.py, store.py, rate_limit.py, cors.py, security_headers.py, keyring_store.py; civiccast/cli.py:2030-2220 (token commands); ops/docs-sprint/inventory/generated/cli.md (token, cert, installer verify-package, egress trim-health); civiccast/installer/station_state.py (sessions, recovery kit, PBKDF2); civiccast/installer/router.py:1195-1305 (loopback setup guard); ops/docs-sprint/inventory/screens/_shell-signin-and-session.md, setup.md, _shell-navigation-and-roles.md; civiccast/app.py:2093-2175 (LAN-only, /docs off), 2323-2450 (/health, analytics cap); civiccast/native/supervisor/children.py (host 127.0.0.1, Postgres bind); civiccast/native/provision/conf.py (postgresql.conf, pg_hba); civiccast/apps/installer/src-tauri/src/native_service_registration.rs:2714-2830 (firewall rule); civiccast/native/station_runtime.py; civiccast/certs/authority.py; civiccast/subscribe/service.py, secrets.py; civiccast/platform/providers.py; civiccast/analytics/models.py, store.py; civiccast/app_platform/router.py (analytics ingest); civiccast/schedule/router.py (public assets); civiccast/captions/retention.py; ops/docs-sprint/inventory/generated/api.md (path groups); docs/ops/staff-route-protection.md, docs/ops/local-ca-mtls.md (topics only); SECURITY.md; CODE_SIGNING_POLICY.md; docs/install/windows-release-trust.md; docs/releases/v1.0.0-beta.10-verification.md; ops/beta10-oversight/audits/audit-lite-whole-repo-beta10-2026-10-02.md and slices/slice-E-security.md, slice-B-captions-app.md, slice-A-egress.md -->
