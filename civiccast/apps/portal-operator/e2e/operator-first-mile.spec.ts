import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const NOT_STARTED = {
  status: 'not_started',
  setup_complete: false,
  profile: null,
  recovery_kit_created: false,
  recovery_kit_id: null,
  operator_console_url: 'http://127.0.0.1:5173',
  next_step: 'Create the first admin account and save the recovery kit.',
}

const STORAGE_READY = {
  status: 'ready',
  database_url: 'sqlite:///C:/CivicCast/data/civiccast.sqlite3',
  database_path: 'C:/CivicCast/data/civiccast.sqlite3',
  upload_dir: 'C:/CivicCast/uploads',
  storage_dir: 'C:/CivicCast',
  migrations_applied: true,
  configured_at: '2026-05-22T18:00:00Z',
  operator_message: 'CivicCast local durable storage is ready.',
  next_step: 'Open the operator console and continue setup.',
}

const SETUP_RESPONSE = {
  status: 'complete',
  profile: {
    station_name: 'Pinegrove School Board',
    admin_display_name: 'Avery Admin',
    admin_username: 'avery',
    default_channel_id: 'government',
    public_base_url: 'https://meetings.example.gov',
    recovery_kit_id: 'rk_test',
    recovery_kit_generated_at: '2026-05-22T18:00:00Z',
  },
  recovery_kit: {
    kit_id: 'rk_test',
    generated_at: '2026-05-22T18:00:00Z',
    station_name: 'Pinegrove School Board',
    admin_username: 'avery',
    recovery_codes: ['CC-111111111111', 'CC-222222222222'],
    instructions: ['Print or save this kit before the first public meeting.'],
    excludes: ['staff bearer token values', 'provider secret values'],
  },
  operator_console_url: 'http://127.0.0.1:5173',
  operator_console_token: 'ccst_mock_operator_console_token',
  next_step: 'Open System Health, confirm readiness, then run a private rehearsal.',
}

const HEALTH_REPORT = {
  generated_at: '2026-05-22T18:05:00Z',
  safe_to_broadcast: 'yellow',
  label: 'Ready with optional items',
  operator_message: 'Required checks passed. Review optional items before the meeting if policy requires them.',
  setup: {
    status: 'complete',
    setup_complete: true,
    profile: SETUP_RESPONSE.profile,
    recovery_kit_created: true,
    recovery_kit_id: 'rk_test',
    operator_console_url: 'http://127.0.0.1:5173',
    next_step: 'Open System Health.',
  },
  resident_preview: {
    status: 'available',
    public_url: 'https://meetings.example.gov',
    message: 'Resident preview is pointed at the configured public portal.',
    next_step: 'Open the preview before the meeting.',
  },
  checks: [
    {
      id: 'first-admin',
      label: 'First admin',
      kind: 'required',
      required: true,
      state: 'ready',
      color: 'green',
      message: 'Avery Admin can manage this station.',
      next_step: 'Keep the recovery kit somewhere separate from this computer.',
    },
    {
      id: 'backup-status',
      label: 'Backup',
      kind: 'required',
      required: true,
      state: 'ready',
      color: 'green',
      message: 'Backup destination accepted a write/read/delete proof.',
      next_step: 'Keep this backup drive available before public meetings.',
    },
    {
      id: 'source-preflight',
      label: 'Camera or meeting source',
      kind: 'required',
      required: true,
      state: 'ready',
      color: 'green',
      message: '1 camera or meeting source is configured.',
      next_step: 'Run Run Meeting pre-flight before going live.',
    },
    {
      id: 'youtube',
      label: 'YouTube',
      kind: 'optional',
      required: false,
      state: 'needs_attention',
      color: 'yellow',
      message: 'YouTube is not set up yet.',
      next_step: 'Set it up later if station policy requires it.',
    },
  ],
}

const BACKUP_STATUS = {
  generated_at: '2026-05-22T18:05:00Z',
  status: 'ready',
  destination: 'C:/CivicCastBackups',
  last_probe_at: '2026-05-22T18:05:00Z',
  last_backup_at: null,
  message: 'Backup destination accepted a write/read/delete proof.',
  next_step: 'Keep this backup drive available before public meetings.',
}

