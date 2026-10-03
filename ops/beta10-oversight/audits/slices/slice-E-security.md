# Slice E - Security, supply chain, build/install scripts
Repo: civiccast-release @ release/beta10 (read-only static review, 2026-10-02). No online advisory lookups were made.

Secrets result: NO committed secrets found in the tracked tree (3,375 files) or in added lines of the last 200 commits (694 commits total). Patterns scanned: ghp_/github_pat_/AKIA/sk-/xox*/AIza, PEM private-key headers, `ccst_` staff tokens, connection strings with passwords, Azure client secrets, long base64 blobs. Only hits were test fixtures (`ccst_mock_...`, `operator-token-a`), the Tizen SDK's public sample-cert passwords (see E-016), a `CHANGE-ME-BEFORE-USE` placeholder in `gate-b/answer/autounattend.xml:105`, and sentinel strings in a patch file.

### E-001 Critical: Unauthenticated public webhook subscription = blind SSRF, self-confirmable, with a guessable signing secret
**Dimension:** Runtime
**Evidence:** civiccast/subscribe/models.py:43 (`webhook_url: HttpUrl`, no address validation); civiccast/subscribe/service.py:138-171 (create_webhook_subscription), :70-91 (comment admits the confirmation token is echoed for webhooks and "proves nothing about URL ownership"); civiccast/subscribe/service.py:149 (`webhook_secret = sha256(f"{subscription_id}:webhook")`) with :41-43 (`subscription_id` = sha256 of channel+URL+target_type+target_id, all public values); civiccast/subscribe/webhook.py:69-83 (httpx POST to the stored URL, no private/loopback/link-local block); route civiccast/subscribe/router.py:87 (`/api/public/subscribe/webhook`, no staff auth).
**Why it matters:** Anyone who can reach the public API can register any http(s) URL (127.0.0.1 services such as the bundled Ollama, LAN devices, router admin pages, cloud metadata addresses), confirm it themselves with the echoed token, and make the station POST JSON to it on every publish and retry. The per-subscription HMAC secret is computable by anyone who knows the URL and target, so receivers cannot trust signatures either. The author's own comment records this as a known, unclosed gap.
**Fix path:** (1) Add an outbound-URL guard used by webhook delivery and registration: resolve the host, reject loopback/private/link-local/multicast/unspecified (re-check at connect time to defeat DNS rebinding), `follow_redirects=False`, https-only unless an operator allow-list says otherwise (the `cg/feed_fetcher.py` and `activitypub/remote.py` guards are existing patterns to reuse). (2) Make webhook confirmation real: POST a challenge to the URL and require the receiver to echo it, and stop returning `confirmation_token` in the public response. (3) Generate the webhook secret with `secrets.token_urlsafe(32)`, never derive it from public inputs. (4) Add tests for each.
**Blast radius:** Station-side requests to internal services (Ollama on 11434/11435, PostgreSQL loopback port, router/NVR admin on the LAN) from an unauthenticated caller; delivery retries amplify it; forged "signed" notices to subscribers. Reachable only where the public API is reachable (loopback by default today; any reverse proxy or future LAN exposure makes it live).

### E-002 Critical: Signing secrets are not environment-gated, and the action that receives the Azure secret is a mutable tag
**Dimension:** Correctness
**Evidence:** .github/workflows/sign-native-installer.yml:57-64 and .github/workflows/native-beta-candidate-artifacts.yml:868-875 (`azure/artifact-signing-action@v2` receives `secrets.AZURE_CLIENT_SECRET`); .github/workflows/native-beta-candidate-artifacts.yml:510,1177 (`secrets.CIVICCAST_PACK_SIGNING_PRIVATE_KEY` written to RUNNER_TEMP); `grep environment:` across .github returns nothing; .github/workflows/native-beta-candidate-artifacts.yml:103 (`id-token: write` granted though CODE_SIGNING_POLICY.md says no OIDC is used). sign-native-installer.yml:11-25 is dispatchable with any draft-release asset plus a caller-supplied hash.
**Why it matters:** The pack-signing ed25519 key is the root of trust the installer embeds: whoever can run a workflow with it can mint packs that a perMachine, LocalSystem-service installer will unpack and run. The Azure service-principal secret signs the public installer under the owner's name. With no `environment:` protection (required reviewers / branch restriction) any user with write access, or any compromised third-party action tag, can use both; the sign workflow acts as a signing oracle for any exe a writer uploads to a draft release. Repo-settings protection (if any) is not visible from the tree - confirm in GitHub.
**Fix path:** Put both secrets in a protected GitHub Environment (required reviewer = owner, deployment restricted to the release branch/tag) and add `environment:` to the signing jobs; pin `azure/artifact-signing-action` and every action that runs in a secret-bearing job to a full commit SHA; drop `id-token: write`; make the sign workflow also verify the intake exe was built by a prior green candidate run (run id + artifact digest) rather than accepting any hash typed in; rotate the Azure secret on a schedule and consider moving the pack-signing key to Azure Key Vault/HSM signing.
**Blast radius:** Total loss of release integrity: an attacker-signed installer or packs executing as SYSTEM on every station that installs them. Every `uses:` line in .github is a mutable tag (`actions/*@v4/v5`, `astral-sh/setup-uv`, `Swatinem/rust-cache@v2`, `dtolnay/rust-toolchain@stable`, `gradle/actions@v4`); `setup-uv` also uses `version: "latest"`.

