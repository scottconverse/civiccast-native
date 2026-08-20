# Recovery-Kit Acknowledgement Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the first-admin recovery-kit lockout: the operator cannot proceed past the one-time recovery-kit screen until they have genuinely saved or printed the codes and confirmed it, every copy-claim is honest (no file is ever claimed saved unless it was), and the acknowledgement is durably recorded server-side.

**Architecture:** Backend records an `acknowledged` flag in the existing station-state JSON (`recovery` section) with a new local-setup-guarded endpoint `POST /api/setup/recovery-kit/acknowledge`; `StationSetupState` exposes `recovery_kit_acknowledged` so any client can see an unconfirmed kit. Frontend `SetupScreen` blocks everything after setup completion behind: kit action (Save/Print click) → confirmation checkbox → Continue (calls the endpoint), plus a `beforeunload` guard and an honest warning banner on revisit when the server has no acknowledgement record.

**Tech Stack:** FastAPI + Pydantic (installer router/service/station_state), React + TanStack Query (portal-operator), Playwright e2e, pytest.

**Scott's spec (verbatim intent):** "don't let people leave that screen until they've genuinely saved or printed the codes, and don't tell them it saved a file unless it really did. And whenever you do turn the 'save a file' part back on, make sure that file isn't just sitting on the computer as plain readable text." No server-side kit file is added in this change (YAGNI) — so requirement 3 stays moot by design; the browser download is the only file and it is user-initiated.

**Bug recap (verified in code):** `complete_first_admin_setup` (civiccast/installer/station_state.py:85) stores only code hashes and the free-text `destination`; no file is written. `SetupScreen.tsx` shows the kit once (`RecoveryKitPanel`, line 99) and immediately renders `StationAdminTools` below it (`showAdminTools`, line 813) — nothing forces a save/print. A clerk who clicks past is permanently locked out if the password is lost.

**Also fixed here (found during planning):** PR #127/#129 relabeled the destination field to "Where will you keep the recovery kit?" but `e2e/setup-real-boundary.spec.ts:214` and `e2e/operator-first-mile.spec.ts:647` still do `getByLabel('Recovery kit destination')` — both specs are currently broken. The installer contract (service.py:460) still claims `downloadable_pdf` media (it is a .txt download) and a `contains` list that does not match the real kit.

---

### Task 1: Backend — acknowledged flag in station state + read-back

**Files:**
- Modify: `civiccast/civiccast/installer/models.py` (StationSetupState, ~line 333)
- Modify: `civiccast/civiccast/installer/station_state.py` (read_station_setup_state ~line 60, complete_first_admin_setup raw_state ~line 155)
- Test: `tests/installer/test_installer_api.py`

- [x] **Step 1: Write the failing test**

