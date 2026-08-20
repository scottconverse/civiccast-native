import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']

const sourceA = {
  live_source_id: 'rtmp-cam-01',
  channel_id: 'government',
  name: 'Council Chamber Encoder',
  source_type: 'rtmp',
  endpoint_url: 'rtmp://encoder.local/live/council',
  credentials_handle: null,
  created_at: '2026-05-12T18:00:00Z',
}

const sourceB = {
  live_source_id: 'ndi-floor-01',
  channel_id: 'government',
  name: 'Floor Camera NDI',
  source_type: 'ndi',
  endpoint_url: 'ndi://floor-camera',
  credentials_handle: null,
  created_at: '2026-05-12T18:00:00Z',
}

const relayConfig = {
  relay_config_id: 'project-relay',
  channel_id: 'government',
  name: 'Project Hosted Relay',
  mode: 'cloud_rtmp_relay',
  endpoint_url: 'rtmps://relay.example/live/gov',
  return_playback_url: 'https://cdn.example/live/gov.m3u8',
  provider: 'project-hosted',
  credentials_handle: null,
  enabled: true,
  health_state: 'ready',
  last_heartbeat_at: '2026-05-31T18:00:00Z',
  notes: null,
  created_at: '2026-05-31T17:00:00Z',
}

function ingestPlan(relays = [relayConfig]) {
  const relayPaths = relays.map((relay) => ({
    path_id: relay.relay_config_id,
    label: relay.name,
    mode: relay.mode,
    endpoint_url: relay.endpoint_url,
    return_playback_url: relay.return_playback_url,
    provider: relay.provider,
    enabled: relay.enabled,
    health_state: relay.health_state,
    outbound_only: relay.mode !== 'local_rtmp',
    requires_inbound_firewall: false,
    operator_action: 'Send the room encoder to this relay endpoint.',
    risk_note: null,
  }))
  return {
    channel_id: 'government',
    generated_at: '2026-05-31T18:00:00Z',
    local_default: {
      path_id: 'government:local',
      label: 'Local encoder',
      mode: 'local_rtmp',
      endpoint_url: 'rtmp://127.0.0.1/live/government',
      return_playback_url: null,
      provider: 'self-hosted',
      enabled: true,
      health_state: 'ready',
      outbound_only: false,
      requires_inbound_firewall: false,
      operator_action: 'Point the room encoder at the local CivicCast ingest endpoint.',
      risk_note: null,
    },
    relay_paths: relayPaths,
    recommended_path_id:
      relayPaths.find((path) => path.health_state === 'ready')?.path_id ?? 'government:local',
    degraded_count: relayPaths.filter((path) => path.health_state !== 'ready').length,
    direct_syndication_available: relayPaths.some((path) => path.mode === 'direct_syndication'),
  }
}

const SOURCE_SETUP = {
  generated_at: '2026-05-22T18:00:00Z',
  status: 'not_set_up',
  configured_source_count: 0,
  next_step: 'Choose the option that matches the equipment in the room, then run preflight.',
  options: [
    {
      id: 'usb-hdmi',
      label: 'Camera plugged into this computer',
      best_for: 'USB webcams or camcorders connected through an HDMI capture adapter.',
      source_type: 'upload',
      operator_steps: [
        'Plug the camera or capture adapter into this computer.',
        'Choose Camera in Run Meeting.',
        'Confirm the preview shows video and audio before the meeting.',
      ],
      needs_it_help: false,
    },
    {
      id: 'sample-upload',
      label: 'Sample recording or uploaded test file',
      best_for: 'A no-camera rehearsal before the first real meeting.',
      source_type: 'upload',
      operator_steps: [
        'Choose Upload test media in Run Meeting.',
        'Use the bundled sample or a short local video.',
        'Run rehearsal and review the resident preview.',
      ],
      needs_it_help: false,
    },
  ],
}

const SETUP_READY = {
  status: 'complete',
  setup_complete: true,
  profile: null,
  recovery_kit_created: true,
  recovery_kit_id: 'rk_test',
  operator_console_url: 'http://127.0.0.1:5173',
  next_step: 'Open Live and run the meeting pre-flight.',
}