### E-003 Major: Command injection into `cmd.exe /C start` through the installer's "open console / open log" commands
**Dimension:** Runtime
**Evidence:** civiccast/apps/installer/src-tauri/src/main.rs:3777-3784 (`validate_local_console_url` is only a `starts_with("http://127.0.0.1:8000/")` prefix check); :3788-3796 (`Command::new("cmd.exe").args(["/C","start","",&url])`); :2934-2943 (same idiom with a log path); the URL originates from the installer progress JSON (`operator_console_url`, civiccast/apps/installer/src/api.ts:252) and App.tsx:467,586.
**Why it matters:** `http://127.0.0.1:8000/&calc.exe` passes the prefix check, and cmd.exe treats the unquoted `&` as a command separator. A tampered progress/state file (or a log path containing `&`, e.g. a profile name like "A&B") runs arbitrary commands as the user running the installer (the elevated per-machine installer during setup).
**Fix path:** Parse with a real URL parser and require scheme http, host exactly 127.0.0.1/localhost, port in {8000,5173}, no userinfo, and reject any of `& | < > ^ " % ! ( )` and control characters; better, bypass cmd.exe entirely with `ShellExecuteW` / `open::that` / `rundll32 url.dll,FileProtocolHandler`. Add a unit test with `&`, `|`, `%PATH%` and quote payloads.
**Blast radius:** Local code execution in the installer's security context; requires a prior write to the installer state/progress source, so practical exposure is low-to-moderate.

### E-004 Major: The pip-audit gate scans a different dependency set from the one that ships; 37 of 81 shipped pins differ from uv.lock
**Dimension:** Correctness
**Evidence:** .github/workflows/ci-security-scan.yml:50-57 (`uv sync --all-extras --group dev` then `pip-audit`, i.e. the uv.lock environment); the shipped set is requirements-native-app.txt (81 hashed pins, installed with `uv pip install --require-hashes`, scripts/build_native_app_payload.py:797-830). A programmatic comparison found 37 version differences, e.g. pypdf 6.14.2 shipped vs 6.16.1 in uv.lock, lxml 6.1.1 vs 6.1.2, uvicorn 0.51.0 vs 0.46.0, fastapi 0.136.3 vs 0.136.1, sqlalchemy 2.0.51 vs 2.0.49.
**Why it matters:** A CVE fix applied to uv.lock (and so green in CI) is not necessarily applied to what customers receive; the older shipped pypdf/lxml are exactly the parser libraries that handle untrusted documents. I did not run an online audit, so I cannot say whether those older versions have advisories - the point is that nothing checks them.
**Fix path:** Run `pip-audit -r requirements-native-app.txt --require-hashes` (and the runtime/pyav/app-build lock files) in CI through the same allow-list script, and add a policy test that fails when a package appears in both lock files at different versions (or generate one from the other).
**Blast radius:** Shipped runtime vulnerabilities invisible to CI; applies to every installed station.

### E-005 Major: The pip-audit allow-list has an expired entry, an undated open-ended entry, and the checker never enforces `review_by`
**Dimension:** Correctness
**Evidence:** security/pip-audit-allowlist.json:13-14 (nltk PYSEC-2026-3740, `review_by` 2026-10-01 - already past as of 2026-10-02); :7 (nltk PYSEC-2026-597, reviewed 2026-07-05, no review_by, "no fix as of this review"); scripts/check_pip_audit_allowlist.py:24-26,43-47 (matches only on (package,id); `review_by` is never read).
**Why it matters:** The gate silently accepts findings forever; the justification text is good (nltk is reachable only via the optional `agenda-js-import` extra and is not in requirements-native-app.txt, which I confirmed), but the "re-review by 2026-10-01" promise is unenforced and now overdue.
**Fix path:** Make the checker fail on any entry whose `review_by` is missing or earlier than today, add `review_by` to the first entry, then re-check whether nltk now has a fix and either bump or re-date both entries. Add a test for the expiry behaviour.
**Blast radius:** n/a (process gate; no direct exposure while nltk stays out of the shipped lock).