Append to `tests/installer/test_installer_api.py` (match the file's existing monkeypatch/TestClient style):

```python
def test_station_state_reports_unacknowledged_recovery_kit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    before = client.get("/api/setup/station-state")
    assert before.status_code == 200
    assert before.json()["recovery_kit_acknowledged"] is False

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200

    state = client.get("/api/setup/station-state")
    assert state.status_code == 200
    payload = state.json()
    assert payload["setup_complete"] is True
    assert payload["recovery_kit_acknowledged"] is False
    assert "recovery kit" in payload["next_step"].lower()
```

- [x] **Step 2: Run test to verify it fails**

Run (venv): `pytest tests/installer/test_installer_api.py::test_station_state_reports_unacknowledged_recovery_kit -q`
Expected: FAIL — `KeyError: 'recovery_kit_acknowledged'` (field absent).

- [x] **Step 3: Implement**

`models.py` — add to `StationSetupState` after `recovery_kit_id`:

```python
    recovery_kit_acknowledged: bool = False
```

`station_state.py` — in `complete_first_admin_setup`, extend the `"recovery"` dict:

```python
        "recovery": {
            "kit_id": kit_id,
            "generated_at": generated_at.isoformat(),
            "destination": request.recovery_kit_destination.strip(),
            "acknowledged": False,
            "acknowledged_at": None,
            "code_hashes": [_hash_secret(code, salt=kit_id) for code in recovery_codes],
        },
```

`station_state.py` — in `read_station_setup_state`, replace the completed-state return:

```python
    recovery = raw.get("recovery", {})
    recovery_kit_id = str(recovery.get("kit_id") or profile.recovery_kit_id)
    acknowledged = bool(recovery.get("acknowledged"))
    next_step = (
        "Open System Health and confirm the station is ready for a private rehearsal."
        if acknowledged
        else "Confirm the recovery kit is saved or printed before the first public meeting."
    )
    return StationSetupState(
        status="complete",
        setup_complete=True,
        profile=profile,
        recovery_kit_created=True,
        recovery_kit_id=recovery_kit_id,
        recovery_kit_acknowledged=acknowledged,
        operator_console_url=operator_console_url,
        next_step=next_step,
    )
```

Backward compatibility: pre-existing state files have no `acknowledged` key → reads as `False` (honest: CivicCast has no record the kit was saved).

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/installer/test_installer_api.py::test_station_state_reports_unacknowledged_recovery_kit -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add tests/installer/test_installer_api.py civiccast/installer/models.py civiccast/installer/station_state.py
git commit -s -m "feat(installer): track recovery-kit acknowledgement in station state (refs recovery-kit lockout)"
```

### Task 2: Backend — acknowledge endpoint

**Files:**
- Modify: `civiccast/civiccast/installer/station_state.py` (new function + error class)
- Modify: `civiccast/civiccast/installer/models.py` (request model)
- Modify: `civiccast/civiccast/installer/service.py` (passthrough, near read_station_setup ~line 653)
- Modify: `civiccast/civiccast/installer/router.py` (public endpoint after `/first-admin` ~line 622; import additions)
- Test: `tests/installer/test_installer_api.py`

- [x] **Step 1: Write the failing tests**

```python
def test_recovery_kit_acknowledge_records_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert setup.status_code == 200

    ack = client.post("/api/setup/recovery-kit/acknowledge", json={"confirmed": True})
    assert ack.status_code == 200
    assert ack.json()["recovery_kit_acknowledged"] is True
    assert "rehearsal" in ack.json()["next_step"].lower()

    state = client.get("/api/setup/station-state")
    assert state.json()["recovery_kit_acknowledged"] is True

    raw = json.loads((tmp_path / "station-state.json").read_text(encoding="utf-8"))
    assert raw["recovery"]["acknowledged"] is True
    assert raw["recovery"]["acknowledged_at"]


def test_recovery_kit_acknowledge_requires_setup_and_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())

    too_early = client.post("/api/setup/recovery-kit/acknowledge", json={"confirmed": True})
    assert too_early.status_code == 409

    setup = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "safe",
        },
    )
    assert setup.status_code == 200

    not_confirmed = client.post("/api/setup/recovery-kit/acknowledge", json={"confirmed": False})
    assert not_confirmed.status_code == 400
    state = client.get("/api/setup/station-state")
    assert state.json()["recovery_kit_acknowledged"] is False
```

(`import json` already exists at the top of the test file — verify; add if missing.)

- [x] **Step 2: Run tests to verify they fail**

Run: `pytest tests/installer/test_installer_api.py -q -k recovery_kit_acknowledge`
Expected: FAIL — 404 (route does not exist).

- [x] **Step 3: Implement**

`station_state.py` — new error class next to the existing ones:

```python
class StationSetupNotCompleteError(RuntimeError):
    """Raised when a recovery-kit action needs completed first-admin setup."""