const PROVIDER_READINESS = {
  generated_at: '2026-05-22T18:05:00Z',
  next_step: 'Set up only the providers the station needs.',
  items: [
    {
      id: 'local-portal',
      label: 'Local resident portal',
      required: true,
      status: 'ready',
      message: 'The local resident portal is available for tester broadcasts.',
      next_step: 'Use Resident preview to confirm what viewers can see.',
      what_you_need: [],
      setup_steps: ['Open System Health.', 'Choose Open resident preview.'],
      setup_url: null,
      proof_requirement: 'Resident preview must open from the public URL.',
      credential_fields: [],
      credential_handle: null,
    },
    {
      id: 'youtube',
      label: 'YouTube',
      required: false,
      status: 'not_set_up',
      message: 'YouTube is optional and not set up yet.',
      next_step: 'Connect YouTube only if the station wants an optional YouTube copy.',
      what_you_need: ['Station YouTube channel', 'Google OAuth client ID and secret'],
      setup_steps: ['Confirm channel access.', 'Create an OAuth client.', 'Run a private proof.'],
      setup_url: 'https://console.cloud.google.com/apis/credentials',
      proof_requirement: 'A private YouTube proof is required before public claims.',
      credential_fields: [
        {
          id: 'client_id',
          label: 'Client ID',
          help_text: 'Paste the Google OAuth client ID for the station channel.',
          secret: false,
          required: true,
        },
        {
          id: 'client_secret',
          label: 'Client secret',
          help_text: 'Paste the Google OAuth client secret. CivicCast stores it locally and never prints it back.',
          secret: true,
          required: true,
        },
      ],
      credential_handle: null,
    },
  ],
}

const SOURCE_SETUP = {
  generated_at: '2026-05-22T18:05:00Z',
  status: 'not_set_up',
  configured_source_count: 0,
  options: [
    {
      id: 'usb-hdmi',
      label: 'USB/HDMI capture',
      best_for: 'A webcam or HDMI capture device using a private RTMP feed.',
      source_type: 'rtmp',
      operator_steps: ['Open the capture app.', 'Paste the private stream address.'],
      needs_it_help: false,
    },
    {
      id: 'sample-upload',
      label: 'Bundled sample video',
      best_for: 'A no-camera private rehearsal.',
      source_type: null,
      operator_steps: ['Create the sample.', 'Check broadcast readiness.'],
      needs_it_help: false,
    },
  ],
  next_step: 'Choose a camera or test media in Setup.',
}

const SAMPLE_UPLOAD = {
  status: 'ready',
  asset_id: 'sample-rehearsal-test',
  title: 'CivicCast sample rehearsal',
  file_path: 'C:/CivicCast/uploads/sample-rehearsal-test/civiccast-sample-rehearsal.mp4',
  message: 'CivicCast created a short sample video for rehearsal.',
  next_step: 'Open System Health and select Check broadcast readiness, then confirm the resident preview.',
}

const CABLE_CHANNELS = [
  {
    channel_id: 'public',
    kind: 'public_access',
    branding: {
      display_name: 'Public Access',
      short_name: 'Public',
      color: '#2457a6',
      logo_text: 'PA',
      logo_url: null,
    },
    schedule_source: 'civiccast-schedule',
    outputs: [
      {
        id: 'headend',
        label: 'Headend',
        kind: 'srt',
        uri: 'srt://127.0.0.1:17001',
        enabled: true,
      },
    ],
    fallback_behavior: 'CivicCast shows the configured slate when no meeting is on air.',
  },
]

const EGRESS_HEALTH_SAMPLE = {
  channel_id: 'public',
  sampled_at: '2026-05-22T18:09:00Z',
  state: 'ON_AIR',
  sink_connected: { Headend: true },
  encoder_fps: 29.97,
  encoder_bitrate_kbps: 3200,
  dropped_frames: 0,
  seconds_on_air: 42,
  last_loudness_lufs: -16.1,
  caption_status: 'not-verified',
}

const RESTORE_STATUS = {
  generated_at: '2026-05-22T18:05:00Z',
  status: 'not_tested',
  target_profile: 'isolated-station-profile',
  last_restore_test_at: null,
  proof_summary: null,
  plan_steps: [
    'Use an isolated station profile; never restore over the active meeting station.',
    'Restore database state, media artifacts, configuration, and operator-state metadata into the isolated profile.',
  ],
  message: 'Backup storage is available, but restore has not been rehearsed yet.',
  next_step: 'Run a private restore rehearsal before relying on this station for records.',
}