const STORAGE_READY = {
  status: 'ready',
  database_url: 'sqlite:///C:/CivicCast/data/civiccast.sqlite3',
  database_path: 'C:/CivicCast/data/civiccast.sqlite3',
  upload_dir: 'C:/CivicCast/uploads',
  storage_dir: 'C:/CivicCast',
  migrations_applied: true,
  configured_at: '2026-05-31T18:00:00Z',
  operator_message: 'CivicCast local durable storage is ready.',
  next_step: 'Open Live and run the meeting pre-flight.',
}

const HEALTH_REPORT = {
  generated_at: '2026-05-31T18:05:00Z',
  safe_to_broadcast: 'green',
  label: 'Ready',
  operator_message: 'Required checks passed. The station can start a broadcast.',
  setup: SETUP_READY,
  resident_preview: {
    status: 'available',
    public_url: 'https://meetings.example.gov',
    message: 'Resident preview is available.',
    next_step: 'Open the preview before the meeting.',
  },
  checks: [],
}

const BACKUP_STATUS = {
  generated_at: '2026-05-31T18:05:00Z',
  status: 'ready',
  destination: 'C:/CivicCast/backups',
  last_probe_at: '2026-05-31T18:05:00Z',
  last_backup_at: null,
  message: 'Backup destination is reachable.',
  next_step: 'Run a backup after the meeting.',
}

const PROVIDER_READINESS = {
  generated_at: '2026-05-31T18:05:00Z',
  items: [],
  next_step: 'No external provider action is required for this test.',
}

interface MockLiveOptions {
  sources?: typeof sourceA[]
  relays?: typeof relayConfig[]
  failConfiguration?: boolean
  preflightReady?: boolean
  roles?: string[]
}

function session(state: string) {
  return {
    live_session_id: 'council-live-room',
    channel_id: 'government',
    title: 'Council live room',
    state,
    started_at: state === 'on_air' ? '2026-05-12T18:15:00Z' : null,
    ended_at: state === 'ending' ? '2026-05-12T19:15:00Z' : null,
    notes: 'Created from the operator live room.',
    created_at: '2026-05-12T18:00:00Z',
  }
}

