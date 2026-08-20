import { mkdir, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'

import { expect, test, type TestInfo } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const readiness = {
  generated_at: '2026-06-30T12:00:00Z',
  ready_for_on_air: false,
  station_device_ready: false,
  // Mirrors the REAL string from civiccast/control_room/service.py.
  summary: 'Control-room configuration has 1 blocker(s) before On-Air use.',
  devices_configured: 1,
  devices_enabled: 0,
  devices_missing_profile: ['dev_obs'],
  surfaces_configured: 1,
  cues_configured: 1,
  open_sessions: 0,
  open_on_air_sessions: 0,
  checks: [
    {
      check_id: 'tsr-control-service',
      label: 'TSR control service',
      status: 'blocked',
      severity: 'blocker',
      detail: 'The Node TSR control service is not configured; live cue fire/probe paths fail closed.',
      operator_action: 'Configure and supervise CIVICAST_CONTROL_ROOM_TSR_URL before opening On-Air Mode.',
      evidence_ref: 'control_room.tsr_client',
    },
    {
      check_id: 'station-device-evidence',
      label: 'Station-device evidence',
      status: 'warning',
      severity: 'warning',
      detail:
        "This control room has not been verified against your station's real equipment yet.",
      operator_action: 'Do not claim station-device readiness until station-device evidence exists.',
      evidence_ref: 'control_room.lpm_lab',
    },
  ],
  lpm_profiles: [
    {
      profile_id: 'fixed-studio-livestreaming',
      label: 'Fixed Studio + Livestreaming Studio',
      priority: 1,
      proof_status: 'contract_only_not_station_device_evidence',
      devices: [
        {
          profile_id: 'fixed-studio-livestreaming',
          device_contract_id: 'fixed-vmix-streaming-pc',
          label: 'vMix Streaming PC',
          device_class: 'vmix',
          integration_surface: 'vMix HTTP /api',
          proof_level: 'mocked',
          station_device_evidence_required: true,
          required_checks_count: 7,
        },
      ],
      required_absences: [],
      egress_destinations: ['Castr', 'YouTube'],
      not_claimed: ['No station-device readiness is claimed.'],
    },
  ],
  proof_boundary: 'Readiness is not clean Windows install evidence or station-device evidence.',
}

const readyReadiness = {
  ...readiness,
  ready_for_on_air: true,
  summary:
    "Ready for local dry runs. On-air readiness is confirmed once a check against this room's actual devices passes.",
  devices_enabled: 1,
  devices_missing_profile: [],
  checks: [
    {
      check_id: 'tsr-control-service',
      label: 'TSR control service',
      status: 'passed',
      severity: 'info',
      detail: 'A TSR control client is configured for local cue fire/probe paths.',
      operator_action: 'No action needed.',
      evidence_ref: 'control_room.tsr_client',
    },
    readiness.checks[1],
  ],
}

const surface = { surface_id: 'srf', label: 'Chamber', assigned_role: 'meeting_operator', created_by: 'operator', created_at: 'x', updated_at: 'x' }
const device = {
  device_id: 'dev_obs',
  label: 'Studio OBS',
  kind: 'obs',
  transport: 'websocket',
  host: '127.0.0.1',
  port: 4455,
  enabled: true,
  notes: null,
  secret_ref: null,
  created_at: 'x',
  updated_at: 'x',
}
const cue = {
  cue_id: 'cue_1',
  surface_id: 'srf',
  label: 'Take CAM2',
  device_id: 'dev_obs',
  action: 'scene',
  payload: { scene: 'CAM2' },
  confirm_required: true,
  bank: 0,
  position: 0,
  proof_boundary: 'Local dry-run only.',
  created_at: 'x',
}
// A second, non-safe-state cue, distinct from `cue` above (which the
// rollback test uses as the safe-state cue) so a click on "Take CAM1" can't
// ambiguously match the Safe State panel's own plan/fire controls.
const targetCue = {
  cue_id: 'cue_2',
  surface_id: 'srf',
  label: 'Take CAM1',
  device_id: 'dev_obs',
  action: 'scene',
  payload: { scene: 'CAM1' },
  confirm_required: true,
  bank: 0,
  position: 1,
  proof_boundary: 'Local dry-run only.',
  created_at: 'x',
}
const plan = {
  cue_id: 'cue_1',
  surface_id: 'srf',
  device_id: 'dev_obs',
  label: 'Take CAM2',
  action: 'scene',
  resolved_payload: { scene: 'CAM2' },
  command_preview: 'Studio OBS: set scene -> CAM2',
  ready_to_send: true,
  confirm_required: true,
  material_state_fingerprint: 'abc123def456abc123def456abc123def456abc123def456abc123def456abcd',
  take_delay_ms: 0,
  post_roll_ms: 0,
  operator_action: 'Fire to send.',
  proof_boundary: 'Cue plan preview only.',
}
const targetCuePlan = {
  ...plan,
  cue_id: 'cue_2',
  label: 'Take CAM1',
  resolved_payload: { scene: 'CAM1' },
  command_preview: 'Studio OBS: set scene -> CAM1',
  material_state_fingerprint: 'def456abc123def456abc123def456abc123def456abc123def456abc123def4',
}

async function mockControlRoom(
  page: import('@playwright/test').Page,
  roles: string[],
  readinessBody = readiness,
) {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'operator',
        operator_display_name: 'Operator',
        token_id: 'token',
        scopes: ['operator'],
        roles,
      }),
    })
  })
  await page.route('**/api/version', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ version: '1.0.0-rc11' }),
    })
  })
  await page.route('**/api/staff/control-room/readiness', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(readinessBody),
    })
  })
  await page.route('**/api/staff/control-room/devices', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([device]),
    })
  })
  await page.route('**/api/staff/control-room/devices/dev_obs/probe', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ reachable: false, detail: 'OBS websocket intentionally absent in this walkthrough.' }),
    })
  })
  await page.route('**/api/staff/control-room/surfaces**', async (route) => {
    const url = new URL(route.request().url())
    const body = url.pathname.endsWith('/srf')
      ? { surface, cues: [cue, targetCue] }
      : [surface]
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })
  await page.route('**/api/staff/control-room/sessions', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: 's1',
        surface_id: 'srf',
        operator_id: 'operator',
        operator_name: 'Operator',
        program_feed_source_ref: 'public:control-room',
        mode: 'on_air',
        safe_state_cue_id: 'cue_1',
        state: 'open',
        started_at: '2026-06-30T12:00:00Z',
        on_air_expires_at: '2026-06-30T12:30:00Z',
        ended_at: null,
      }),
    })
  })
  await page.route('**/api/staff/control-room/sessions/s1/audit', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
  await page.route('**/api/staff/control-room/sessions/s1/cues/cue_1/plan', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(plan),
    })
  })
  await page.route('**/api/staff/control-room/sessions/s1/cues/cue_2/plan', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(targetCuePlan),
    })
  })
  await page.route('**/api/staff/control-room/sessions/s1/cues/cue_1/fire', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        event_id: 'e1',
        session_id: 's1',
        cue_id: 'cue_1',
        operator_id: 'operator',
        device_id: 'dev_obs',
        action: 'scene',
        result: 'fired',
        fired_at: '2026-06-30T12:00:01Z',
        detail: {},
      }),
    })
  })
  await page.route('**/api/staff/control-room/sessions/s1/rollback', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        event_id: 'e_rollback',
        session_id: 's1',
        cue_id: 'cue_1',
        operator_id: 'operator',
        device_id: 'dev_obs',
        action: 'scene',
        result: 'fired',
        fired_at: '2026-06-30T12:00:02Z',
        detail: {},
      }),
    })
  })
  await page.route('**/api/staff/installer/support-bundle', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        bundle_id: 'bundle_1',
        generated_at: '2026-06-30T12:00:02Z',
        path: 'C:\\CivicCast\\support\\bundle.zip',
        sha256: 'a'.repeat(64),
        redacted: true,
        contains: ['control-room-audit'],
        excludes: ['secrets'],
        next_step: 'Attach this bundle to support.',
      }),
    })
  })
}