### E-006 Major: Loopback-only trust has no Host/Origin check, so first-run setup and `login/recover` are open to DNS rebinding and any local process
**Dimension:** Runtime
**Evidence:** civiccast/installer/router.py:1211-1262 (`_require_local_setup_request` admits any loopback peer; also admits when `request.app.debug` or `scope["client"] is None`); civiccast/auth/middleware.py:64 (only `/api/staff/*` is token-gated); no TrustedHostMiddleware, Host-header or Origin validation anywhere in civiccast/ (grep); civiccast/auth/cors.py default is deny-all (good) but does not stop DNS rebinding, which is same-origin from the browser's view.
**Why it matters:** A web page the operator visits during first run can rebind its hostname to 127.0.0.1 and POST to `/api/setup/first-admin` (the peer address really is loopback), becoming the station's first admin; afterwards `login`/`recover` stay loopback-open for brute force of the recovery kit. Any other local account on a shared Windows box has the same access. The owner decision (2026-08-29) retired the nonce on the premise that loopback is enough; DNS rebinding is the case that premise misses.
**Fix path:** Add a Host allow-list middleware (127.0.0.1, localhost, [::1], the configured public host) returning 421 otherwise, and require `Origin`/`Sec-Fetch-Site` same-origin or absent on mutating `/api/setup/*` calls; remove the `app.debug` bypass from the setup guard or gate it on an explicit test flag.
**Blast radius:** Station takeover during the setup window; moderate likelihood only while a browser is open on the station.

### E-007 Major: The whole control plane (web server, ffmpeg/PyAV media parsing, AI runtime, outbound HTTP) runs as LocalSystem
**Dimension:** Runtime
**Evidence:** docs/adr/0021-native-windows-runtime.md:70-72 (owner-accepted "LocalSystem service identity for the beta ... tracked follow-up"); civiccast/apps/installer/src-tauri/src/native_service_registration.rs:25-26,3523-3524 (test asserts no `--username/--password`); civiccast/native/supervisor/children.py:536 launches uvicorn as a child of the SYSTEM supervisor.
**Why it matters:** Any code-execution bug in a parser reached from public uploads (contributor upload, VOD, captions) or an E-001-style request forgery lands as SYSTEM. This is a recorded and accepted risk, so it is listed rather than escalated, but it multiplies the impact of every other finding.
**Fix path:** Run web-facing children under a dedicated low-privilege virtual service account (`NT SERVICE\CivicCastSupervisor` or a restricted token / low-integrity child) with ACLs on the data dirs; keep only the supervisor itself privileged.
**Blast radius:** Machine-level compromise from any web-facing RCE.

### E-008 Minor: Release gate checks Authenticode `Status == Valid` but not the signer identity
**Dimension:** Correctness
**Evidence:** scripts/release/publish_beta_candidate.py:207-216 (`(Get-AuthenticodeSignature ...).Status` only); .github/workflows/native-beta-candidate-artifacts.yml:886 (same); contrast CODE_SIGNING_POLICY.md "signer CN=Scott Converse".
**Why it matters:** A validly signed file from any publisher passes the gate; the documented subject is never asserted.
**Fix path:** Also assert `SignerCertificate.Subject` contains the expected CN (and ideally the chain/thumbprint and an RFC3161 timestamp) before publishing.

### E-009 Minor: Inbound firewall rule is broader than the product needs and contradicts the loopback-only posture
**Dimension:** Runtime
**Evidence:** civiccast/apps/installer/src-tauri/src/native_service_registration.rs:2774-2789 (`dir=in action=allow protocol=TCP localport=8000 program=...python.exe profile=any`, no `remoteip=`); civiccast/native/supervisor/core.py:393 binds 127.0.0.1 and no `0.0.0.0` bind exists anywhere in civiccast/ (grep); INSTALL-WINDOWS.md:197 says the URL "is useless from another machine".
**Why it matters:** The rule does nothing today but would instantly expose port 8000 on Public Wi-Fi profiles for the SYSTEM-run python.exe if a bind ever changes; it also adds an installer failure mode (CIVICCAST_EXIT_D4_FIREWALL).
**Fix path:** Remove the rule while the product is loopback-only, or restrict to `profile=private,domain remoteip=LocalSubnet` when LAN exposure becomes a real feature.