```

and new function after `complete_first_admin_setup`:

```python
def acknowledge_recovery_kit(*, operator_console_url: str) -> StationSetupState:
    """Record that the operator saved or printed the one-time recovery kit."""

    raw = _load_raw_state()
    if not raw.get("setup_complete"):
        raise StationSetupNotCompleteError(
            "First-admin setup is not complete, so there is no recovery kit to confirm."
        )
    recovery = raw.setdefault("recovery", {})
    recovery["acknowledged"] = True
    recovery["acknowledged_at"] = datetime.now(UTC).isoformat()
    _save_raw_state(raw)
    return read_station_setup_state(operator_console_url=operator_console_url)
```

`models.py` — new request model next to `FirstAdminSetupRequest` (mirror its `model_config` style):

```python
class RecoveryKitAcknowledgeRequest(BaseModel):
    """Operator confirmation that the one-time recovery kit is saved or printed."""

    model_config = ConfigDict(extra="forbid")

    confirmed: bool
```

`service.py` — passthrough next to `read_station_setup`:

```python
def acknowledge_station_recovery_kit(*, console_url: str | None = None) -> StationSetupState:
    """Record the operator's recovery-kit save/print confirmation."""

    return acknowledge_recovery_kit(
        operator_console_url=console_url or operator_console_url(),
    )
```

(import `acknowledge_recovery_kit` from `civiccast.installer.station_state` alongside the existing station_state imports.)

`router.py` — after `public_first_admin_setup` (~line 622), guarded the same way as the storage mutation:

```python
@public_router.post(
    "/recovery-kit/acknowledge",
    response_model=StationSetupState,
    summary="Record that the operator saved or printed the one-time recovery kit",
)
def public_recovery_kit_acknowledge(
    payload: RecoveryKitAcknowledgeRequest,
    request: Request,
    _setup_nonce: SetupNonceHeader = None,
) -> StationSetupState:
    _require_local_setup_mutation(request)
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set confirmed=true only after the recovery kit is saved or printed.",
        )
    try:
        return acknowledge_station_recovery_kit()
    except StationSetupNotCompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
```

(add `RecoveryKitAcknowledgeRequest`, `acknowledge_station_recovery_kit`, `StationSetupNotCompleteError` to the router's existing imports; `StationSetupState` is already imported.)

- [x] **Step 4: Run tests to verify they pass**

Run: `pytest tests/installer/test_installer_api.py -q`
Expected: ALL PASS (including pre-existing tests).

- [x] **Step 5: Commit**

```bash
git add civiccast/installer/ tests/installer/test_installer_api.py
git commit -s -m "feat(installer): recovery-kit acknowledge endpoint records save/print confirmation"
```

### Task 3: Backend — honest first-admin contract copy

**Files:**
- Modify: `civiccast/civiccast/installer/service.py:460-517` (build_first_admin_setup_contract)
- Test: `tests/installer/test_installer_api.py::test_first_admin_contract_is_operator_safe_and_recovery_kit_first` (line 339)

- [x] **Step 1: Extend the existing contract test (failing first)**

In `test_first_admin_contract_is_operator_safe_and_recovery_kit_first`, after the `"printable" in media` assertion add:

```python
    assert "downloadable_pdf" not in payload["recovery_kit"]["media"]
    assert "downloadable_text_file" in payload["recovery_kit"]["media"]
    assert "one-time recovery codes" in payload["recovery_kit"]["contains"]
    destination_field = next(
        field for field in payload["required_fields"] if field["id"] == "recovery-kit-destination"
    )
    assert destination_field["label"] == "Where will you keep the recovery kit?"
    assert "does not save" in destination_field["help_text"]
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/installer/test_installer_api.py::test_first_admin_contract_is_operator_safe_and_recovery_kit_first -q`
Expected: FAIL on `downloadable_pdf`.

- [x] **Step 3: Implement honest copy in `build_first_admin_setup_contract`**

Replace the destination field entry:

```python
            FirstAdminRequiredField(
                id="recovery-kit-destination",
                label="Where will you keep the recovery kit?",
                help_text=(
                    "A note for the station record of where the kit will be kept. "
                    "CivicCast does not save the kit to that location; save or print "
                    "the kit from the setup screen."
                ),
            ),