async function mockLiveBackend(
  page: import('@playwright/test').Page,
  options: MockLiveOptions = {},
) {
  const {
    sources = [sourceA, sourceB],
    relays = [relayConfig],
    failConfiguration = false,
    preflightReady = true,
    roles = ['meeting_operator'],
  } = options
  await page.route('**/api/setup/station-state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SETUP_READY),
    })
  })
  await page.route('**/api/setup/storage', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(STORAGE_READY),
    })
  })
  await page.route('**/api/staff/installer/safe-to-broadcast', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(HEALTH_REPORT),
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
  await page.route('**/api/staff/assets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    })
  })
  await page.route('**/api/staff/live/sources', async (route) => {
    if (failConfiguration) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '{',
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(sources),
    })
  })
  await page.route('**/api/staff/live/relay-configs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(relays),
    })
  })
  await page.route('**/api/staff/cable/channels', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { channel_id: 'government', slug: 'government', kind: 'government' },
        { channel_id: 'education', slug: 'education', kind: 'education' },
      ]),
    })
  })
  await page.route('**/api/staff/live/ingest-plan**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(ingestPlan(relays)),
    })
  })
  await page.route('**/api/staff/installer/source-setup', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SOURCE_SETUP),
    })
  })
  await page.route('**/api/staff/live/recording-targets', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          recording_target_id: 'local-recordings',
          name: 'Local recordings',
          target_uri: 'file:///var/lib/civiccast/recordings',
          created_at: '2026-05-12T18:00:00Z',
        },
      ]),
    })
  })
  await page.route('**/api/staff/live/sessions', async (route) => {
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify(session('idle')),
    })
  })
  await page.route('**/api/staff/live/sessions/*/start-preflight', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session('preflight')),
    })
  })
  await page.route('**/api/staff/live/sessions/*/preflight', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        live_session_id: 'council-live-room',
        ready: preflightReady,
        checks: [
          {
            name: 'network',
            status: preflightReady ? 'pass' : 'fail',
            reason_code: preflightReady ? undefined : 'network.unreachable',
            message: preflightReady
              ? 'Network reachable.'
              : 'Encoder network is unreachable.',
          },
          { name: 'storage', status: 'pass', message: '128.0 GiB free.' },
          {
            name: 'ai_runtime',
            status: 'not_configured',
            reason_code: 'ai_runtime.not_configured',
            message: 'AI runtime not configured; optional for Slice 1.',
          },
          {
            name: 'live_source',
            status: 'pass',
            message: "Source 'rtmp-cam-01' (rtmp) configured.",
          },
          {
            name: 'recording_target',
            status: 'pass',
            message: "Recording target 'local-recordings'.",
          },
          {
            name: 'operator_confirm',
            status: preflightReady ? 'pass' : 'fail',
            reason_code: preflightReady ? undefined : 'operator.unconfirmed',
            message: preflightReady
              ? undefined
              : 'Operator has not confirmed preview and audio.',
          },
          // Publish-surface postures as the backend actually reports them on a
          // default install: the shipped simulation, said plainly (PE-2).
          {
            name: 'syndication',
            status: 'not_configured',
            reason_code: 'publish_surface.simulated',
            message:
              'Syndication (YouTube) is running in simulation - this meeting will NOT be published there and nothing will be written.',
          },
          {
            name: 'internet_archive',
            status: 'not_configured',
            reason_code: 'publish_surface.simulated',
            message:
              'Internet Archive is running in simulation - this meeting will NOT be published there and nothing will be written.',
          },
          {
            name: 'nas',
            status: 'not_configured',
            reason_code: 'publish_surface.simulated',
            message:
              'Local NAS archive is running in simulation - this meeting will NOT be published there and nothing will be written.',
          },
        ],
      }),
    })
  })
  await page.route('**/api/staff/live/sessions/*/go-on-air', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session('on_air')),
    })
  })
  await page.route('**/api/staff/live/sessions/*/end-broadcast', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session('ending')),
    })
  })
  // Beta B2 finalization panel defaults: no job yet, session still ending.
  await page.route('**/api/staff/live/sessions/*/finalization', async (route) => {
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Finalization status not found' }),
    })
  })
  await page.route('**/api/staff/live/sessions/council-live-room', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(session('ending')),
    })
  })
}

async function openLive(
  page: import('@playwright/test').Page,
  options: MockLiveOptions = {},
) {
  await mockLiveBackend(page, options)
  await page.goto('/')
  await page.getByRole('button', { name: 'Live', exact: true }).click()
  if (!options.failConfiguration) {
    await expect(page.getByRole('heading', { name: 'Live' })).toBeVisible()
  }
}