### E-010 Minor: No dependency-advisory checks for the shipped installer (Rust and npm) or tools/ndi-ffmpeg-sender
**Dimension:** Correctness
**Evidence:** .github/workflows/ci-security-scan.yml covers pip-audit, bandit and npm audit for portal-operator and portal-public only; no `cargo audit/deny`, no npm audit for civiccast/apps/installer/package-lock.json, none for tools/ndi-ffmpeg-sender/Cargo.lock; `git grep RUSTSEC` is empty. civiccast/apps/installer/src-tauri/Cargo.lock includes glib 0.18.5, the gtk3 bindings (gtk/gdk/atk 0.18.2, webkit2gtk 2.0.2), proc-macro-error and unic-* crates, which I recall are flagged unsound/unmaintained upstream (from memory, not verified online); they are Tauri's Linux-only transitive dependencies and are not compiled into the Windows build.
**Why it matters:** The installer is the one elevated, per-machine binary and has the weakest advisory coverage.
**Fix path:** Add `cargo audit --deny warnings` (with a small ignore file for the Linux-only crates) and `npm audit --audit-level=high` for the installer and NDI tool to ci-security-scan.yml.

### E-011 Minor: Embedded interpreter is Python 3.12.10, the last 3.12 build with binary installers
**Dimension:** Runtime
**Evidence:** scripts/build_native_app_payload.py:126 and the workflow's `civiccast-python-3.12.10-embed-amd64.zip` (native-beta-candidate-artifacts.yml, "Build and verify signed component packs" step).
**Why it matters:** From my knowledge python.org publishes 3.12.11+ security releases only as source, so the shipped runtime stops receiving stdlib security fixes unless the project builds its own interpreter or moves to a Python line that still has binaries. Not verified online.
**Fix path:** Record a policy: move to a supported Python with embeddable binaries, or build 3.12.x from source with a pinned hash; add a CI check for interpreter age.

### E-012 Minor: Single pack-signing key with no expiry, rotation or revocation path in the trust model
**Dimension:** Correctness
**Evidence:** civiccast/apps/installer/src-tauri/src/native_packs.rs:234-259 (one embedded ed25519 key + key id); native_distribution.rs has no freshness/expiry field (grep for expires/not_after/generated_at is empty). Downgrade is blocked by requiring `product_version` to equal the installer's own (native_distribution.rs:127-190), which is good.
**Why it matters:** If the key leaks, already-shipped installers cannot be told to distrust it; a signed index/pack stays valid forever for that installer version.
**Fix path:** Add a validity window to signed manifests and support a list of embedded key ids so a rotated key can be shipped; document the compromise procedure.

### E-013 Minor: Installer webview has no Content-Security-Policy
**Dimension:** Correctness
**Evidence:** civiccast/apps/installer/src-tauri/tauri.conf.json (no `app.security.csp`; `withGlobalTauri: true`); tauri.native.conf.json also none; capabilities/default.json grants `core:default` + `allow-installer-actions` to all windows.
**Why it matters:** The window only loads bundled assets today, but with the global IPC exposed and shell-spawning commands (E-003), any future injected markup becomes command execution.
**Fix path:** Set a strict `csp` (`default-src 'self'; script-src 'self'; connect-src ipc: http://ipc.localhost`) and turn off `withGlobalTauri` if the bundled code does not need it.

### E-014 Minor: Public marketing page loads Google Fonts and three.js from third-party CDNs, no SRI
**Dimension:** Docs
**Evidence:** docs/index.html:2-5 (fonts.googleapis.com, fonts.gstatic.com, cdnjs.cloudflare.com/three.js r128 without `integrity=`).
**Why it matters:** This is the GitHub Pages site, not the product: the portals and installer UI contain no CDN fonts, scripts or telemetry (verified by grep of portal-operator, portal-public and installer sources). But CODE_SIGNING_POLICY.md promises no external transfers, and a visitor's IP goes to Google/Cloudflare.
**Fix path:** Self-host the font and script in docs/assets (or add `integrity` + `crossorigin`), or scope the privacy sentence to "the installed product".