const RESTORE_PASSED = {
  generated_at: '2026-05-22T18:08:00Z',
  status: 'needs_attention',
  target_profile: 'isolated-station-profile',
  last_restore_test_at: null,
  proof_summary: 'Backup storage passed a manifest checksum round trip. This did not restore station data.',
  plan_steps: [
    'Use an isolated station profile; never restore over the active meeting station.',
    'Restore database state, media artifacts, configuration, and operator-state metadata into the isolated profile.',
  ],
  message: 'Backup storage passed its round-trip check; an actual full station restore has not been run.',
  next_step: 'Run the real database drill and prove media/config restore on an isolated machine.',
}

const UPDATE_STATUS = {
  generated_at: '2026-05-22T18:05:00Z',
  current_version: '1.5.0',
  available_version: '1.5.1',
  status: 'update_available',
  migration_state: 'Backup destination is ready; full restore proof has not run.',
  rollback_available: false,
  rollback_artifact: null,
  rollback_artifact_sha256: null,
  rollback_proof_state: 'not_configured',
  last_rollback_test_at: null,
  rollback_proof_summary: null,
  post_update_proof_state: 'not_run',
  last_post_update_proof_at: null,
  post_update_proof_summary: null,
  maintenance_window_state: 'closed',
  maintenance_window_expires_at: null,
  maintenance_window_summary: null,
  failed_update_rollback_state: 'not_run',
  last_failed_update_rollback_at: null,
  failed_update_rollback_summary: null,
  safe_to_apply: false,
  last_preflight_at: null,
  checkpoint_summary: null,
  plan_steps: [
    'Confirm no meeting is in progress and backup status is ready.',
    'Choose or build a rollback artifact before applying an update to a beta station.',
    'Run Safe to broadcast and a private rehearsal after the update.',
  ],
  message: 'CivicCast 1.5.1 is available for tester review.',
  next_step: 'Run update preflight before applying this update.',
}

const UPDATE_PREFLIGHT_PASSED = {
  ...UPDATE_STATUS,
  generated_at: '2026-05-22T18:09:00Z',
  safe_to_apply: false,
  last_preflight_at: '2026-05-22T18:09:00Z',
  checkpoint_summary: 'CivicCast wrote and verified update checkpoint update-checkpoint-test for 1.5.0 -> 1.5.1.',
  migration_state: 'Update preflight passed; maintenance window is closed.',
  next_step: 'Open the maintenance window before applying this update.',
}

const ROLLBACK_CONFIGURED = {
  ...UPDATE_PREFLIGHT_PASSED,
  rollback_available: true,
  rollback_artifact: 'C:\\CivicCast\\releases\\CivicCast_1.4.0_x64-setup.exe',
  rollback_artifact_sha256: 'b'.repeat(64),
  rollback_proof_state: 'not_tested',
}

const ROLLBACK_PASSED = {
  ...ROLLBACK_CONFIGURED,
  rollback_proof_state: 'passed',
  last_rollback_test_at: '2026-05-22T18:11:00Z',
  rollback_proof_summary: 'CivicCast verified rollback artifact CivicCast_1.4.0_x64-setup.exe with SHA-256 in an isolated rehearsal copy.',
}

const MAINTENANCE_OPEN = {
  ...ROLLBACK_PASSED,
  safe_to_apply: true,
  maintenance_window_state: 'open',
  maintenance_window_expires_at: '2026-05-22T19:11:00Z',
  maintenance_window_summary: 'Maintenance window opened for 1.5.0 -> 1.5.1 until 2026-05-22T19:11:00Z.',
  migration_state: 'Update preflight and maintenance window are active.',
  next_step: 'Close the operator console, apply the update package, then run post-update proof.',
}

const FAILED_UPDATE_PASSED = {
  ...MAINTENANCE_OPEN,
  failed_update_rollback_state: 'passed',
  last_failed_update_rollback_at: '2026-05-22T18:12:00Z',
  failed_update_rollback_summary: 'CivicCast simulated failed update failed-update-rollback-test, verified rollback artifact CivicCast_1.4.0_x64-setup.exe, and removed temporary proof files.',
}

const POST_UPDATE_PASSED = {
  ...FAILED_UPDATE_PASSED,
  post_update_proof_state: 'passed',
  last_post_update_proof_at: '2026-05-22T18:13:00Z',
  post_update_proof_summary: 'Post-update Safe to broadcast proof passed with label: Ready with optional items.',
}