async function expectNoWcagAxeViolations(page: import('@playwright/test').Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  if (results.violations.length > 0) {
    const summary = results.violations
      .map((v) => {
        const nodes = v.nodes
          .map((n) => `${n.target.join(', ')} :: ${n.failureSummary ?? 'no failure summary'}`)
          .join('\n')
        return `[${v.impact}] ${v.id}: ${v.help}\n${nodes}`
      })
      .join('\n')
    throw new Error(`axe-core found ${results.violations.length} WCAG violation(s) on ${label}:\n${summary}`)
  }
}

async function captureUiEvidence(
  page: import('@playwright/test').Page,
  testInfo: TestInfo,
  name: string,
) {
  const screenshotPath = testInfo.outputPath(`${name}.png`)
  const htmlPath = testInfo.outputPath(`${name}.html`)
  await page.screenshot({ path: screenshotPath, fullPage: true })
  await mkdir(dirname(htmlPath), { recursive: true })
  await writeFile(htmlPath, await page.content(), 'utf8')
  await testInfo.attach(`${name}.png`, { path: screenshotPath, contentType: 'image/png' })
  await testInfo.attach(`${name}.html`, { path: htmlPath, contentType: 'text/html' })
}

test.describe('control-room readiness panel', () => {
  test('operator route labels contract-only readiness and passes axe', async ({ page }, testInfo) => {
    await mockControlRoom(page, ['meeting_operator'])
    await page.goto('/#/control-room')
    await expect(page.getByRole('heading', { name: 'Control-room readiness' })).toBeVisible()
    await expect(page.getByText('v1.0.0-rc11')).toBeVisible()
    await expect(page.getByText('Equipment check pending', { exact: true })).toBeVisible()
    // Three Technical detail toggles on this route: the panel-level
    // proof-boundary one (first), then one per check in [blocking, warnings]
    // order — nth(1) = the blocked tsr-control-service check.
    await expect(page.getByText('Technical detail').first()).toBeVisible()
    await page.getByText('Technical detail').first().click()
    await expect(page.getByText(/not clean Windows install evidence/)).toBeVisible()
    await page.getByText('Technical detail').nth(1).click()
    await expect(page.getByText('Evidence: control_room.tsr_client')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Open Control Room Setup' })).toBeVisible()
    await expect(page.getByText(/Open Control Room Setup to start or reconnect/)).toBeVisible()
    await captureUiEvidence(page, testInfo, 'operator-readiness-blocked')
    await expectNoWcagAxeViolations(page, 'control-room readiness')
  })

  test('setup route shows proof-boundary detail and passes axe', async ({ page }, testInfo) => {
    await mockControlRoom(page, ['setup_admin'])
    await page.goto('/#/control-room-setup')
    await expect(page.getByRole('heading', { name: 'Control-room readiness' })).toBeVisible()
    // proof-boundary text now lives behind the panel's Technical detail toggle
    await page.getByText('Technical detail').first().click()
    await expect(page.getByText(/not clean Windows install evidence/)).toBeVisible()
    await expect(page.getByText('Equipment check pending', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByText('Unreachable')).toBeVisible()
    await expect(page.getByText(/intentionally absent/)).toBeVisible()
    await captureUiEvidence(page, testInfo, 'setup-readiness-probe')
    await expectNoWcagAxeViolations(page, 'control-room setup readiness')
  })

  test('operator route exposes safe-state and support-bundle controls and passes axe', async ({ page }, testInfo) => {
    await mockControlRoom(page, ['meeting_operator', 'support_admin'], readyReadiness)
    await page.goto('/#/control-room')
    await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    await page.getByLabel('Control surface').selectOption('srf')
    await page.getByLabel('On-Air Mode').check()
    await page.getByLabel('Safe-state cue').selectOption('cue_1')
    await page.getByLabel(/I understand On-Air cue actions/).check()
    await page.getByRole('button', { name: 'Open On-Air Session' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'ON-AIR MODE - cue actions can be sent' })).toBeVisible()
    await expect(page.getByText('Safe State', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Panic: Run Safe State' })).toBeDisabled()
    await page.getByRole('button', { name: 'Dry Run Safe State' }).click()
    await expect(page.getByText('Studio OBS: set scene -> CAM2').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Panic: Run Safe State' })).toBeEnabled()
    await page.getByRole('button', { name: 'Create support bundle' }).click()
    await expect(page.getByText('Support bundle ready')).toBeVisible()
    await captureUiEvidence(page, testInfo, 'operator-on-air-safe-state-support-bundle')
    await expectNoWcagAxeViolations(page, 'control-room operator controls')
  })

  test('offers rollback to safe state after a failed on-air cue fire, and it fires', async ({ page }, testInfo) => {
    await mockControlRoom(page, ['meeting_operator'], readyReadiness)
    // cue_1 ("Take CAM2") is the safe-state cue for this session; fail closed
    // firing cue_2 ("Take CAM1") instead, like a real TSR transport error, so
    // the rollback affordance is genuinely exercised against a DIFFERENT cue
    // than the one it rolls back to.
    await page.route('**/api/staff/control-room/sessions/s1/cues/cue_2/fire', async (route) => {
      await route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Production control service error (TsrClientError).' }),
      })
    })
    await page.goto('/#/control-room')
    await page.getByLabel('Control surface').selectOption('srf')
    await page.getByLabel('On-Air Mode').check()
    await page.getByLabel('Safe-state cue').selectOption('cue_1')
    await page.getByLabel(/I understand On-Air cue actions/).check()
    await page.getByRole('button', { name: 'Open On-Air Session' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'ON-AIR MODE - cue actions can be sent' })).toBeVisible()

    await page.getByRole('button', { name: 'Take CAM1' }).click()
    await expect(page.getByText('Studio OBS: set scene -> CAM1')).toBeVisible()
    await page.getByRole('button', { name: /Fire\.\.\. \(needs confirm\)/ }).click()
    await page.getByRole('button', { name: 'Confirm fire' }).click()
    await expect(page.getByRole('button', { name: 'Roll back to Safe State' })).toBeVisible()

    await page.getByRole('button', { name: 'Roll back to Safe State' }).click()
    await expect(page.getByText('Rolled back to Safe State.')).toBeVisible()
    await captureUiEvidence(page, testInfo, 'operator-rollback-after-failed-fire')
    await expectNoWcagAxeViolations(page, 'control-room rollback after failed fire')
  })
})