### E-015 Minor: Workflow-dispatch inputs interpolated straight into PowerShell on the self-hosted runner; single-quote path injection in the publish script
**Dimension:** Correctness
**Evidence:** .github/workflows/gate-a-station-acceptance.yml:227,526,926; gate-b-reboot-soak.yml:123-124,174-178; publish-staged-kit.yml:71,96-97; benchmark-caption-runtime.yml:109-111 (`${{ inputs.* }}` inside `run:`). scripts/release/publish_beta_candidate.py:159,207 (`'{setup}'` single-quoted into `powershell -Command`).
**Why it matters:** A dispatcher with write access could break out of quoting and run commands on the owner's lab box (they could already push a workflow, so little extra privilege); a kit path containing `'` breaks or injects into the publish script. Self-hosted jobs are correctly not triggered by pull_request.
**Fix path:** Pass inputs through `env:` and read `$env:NAME` (as sign-native-installer.yml already does); in the publish script pass the path as a script argument or double any single quotes.

### E-016 Nit: Test/sample credentials and local paths committed
**Dimension:** Docs
**Evidence:** civiccast/apps/ott-native/tizen/fix_signing_profile.py:49-50 (Tizen SDK public sample-cert passwords, annotated); gate-b/answer/autounattend.xml:105 (`CHANGE-ME-BEFORE-USE`, PlainText); 15 tracked files embed `C:\Users\scott` paths (ops/beta10-oversight/*, docs/history/*); gate-b/scripts/In-Vm-GateB-Agent.ps1:158 generates the disposable-VM password with `Get-Random` (not a CSPRNG) and still reads the retired `SetupNonce`.
**Why it matters:** None are live secrets; noise for scanners and minor hygiene cost in a public repo.
**Fix path:** Keep the annotations; consider moving ops/beta10-oversight out of the release repo; refresh the Gate B agent to the nonce-free setup flow.

## What's working
- No committed secrets in tree or recent history (see header); secrets flow only through GitHub secrets/vars, and the signing key file is deleted in `finally` blocks.
- Pack trust chain is strong: ed25519 signed manifests verified by one code path (`native_packs::verify_pack`), dev keys refused without an explicit switch (native_packs.rs:234-247), per-file SHA-256 on extraction, rejects `..`, `:`, reserved device names, case-folded duplicates and reparse points (native_packs.rs:1292-1335,1478), extracts to `.partial` then re-walks the tree, and the index is product-version pinned (no downgrade).
- Downloads: HTTPS-only with a redirect policy, pinned (bytes, sha256) for HuggingFace/Ollama files and the build-time downloads (interpreter, licenses, CUDA wheels, PyAV, TSDuck all hash-pinned; zip-slip guard in tsduck_install.py:196-210); `--require-hashes --no-deps --no-index` for the app payload; `cargo test --locked`; `npm ci`; all four requirements files are hash-locked.
- Installer subprocess calls use argument vectors and absolute `$SYSDIR\sc.exe`, and fail closed (D4 service/firewall steps abort the install on error); vc_redist is validated at build time.
- Server hardening defaults: control plane binds 127.0.0.1 with no 0.0.0.0 anywhere in code; CORS deny-all by default and wildcard is a startup error; CSP, X-Frame-Options, nosniff on every response; `/docs` and `/redoc` off and `/openapi.json` token-gated on stations; staff tokens PBKDF2-hashed with constant-time compare; role dependencies fail closed with 401 when no identity (auth/roles.py:85-91) and a CI AST test enforces roles on `/api/staff` mutations; media serving has a path-traversal guard (stream/media_router.py:149-150); Postgres uses scram-sha-256 on 127.0.0.1 only.
- Sandbox lab: network disabled, payload and scripts mapped read-only, only output/hoststore writable; no TrustedHosts/Defender/firewall disabling anywhere.
- Privacy: portal-operator, portal-public and installer sources contain no CDN assets, fonts, analytics or telemetry; the RFC3161 TSA client defaults to FreeTSA only via DI/opt-in.
- Pip allow-list entries carry dated, reasoned justifications and nltk is verified absent from the shipped lock.

## Not checked
- GitHub repository/organization settings (environment protection, branch protection, secret scoping, fork-PR policy, Actions permissions) - only the tree was read.
- Online advisories for any lock file (pip, npm, Cargo); version-based remarks are from memory and flagged as such.
- Dynamic behaviour: nothing was started or fuzzed; the SSRF, cmd.exe injection and DNS-rebinding findings are from code reading, not exploited.
- Full route-by-route authorization of every router outside `/api/staff` (spot-checked media-lifecycle, subscribe, media, webhooks/paywall; the policy test was relied on for the rest).
- Contents of the two committed CI evidence zips, the ott-native mobile/TV apps, ctv-reference, control_room/tsr_service, Roku/Tizen/iOS packages, and the NSIS script beyond the security-relevant hooks.
- Windows ACLs on installed directories and the Postgres data dir (civiccast/native/pgdata_acl.py not reviewed in depth); registry-stored DatabaseUrl protection.
- Git history older than the last 200 commits.