const SUPPORT_BUNDLE = {
  bundle_id: 'support-test',
  generated_at: '2026-05-22T18:05:00Z',
  path: 'C:/CivicCast/support/support-test.json',
  sha256: 'a'.repeat(64),
  redacted: true,
  contains: ['CivicCast version', 'safe-to-broadcast health'],
  excludes: ['bearer tokens', 'private keys'],
  next_step: 'Attach this bundle to the tester bug report if support asks for it.',
}

async function mockSetup(page: import('@playwright/test').Page) {
  await page.route('**/api/setup/station-state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(NOT_STARTED),
    })
  })
  await page.route('**/api/setup/storage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(STORAGE_READY),
    })
  })
  await page.route('**/api/setup/first-admin', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SETUP_RESPONSE),
    })
  })
  await page.route('**/api/setup/recovery-kit/acknowledge', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'complete',
        setup_complete: true,
        profile: SETUP_RESPONSE.profile,
        recovery_kit_created: true,
        recovery_kit_id: 'rk_test',
        recovery_kit_acknowledged: true,
        operator_console_url: 'http://127.0.0.1:5173',
        next_step: 'Open System Health and confirm the station is ready for a private rehearsal.',
      }),
    })
  })
  await page.route('**/api/staff/installer/backup', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(BACKUP_STATUS),
    })
  })
  await page.route('**/api/staff/installer/provider-readiness', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(PROVIDER_READINESS),
    })
  })
  await page.route('**/api/staff/installer/provider-credentials', async (route) => {
    const body = await route.request().postDataJSON()
    expect(JSON.stringify(body)).toContain('youtube-client-secret')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'stored',
        provider_id: 'youtube',
        credential_handle: 'civiccast-provider://youtube',
        configured_fields: ['client_id', 'client_secret'],
        redacted_fields: ['client_secret'],
        message: 'Provider details were saved locally. Secret values will not be shown again.',
        next_step: 'Run provider readiness again, then run live proof before claiming this provider is ready.',
      }),
    })
  })
  await page.route('**/api/staff/installer/source-setup', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SOURCE_SETUP),
    })
  })
  await page.route('**/api/staff/installer/source-setup/sample-upload', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SAMPLE_UPLOAD),
    })
  })
}

async function mockHealth(
  page: import('@playwright/test').Page,
  options: { roles?: string[] } = {},
) {
  let egressState = {
    channel_id: 'public',
    state: 'ON_AIR',
    current_source_label: 'Public meeting live',
    current_proof_event_id: 'proof-live-public',
    updated_at: '2026-05-22T18:09:00Z',
    pid: 4321,
    last_error: null,
  }
  const requests = { egressCommands: [] as string[] }
  const roles = options.roles ?? [
    'setup_admin',
    'meeting_operator',
    'records_clerk',
    'publish_operator',
    'support_admin',
  ]
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'test-operator',
        operator_display_name: 'Test Operator',
        token_id: 'env-test',
        scopes: roles,
        roles,
      }),
    })
  })
  await page.route('**/api/setup/station-state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(HEALTH_REPORT.setup),
    })
  })
  await page.route('**/api/setup/storage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(STORAGE_READY),
    })
  })
  await page.route('**/api/staff/installer/system-health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(HEALTH_REPORT),
    })
  })
  await page.route('**/api/staff/installer/rehearsal', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        rehearsal_id: 'rehearsal-test',
        started_at: '2026-05-22T18:10:00Z',
        status: 'needs_attention',
        safe_to_broadcast: 'yellow',
        message: 'Private rehearsal passed required checks with optional items still needing attention.',
        resident_preview: HEALTH_REPORT.resident_preview,
        checks: HEALTH_REPORT.checks,
        private_session_id: 'rehearsal-test',
        recording_asset_id: 'rehearsal-test',
        recording_uri: 'file:///C:/CivicCast/uploads/private-rehearsals/rehearsal-test/private-rehearsal-recording.mp4',
        resident_preview_proof: 'Resident preview loaded (text/html; charset=utf-8).',
        evidence: [
          'Created and validated a short private rehearsal recording.',
          'Live preflight passed.',
          'Finalized private recording as asset rehearsal-test.',
        ],
        next_step: 'Review the yellow items, then run rehearsal again if station policy requires them.',
      }),
    })
  })
  await page.route('**/api/staff/installer/restore', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(RESTORE_STATUS),
    })
  })
  await page.route('**/api/staff/installer/restore/rehearsal', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(RESTORE_PASSED),
    })
  })
  await page.route('**/api/staff/installer/update-rollback/preflight', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(UPDATE_PREFLIGHT_PASSED),
    })
  })
  await page.route('**/api/staff/installer/update-rollback/maintenance-window', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MAINTENANCE_OPEN),
    })
  })
  await page.route('**/api/staff/installer/update-rollback/rollback-artifact', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(ROLLBACK_CONFIGURED),
    })
  })
  await page.route('**/api/staff/installer/update-rollback/rollback-rehearsal', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(ROLLBACK_PASSED),
    })
  })
  await page.route('**/api/staff/installer/update-rollback/failed-update-rehearsal', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(FAILED_UPDATE_PASSED),
    })
  })
  await page.route('**/api/staff/installer/update-rollback/post-update-proof', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(POST_UPDATE_PASSED),
    })
  })
  await page.route('**/api/staff/cable/channels', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(CABLE_CHANNELS),
    })
  })
  await page.route('**/api/staff/egress/channels/public/state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(egressState),
    })
  })
  await page.route('**/api/staff/egress/channels/public/health?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([EGRESS_HEALTH_SAMPLE]),
    })
  })
  await page.route('**/api/staff/egress/channels/public/commands', async (route) => {
    const payload = await route.request().postDataJSON() as { action: string }
    requests.egressCommands.push(payload.action)
    egressState = {
      ...egressState,
      state: payload.action === 'stop' ? 'STOPPED' : egressState.state,
      current_source_label: payload.action === 'stop' ? null : egressState.current_source_label,
      updated_at: '2026-05-22T18:10:00Z',
    }
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        queued: true,
        command: {
          channel_id: 'public',
          action: payload.action,
          issued_at: '2026-05-22T18:10:00Z',
          issued_by: 'operator-console',
          command_id: `egress-${payload.action}`,
        },
      }),
    })
  })
  await page.route('**/api/staff/installer/update-rollback', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(UPDATE_STATUS),
    })
  })
  await page.route('**/api/staff/installer/support-bundle', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SUPPORT_BUNDLE),
    })
  })
  return requests
}