```

Replace `media` and `contains` in `RecoveryKitContract`:

```python
            media=["printable", "downloadable_text_file", "offline_copy"],
            contains=[
                "station identity",
                "admin account identifier",
                "one-time recovery codes",
                "recovery-code instructions",
                "credential-rotation instructions",
            ],
```

(Check `RecoveryKitContract` in models.py first — if `media`/`contains` are `Literal`-constrained, update the Literal values to match; if plain `list[str]`, no model change.)

- [x] **Step 4: Run to verify it passes**

Run: `pytest tests/installer/test_installer_api.py -q`
Expected: ALL PASS.

- [x] **Step 5: Commit**

```bash
git add civiccast/installer/service.py civiccast/installer/models.py tests/installer/test_installer_api.py
git commit -s -m "fix(installer): first-admin contract claims only what the kit really is (text download, real contents)"
```

### Task 4: Regenerate OpenAPI artifacts + frontend API client

**Files:**
- Regenerate: `civiccast/apps/portal-operator/src/types/api.generated.ts`
- Modify: `civiccast/apps/portal-operator/src/api/client.ts` (~line 312)

- [x] **Step 1: Regenerate types**

From `civiccast/civiccast/apps/portal-operator` (with the repo venv python on PATH):
`npm run generate:api`
Expected: `api.generated.ts` `StationSetupState` gains `recovery_kit_acknowledged?: boolean`; new `RecoveryKitAcknowledgeRequest` interface appears.

- [x] **Step 2: Add the client function** (after `completePublicFirstAdminSetup`):

```typescript
export function acknowledgeRecoveryKit(): Promise<StationSetupState> {
  return request<StationSetupState>('/api/setup/recovery-kit/acknowledge', {
    method: 'POST',
    body: { confirmed: true },
  })
}
```

- [x] **Step 3: Typecheck**

From portal-operator: `npm run build` (or `npx tsc -b` if build is slow — use the project's standard check).
Expected: clean.

- [x] **Step 4: Commit**

```bash
git add civiccast/apps/portal-operator/src/types/api.generated.ts civiccast/apps/portal-operator/src/api/client.ts
git commit -s -m "feat(operator): API client for recovery-kit acknowledgement"
```

### Task 5: Frontend — the gate in SetupScreen

**Files:**
- Modify: `civiccast/apps/portal-operator/src/screens/SetupScreen.tsx` (RecoveryKitPanel line 99-167; SetupScreen body lines 748-1093)

- [x] **Step 1: Rework `RecoveryKitPanel`** — track a real save/print action, require the checkbox, surface Continue:

```tsx
function RecoveryKitPanel({
  setup,
  onAcknowledge,
  ackPending,
  ackError,
}: {
  setup: FirstAdminSetupResponse
  onAcknowledge: () => void
  ackPending: boolean
  ackError: unknown
}) {
  const [kitActionTaken, setKitActionTaken] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const printable = useMemo(/* unchanged */)

  const download = () => {
    /* existing blob download body unchanged */
    setKitActionTaken(true)
  }
  const print = () => {
    window.print()
    setKitActionTaken(true)
  }
  ...
```

Panel additions below the existing buttons (keep Print kit / Save kit, point them at `print`/`download`):

```tsx
      <p className="m-0 text-xs" style={{ color: 'var(--cc-ink-2)' }}>
        Save kit downloads a plain-text file to this browser&apos;s Downloads folder. Print kit
        opens your system print dialog. CivicCast keeps only scrambled verification copies of
        these codes and can never show them again.
      </p>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={!kitActionTaken}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>
          I have saved or printed these recovery codes and stored them away from this computer.
          {!kitActionTaken && (
            <span className="block text-xs" style={{ color: 'var(--cc-ink-3)' }}>
              Use Print kit or Save kit first.
            </span>
          )}
        </span>
      </label>
      <div>
        <button
          type="button"
          disabled={!confirmed || ackPending}
          onClick={onAcknowledge}
          className="rounded-md px-4 py-2 text-sm font-semibold"
          style={{
            background: !confirmed || ackPending ? 'var(--cc-surface-3)' : 'var(--cc-brand)',
            color: !confirmed || ackPending ? 'var(--cc-ink-3)' : 'var(--cc-brand-ink)',
          }}
        >
          {ackPending ? 'Recording confirmation...' : 'Continue to the console'}
        </button>
      </div>
      {ackError != null && (
        <div role="alert" className="rounded-md p-3 text-xs" style={{ background: 'var(--cc-err-soft)', color: 'var(--cc-err)' }}>
          {apiMessage(ackError, 'Could not record the confirmation. Try again.')}
        </div>
      )}
```

Also change the panel intro copy (line 132-134) to be blunt about the stakes:

```tsx
          These codes are shown once and CivicCast cannot show them again. If the admin password
          is ever lost, these codes are the only way back in. Save or print them now.
```

- [x] **Step 2: Gate the rest of the screen in `SetupScreen`**

```tsx
  const [kitAcknowledged, setKitAcknowledged] = useState(false)
  const ackMutation = useMutation({
    mutationFn: acknowledgeRecoveryKit,
    onSuccess: () => {
      setKitAcknowledged(true)
      void queryClient.invalidateQueries({ queryKey: ['station-setup-state'] })
    },
  })
  const kitGateActive = Boolean(completed) && !kitAcknowledged
  const showAdminTools =
    Boolean(stateQuery.data?.setup_complete || completed || authenticated) && !kitGateActive

  useEffect(() => {
    if (!kitGateActive) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [kitGateActive])
```

Render block changes at the bottom (line 1088-1090):

```tsx
      {completed && (
        <RecoveryKitPanel
          setup={completed}
          onAcknowledge={() => ackMutation.mutate()}
          ackPending={ackMutation.isPending}
          ackError={ackMutation.error}
        />
      )}
      {authenticated && !kitGateActive && <SignedInPanel auth={authenticated} />}
      {showAdminTools && <StationAdminTools canManageProviders={canManageProviders} />}
```

(`acknowledgeRecoveryKit` joins the client imports; `useEffect` is already imported.)

- [x] **Step 3: Revisit warning when the server has no acknowledgement record**

Inside the existing `stateQuery.data?.setup_complete && !completed` block (line 870), before the "Setup complete" section:

```tsx
          {stateQuery.data.recovery_kit_acknowledged === false && (
            <section
              role="alert"
              className="rounded-md p-4 lg:col-span-2"
              style={{ background: 'var(--cc-warn-soft, var(--cc-err-soft))', border: '1px solid var(--cc-warn, var(--cc-err))' }}
            >
              <h2 className="m-0 text-base font-semibold">Recovery kit never confirmed</h2>
              <p className="m-0 mt-1 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
                CivicCast has no record that this station&apos;s recovery codes were saved or
                printed. They were shown once during setup and cannot be shown again. Find the
                saved or printed kit now — without those codes, a lost admin password locks this
                station out permanently.
              </p>
              <button
                type="button"
                disabled={ackMutation.isPending}
                onClick={() => ackMutation.mutate()}
                className="mt-3 rounded-md px-3 py-2 text-sm font-semibold"
                style={{ background: 'var(--cc-ink)', color: 'var(--cc-ink-inv)' }}
              >
                I found the kit — it is stored safely
              </button>
            </section>
          )}
```

(Check `--cc-warn-soft`/`--cc-warn` exist in the theme css; the `var(..., fallback)` form keeps it safe either way. After a successful ack the state query invalidation removes the banner.)

- [x] **Step 4: Build/typecheck**

From portal-operator: `npm run build`
Expected: clean.

- [x] **Step 5: Commit**

```bash
git add civiccast/apps/portal-operator/src/screens/SetupScreen.tsx
git commit -s -m "fix(operator): recovery-kit screen blocks until codes are genuinely saved/printed and confirmed"
```

### Task 6: E2E — fix stale labels + prove the gate

**Files:**
- Modify: `civiccast/apps/portal-operator/e2e/setup-real-boundary.spec.ts:214` (+ gate assertions after line 217)
- Modify: `civiccast/apps/portal-operator/e2e/operator-first-mile.spec.ts:647` (+ matching gate steps — read surrounding code first and mirror its flow)

- [x] **Step 1: Fix both stale labels**

`getByLabel('Recovery kit destination')` → `getByLabel('Where will you keep the recovery kit?')` in both specs.

- [x] **Step 2: Add gate assertions to `setup-real-boundary.spec.ts`** right after `await expect(page.getByText('Recovery kit ready')).toBeVisible()`:

```typescript
  // Lockout gate: nothing past the kit until save/print is confirmed.
  await expect(page.getByLabel('Backup folder')).toHaveCount(0)
  const confirmBox = page.getByRole('checkbox', {
    name: /I have saved or printed these recovery codes/,
  })
  await expect(confirmBox).toBeDisabled()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Save kit' }).click()
  const kitDownload = await downloadPromise
  expect(kitDownload.suggestedFilename()).toMatch(/^civiccast-recovery-kit-rk_.+\.txt$/)
  await confirmBox.check()
  await page.getByRole('button', { name: 'Continue to the console' }).click()
  await expect(page.getByLabel('Backup folder')).toBeVisible()
```

(The existing `Backup folder` interaction at line 236 then proceeds as before. If the admin-tools section reveals asynchronously, the final `toBeVisible` already waits.)

- [x] **Step 3: Apply the same pattern to `operator-first-mile.spec.ts`** after its first-admin submission — read lines ~600-700 first; insert the Save kit → checkbox → Continue sequence before any step that uses admin tools.

- [x] **Step 4: Run the touched specs**

From portal-operator (needs built public portal: `npm run prepare:public-portal`, and repo venv python):
`npx playwright test e2e/setup-real-boundary.spec.ts e2e/operator-first-mile.spec.ts`
Expected: PASS. (Honest note for the report: these were broken before this change because of the stale label.)

- [x] **Step 5: Commit**

```bash
git add civiccast/apps/portal-operator/e2e/
git commit -s -m "test(e2e): recovery-kit gate proof + fix labels broken by the destination-field relabel"
```

### Task 7: Full gates, docs truth, PR

- [x] **Step 1: Full backend suite** (venv + ffmpeg on PATH):
`$env:CIVICCAST_POSTGRES_TEST_URL='postgresql+psycopg://postgres@127.0.0.1:54329/postgres'; pytest -q`
Expected: 0 failed, zero exclusions (~1765+ passed).

- [x] **Step 2: Docs truth pass** — update `CAPABILITIES.md` / `docs/USER-MANUAL.md` / `docs/spec/spec.md` ONLY where they describe the recovery-kit flow, in the same commit style as the change: the setup screen now requires a recorded save/print confirmation before the console unlocks; the kit is a browser text download/printout; CivicCast stores only hashes. No version bumps, no re-tag.

- [x] **Step 3: Push branch + PR**

```bash
git checkout -b work/recovery-kit-ack-gate   # (do this FIRST, before Task 1, if not already on it)
git push -u origin work/recovery-kit-ack-gate
gh pr create --title "fix: recovery-kit lockout — forced save/print acknowledgement gate" --body "<summary + test evidence>"
```

Merge per standing merge authority after gates pass; reference the spawned-task/bug description.

---

## Self-review notes
- Spec coverage: (1) can't leave until genuinely saved/printed → Task 5 gate + Task 2 server record + Task 6 proof; (2) no false file-saved claims → Task 3 contract + Task 5 copy; (3) secure server-side file → intentionally not added (no file is written at all; documented).
- The two stale-label e2e fixes are in-scope because this change touches the same screen and the specs must pass to prove the gate.
- Branch note: create `work/recovery-kit-ack-gate` from `main` before Task 1.