test.describe('operator live room', () => {
  test.describe.configure({ mode: 'serial' })

  test('runs pre-flight, starts live stream, switches source, and ends', async ({
    page,
  }) => {
    await openLive(page)

    await expect(page.getByRole('radio', { name: /Council Chamber Encoder/ })).toBeVisible()
    await page.getByRole('button', { name: 'Create live session' }).click()
    await expect(page.getByText('Idle')).toBeVisible()

    await page.getByRole('button', { name: 'Start pre-flight' }).click()
    await page.getByLabel(/Operator confirms/).check()
    await page.getByRole('button', { name: 'Run pre-flight' }).click()
    await expect(page.getByText('Pre-flight ready')).toBeVisible()

    await page.getByRole('button', { name: 'Start Live Stream' }).click()
    await expect(page.getByText('On air')).toBeVisible()

    await page.getByRole('radio', { name: /Council Chamber Encoder/ }).press('ArrowRight')
    await expect(page.getByRole('radio', { name: /Floor Camera NDI/ })).toHaveAttribute(
      'aria-checked',
      'true',
    )

    await page.getByRole('button', { name: 'End Live Stream' }).click()
    await expect(page.getByText('Ending')).toBeVisible()
  })

  test('unverified source preview is honest and actionable', async ({ page }) => {
    await openLive(page)
    await expect(page.getByLabel('Source dropped')).toHaveCount(0)
    await expect(page.getByText('Source preview unavailable')).toBeVisible()
    await expect(page.getByText(/No simulated preview or audio meter is shown/)).toBeVisible()
    await expect(page.getByText(/Connect a real encoder or meeting source/)).toBeVisible()
  })

  test('shows remote ingest health and local default fallback', async ({ page }) => {
    await openLive(page)
    await expect(page.getByRole('heading', { name: 'Remote ingest' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Project Hosted Relay' })).toBeVisible()
    await expect(page.getByText('Cloud relay - project-hosted')).toBeVisible()
    await expect(page.getByText('Recommended: Project Hosted Relay')).toBeVisible()
    await expect(page.getByText(/Outbound only/)).toBeVisible()
    await expect(page.getByText('Ready', { exact: true }).first()).toBeVisible()

    await openLive(page, { relays: [] })
    await expect(page.getByText('Local default')).toBeVisible()
    await expect(page.getByText(/No cloud relay is configured/)).toBeVisible()
  })

  test('loading state is visible while configuration loads', async ({ page }) => {
    await page.route('**/api/setup/station-state', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SETUP_READY),
      })
    })
    await page.route('**/api/setup/storage', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(STORAGE_READY),
      })
    })
    await page.route('**/api/staff/installer/safe-to-broadcast', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(HEALTH_REPORT),
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
    await page.route('**/api/staff/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          operator_id: 'test-operator',
          operator_display_name: 'Test Operator',
          token_id: 'env-test',
          scopes: ['meeting_operator'],
          roles: ['meeting_operator'],
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
    await page.route('**/api/staff/live/relay-configs', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([relayConfig]),
      })
    })
    await page.route('**/api/staff/live/ingest-plan**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(ingestPlan([relayConfig])),
      })
    })
    await page.route('**/api/staff/assets', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })
    await page.route('**/api/staff/live/sources', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([sourceA, sourceB]),
      })
    })
    await page.route('**/api/staff/live/recording-targets', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    })
    await page.goto('/')
    await page.getByRole('button', { name: 'Live', exact: true }).click()
    await expect(page.getByText('Loading live-room configuration...')).toBeVisible()
  })

  test('empty source state is actionable', async ({ page }) => {
    await openLive(page, { sources: [] })
    await expect(page.getByRole('heading', { name: 'Choose a camera or test source' })).toBeVisible()
    await expect(page.getByText('Camera plugged into this computer')).toBeVisible()
    await expect(page.getByText('Sample recording or uploaded test file')).toBeVisible()
  })

  test('keeps live-room read-only without meeting operator role', async ({ page }) => {
    await openLive(page, { roles: ['records_clerk'] })

    await expect(page.getByText(/Live-room controls require the meeting operator role/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Create live session' })).toBeDisabled()
    await expect(page.getByLabel(/Operator confirms/)).toBeDisabled()
    await expect(page.getByRole('radio', { name: /Council Chamber Encoder/ })).toBeVisible()
  })

  test('configuration error state is actionable', async ({ page }) => {
    await openLive(page, { failConfiguration: true })
    await expect(page.getByText('Could not load live room.')).toBeVisible()
    await expect(page.getByText(/connected to its database/)).toBeVisible()
  })

  test('blocked pre-flight keeps Start Live Stream disabled with next steps', async ({
    page,
  }) => {
    await openLive(page, { preflightReady: false })
    await page.getByRole('button', { name: 'Create live session' }).click()
    await page.getByRole('button', { name: 'Start pre-flight' }).click()
    await page.getByRole('button', { name: 'Run pre-flight' }).click()

    await expect(page.getByText('Pre-flight blocked')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start Live Stream' })).toBeDisabled()
    await expect(page.getByText(/Resolve network.unreachable/)).toBeVisible()
    await expect(page.getByText(/Resolve operator.unconfirmed/)).toBeVisible()
  })

  test('axe scan has no serious or critical violations', async ({ page }) => {
    await openLive(page)
    const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
    const blockers = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    )
    if (blockers.length > 0) {
      const summary = blockers
        .map(
          (v) =>
            `[${v.impact}] ${v.id}: ${v.help}\n    ${v.helpUrl}\n    nodes: ${v.nodes
              .map((n) => n.target.join(' '))
              .join('; ')}`,
        )
        .join('\n\n')
      throw new Error(
        `axe-core found ${blockers.length} serious/critical violation(s) in the live room:\n\n${summary}`,
      )
    }
  })

  test('Stage G: channel selector persists the choice and reaches the session payload', async ({
    page,
  }) => {
    await openLive(page)
    const selector = page.getByLabel('Broadcast channel')
    await expect(selector).toBeVisible()
    await expect(selector).toHaveValue('government')

    await selector.selectOption('education')
    await expect(selector).toHaveValue('education')

    // The choice survives a reload (persisted locally).
    await page.reload()
    await page.getByRole('button', { name: 'Live', exact: true }).click()
    await expect(page.getByLabel('Broadcast channel')).toHaveValue('education')

    // The create-session payload carries the selected channel.
    let createdChannelId: string | undefined
    await page.route('**/api/staff/live/sessions', async (route) => {
      const body = route.request().postDataJSON() as { channel_id?: string }
      createdChannelId = body.channel_id
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          live_session_id: 'council-live-room',
          channel_id: body.channel_id,
          title: 'Council live room',
          state: 'idle',
          started_at: null,
          ended_at: null,
          notes: null,
          created_at: '2026-06-10T18:00:00Z',
        }),
      })
    })
    await page.getByRole('button', { name: 'Create live session' }).click()
    await expect.poll(() => createdChannelId).toBe('education')

    // Channel is fixed once a session exists.
    await expect(page.getByLabel('Broadcast channel')).toBeDisabled()
  })

  test('Beta B2: terminal finalization failure shows the reason and a retry button', async ({
    page,
  }) => {
    await openLive(page)
    const failedJob = {
      live_session_id: 'council-live-room',
      state: 'failed',
      attempts: 3,
      max_attempts: 3,
      recording_uri: null,
      recording_size_bytes: null,
      next_attempt_at: null,
      failure_reason:
        'No recording file was found for this session (expected C:\\recordings\\council-live-room.mp4). Check that the recorder wrote to the configured recording target.',
      failure_code: 'recording.never_appeared',
      failure_detail: null,
      asset_id: null,
      local_package_manifest_path: null,
      package_manifest_url: null,
      trim_in_seconds: null,
      trim_out_seconds: null,
      started_at: null,
      completed_at: null,
      created_at: '2026-06-10T18:00:00Z',
      updated_at: '2026-06-10T18:35:00Z',
      terminal: true,
    }
    let currentJob: Record<string, unknown> = failedJob
    let retried = false
    await page.route('**/api/staff/live/sessions/*/finalization', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentJob),
      })
    })
    await page.route('**/api/staff/live/sessions/*/finalization/retry', async (route) => {
      retried = true
      currentJob = { ...failedJob, state: 'pending', attempts: 0, failure_reason: null, failure_code: null, terminal: false }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentJob),
      })
    })

    // Drive the session to ending so the panel mounts.
    await page.getByRole('button', { name: 'Create live session' }).click()
    await page.getByRole('button', { name: 'Start pre-flight' }).click()
    await page.getByLabel(/Operator confirms/).check()
    await page.getByRole('button', { name: 'Run pre-flight' }).click()
    await expect(page.getByText('Pre-flight ready')).toBeVisible()
    await page.getByRole('button', { name: 'Start Live Stream' }).click()
    await page.getByRole('button', { name: 'End Live Stream' }).click()

    const panel = page.getByRole('region', { name: 'Recording finalization' })
    await expect(panel).toBeVisible()
    await expect(panel.getByText(/No recording file was found/)).toBeVisible()

    await panel.getByRole('button', { name: 'Retry finalization' }).click()
    await expect.poll(() => retried).toBe(true)
    await expect(panel.getByText('Pending')).toBeVisible()
  })
})