test.describe('operator first mile', () => {
  test('creates first admin, stores browser token, and shows recovery kit', async ({ page }) => {
    await mockSetup(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()

    await page.getByLabel('Station name').fill('Pinegrove School Board')
    await page.getByLabel('Admin display name').fill('Avery Admin')
    await page.getByLabel('Admin username').fill('avery')
    await page.locator('#admin_password').fill('correct horse battery staple')
    await page.locator('#confirm_password').fill('correct horse battery staple')
    await page
      .getByLabel('Where will you keep the recovery kit?')
      .fill('printed and stored in the clerk safe')
    await page.getByLabel('Resident portal URL').fill('https://meetings.example.gov')
    await page.getByRole('button', { name: 'Create first admin' }).click()

    await expect(page.getByText('Recovery kit ready')).toBeVisible()
    await expect(page.getByText('CC-111111111111')).toBeVisible()
    // Field fix (candidate #17): the kit must show the routine admin
    // password, not just the emergency recovery codes.
    await expect(page.getByText('correct horse battery staple')).toBeVisible()

    // Lockout gate: nothing past the kit until save/print is confirmed.
    await expect(page.getByRole('heading', { name: 'Camera or test media' })).toHaveCount(0)
    const confirmBox = page.getByRole('checkbox', {
      name: /I have saved or printed this kit/,
    })
    await expect(confirmBox).toBeDisabled()
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Save kit' }).click()
    const kitDownload = await downloadPromise
    expect(kitDownload.suggestedFilename()).toBe('civiccast-recovery-kit-rk_test.txt')
    await confirmBox.check()
    await page.getByRole('button', { name: 'Continue to the console' }).click()

    await expect(page.getByRole('heading', { name: 'Camera or test media' })).toBeVisible()
    await page.getByRole('button', { name: 'Create sample media' }).click()
    await expect(page.getByText('Ready: sample-rehearsal-test')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Backup destination' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Provider setup' })).toBeVisible()
    await page.getByLabel('Client ID').fill('youtube-client-id')
    await page.getByLabel('Client secret').fill('youtube-client-secret')
    await page.getByRole('button', { name: 'Save details' }).click()
    await expect(page.getByText('Details saved. Run live proof before marking this provider ready.')).toBeVisible()
    await expect(page.getByText('youtube-client-secret')).toHaveCount(0)
    await expect(
      page.evaluate(() => window.localStorage.getItem('civiccast.staffToken')),
    ).resolves.toBe('ccst_mock_operator_console_token')
  })

  test('system health shows safe-to-broadcast and runs private rehearsal', async ({ page }) => {
    const requests = await mockHealth(page)
    await page.goto('/')
    await page.getByLabel('Show System Health navigation').click()
    await page.getByRole('button', { name: 'Readiness' }).click()

    await expect(page.getByRole('heading', { name: 'Safe to broadcast' })).toBeVisible()
    await expect(page.getByText('Ready with optional items')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Camera or meeting source' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Backup and restore readiness' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Update and rollback' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Outgoing channel feed' })).toBeVisible()
    await expect(page.getByText('Public meeting live')).toBeVisible()
    await expect(page.getByText('Headend: connected')).toBeVisible()
    await expect(page.getByText('Not yet confirmed (waiting for the on-air check)')).toBeVisible()
    await page.getByRole('button', { name: 'Restart feed' }).click()
    await expect.poll(() => requests.egressCommands).toEqual(['reload'])
    await page.getByRole('button', { name: 'Finish current item, then stop' }).click()
    await expect.poll(() => requests.egressCommands).toEqual(['reload', 'drain'])
    await expect(page.getByText('Use an isolated station profile')).toBeVisible()
    await expect(page.getByText('Choose or build a rollback artifact')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Run update preflight' })).toBeVisible()
    await expect(page.getByText('Backup destination is ready; full restore proof has not run.')).toBeVisible()
    await page.getByRole('button', { name: 'Run update preflight' }).click()
    await expect(page.getByText('Update preflight passed; maintenance window is closed.')).toBeVisible()
    await expect(page.getByText('update-checkpoint-test')).toBeVisible()
    await page.getByLabel('Rollback artifact path').fill('C:\\CivicCast\\releases\\CivicCast_1.4.0_x64-setup.exe')
    await page.getByRole('button', { name: 'Save rollback artifact' }).click()
    await expect(page.getByText('Rollback SHA-256')).toBeVisible()
    await page.getByRole('button', { name: 'Run rollback rehearsal' }).click()
    await expect(page.getByText('Rollback proof summary')).toBeVisible()
    await expect(page.getByText('CivicCast verified rollback artifact', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Open maintenance window' }).click()
    await expect(page.getByText('Maintenance summary')).toBeVisible()
    await expect(page.getByText('Maintenance window opened for 1.5.0 -> 1.5.1', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Run failed-update rehearsal' }).click()
    await expect(page.getByText('Failed-update proof summary')).toBeVisible()
    await expect(page.getByText('CivicCast simulated failed update', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Run post-update proof' }).click()
    await expect(page.getByText('Post-update proof summary')).toBeVisible()
    await expect(page.getByText('Post-update Safe to broadcast proof passed', { exact: false })).toBeVisible()
    await page.getByRole('button', { name: 'Check backup storage' }).click()
    await expect(page.getByText('Backup storage passed its round-trip check')).toBeVisible()
    await page.getByRole('button', { name: 'Check broadcast readiness' }).click()
    await expect(page.getByText('Broadcast readiness check result')).toBeVisible()
    await expect(page.getByText('Private session')).toBeVisible()
    await expect(page.getByText('Recording proof')).toBeVisible()
    await expect(page.getByText('Finalized private recording as asset rehearsal-test.')).toBeVisible()
    await page.getByRole('button', { name: 'Create support bundle' }).click()
    await expect(page.getByText('Support bundle ready')).toBeVisible()

    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
    const blockers = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    )
    expect(blockers).toEqual([])
  })

  test('route survives refresh on system health', async ({ page }) => {
    await mockHealth(page)
    await page.goto('/#/health')
    await expect(page.getByRole('heading', { name: 'Safe to broadcast' })).toBeVisible()

    await page.reload()

    await expect(page).toHaveURL(/#\/health/)
    await expect(page.getByRole('heading', { name: 'Safe to broadcast' })).toBeVisible()
  })

  test('system health keeps mutations read-only for records clerk', async ({ page }) => {
    await mockHealth(page, { roles: ['records_clerk'] })
    await page.goto('/#/health')

    await expect(page.getByText(/Checking broadcast readiness requires the meeting operator role/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Check broadcast readiness' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Check backup storage' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Run update preflight' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Open maintenance window' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Save rollback artifact' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Run rollback rehearsal' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Run failed-update rehearsal' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Run post-update proof' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Create support bundle' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Restart feed' })).toBeDisabled()
    await expect(page.getByText('Outgoing feed controls require the meeting operator role.')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Update and rollback' })).toBeVisible()
  })
})
