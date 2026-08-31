import { expect, test } from '@playwright/test'

const now = '2026-05-31T20:00:00Z'

const cableProfile = {
  channel_id: 'public',
  slug: 'public',
  kind: 'public',
  branding: {
    display_name: 'Public Channel',
    short_name: 'Public',
    color: '#2458A6',
    logo_text: 'PUBLIC',
  },
  programming_rules: ['Live meetings take priority over file playback.'],
  fallback_behavior: 'Use the channel slate when live or file playback is unavailable.',
  default_slate_asset_id: 'slate-public',
  outputs: [
    {
      kind: 'hls',
      label: 'Resident and CTV HLS',
      target: '/api/public/channels/public/live.m3u8',
      proof_boundary: 'software-output-url',
      next_step: 'Connect this URL to the channel playout worker before partner proof.',
    },
  ],
}

const appChannel = {
  channel_id: 'public',
  slug: 'public',
  kind: 'public',
  branding: {
    display_name: 'Public Channel',
    short_name: 'Public',
    color: '#2458A6',
    logo_text: 'PUBLIC',
    logo_url: null,
  },
  outputs: [
    {
      kind: 'hls',
      label: 'Resident and CTV HLS',
      target: '/api/public/channels/public/live.m3u8',
      proof_boundary: 'software-output-url',
      app_targets: ['web_pwa', 'roku', 'tvos', 'fire_tv', 'android_tv', 'android_mobile', 'ios_ipados', 'cg', 'epg'],
    },
  ],
  programming_rules: ['Live meetings take priority over file playback.'],
  fallback_behavior: 'Use the channel slate when live or file playback is unavailable.',
  live_state_url: '/api/public/app/channels/public/live',
  schedule_feed_url: '/api/public/app/channels/public/schedule',
  vod_catalog_url: '/api/public/app/channels/public/catalog',
  cg_feed_url: '/api/public/app/channels/public/cg',
  app_targets: ['web_pwa', 'roku', 'tvos', 'fire_tv', 'android_tv', 'android_mobile', 'ios_ipados', 'cg', 'epg'],
}

function stationConfig(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    station_id: 'civiccast-station',
    station_name: 'CivicCast station',
    generated_at: now,
    default_channel_id: 'public',
    build_profile: {
      tier: 'unbranded',
      app_name: 'CivicCast station',
      platform_targets: ['web_pwa', 'roku', 'tvos', 'fire_tv', 'android_tv', 'android_mobile', 'ios_ipados'],
      icon_url: null,
      splash_url: null,
      store_ready: false,
      store_notes: 'Reference app-platform config; branded store packaging lands later.',
    },
    channels: [appChannel],
    support_url: '/support',
    privacy_url: '/privacy',
    analytics_enabled: false,
    emergency_status_url: '/api/public/cg/emergency',
    ...overrides,
  }
}

async function mockChannelOps(
  page: import('@playwright/test').Page,
  options: { roles?: string[]; identityStatus?: number } = {},
) {
  const roles = options.roles ?? ['setup_admin', 'publish_operator', 'meeting_operator']
  const identityStatus = options.identityStatus ?? 200
  let currentAppChannel = appChannel
  let currentStationConfig = stationConfig()
  let egressState = {
    channel_id: 'public',
    state: 'STOPPED',
    current_source_label: null,
    current_proof_event_id: null,
    updated_at: now,
    pid: null,
    last_error: null,
  }
  const requests = {
    stationPatch: 0,
    brandingPatch: 0,
    egressCommands: [] as string[],
    configPuts: [] as Array<Record<string, unknown>>,
    headendApplies: [] as Array<Record<string, unknown>>,
  }
  await page.route('**/api/staff/egress/headend-profiles', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          profile_id: 'comcast-mtd-sd',
          label: 'Comcast MTD - SD (MPEG-2, CableLabs SD numbers)',
          vendor: 'Comcast Technology Solutions, Managed Terrestrial Distribution',
          source_urls: ['https://www.comcasttechnologysolutions.com/managed-terrestrial-distribution'],
          canonical_profile: {
            width: 720,
            height: 480,
            fps: 30,
            video_codec: 'mpeg2video',
            video_bitrate_kbps: 3180,
            gop_size: 15,
            audio_codec: 'ac3',
            audio_bitrate_kbps: 192,
            audio_sample_rate: 48000,
            audio_channels: 2,
            container: 'mpegts',
          },
          muxrate_kbps: 3750,
          transport: 'udp-multicast',
          pkt_size: 1316,
          min_port: 1,
          mpegts_extra_args: [],
          operator_must_supply: ['Multicast group address and UDP port assigned by Comcast.'],
          not_claimed: ['Built from published vendor documentation; provider validation is still required against the real cable headend.'],
        },
      ]),
    })
  })
  await page.route('**/api/staff/egress/channels/public/config/headend-profile', async (route) => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    requests.headendApplies.push(payload)
    egressConfig = {
      ...egressConfig,
      sinks: [
        {
          kind: 'udp-ts',
          label: 'Cable headend',
          uri: payload.destination_uri,
          secret_ref: null,
          latency_ms: 2000,
          extra_output_args: ['-muxrate', '3750k'],
        },
      ],
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(egressConfig),
    })
  })
  let egressConfig: Record<string, unknown> = {
    channel_id: 'public',
    enabled: true,
    auto_start: false,
    fill_policy: 'slate',
    sinks: [],
    loudness_target_lufs: -24,
    loudness_tolerance_lufs: 2,
    slate_message: 'We will be right back.',
  }
  await page.route('**/api/staff/egress/channels/public/config', async (route) => {
    if (route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON() as Record<string, unknown>
      requests.configPuts.push(payload)
      egressConfig = payload
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(egressConfig),
    })
  })
  await page.route('**/api/staff/auth/me', async (route) => {
    if (identityStatus !== 200) {
      await route.fulfill({
        status: identityStatus,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'identity unavailable' }),
      })
      return
    }
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
  await page.route('**/api/staff/cable/channels', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([cableProfile]),
    })
  })
  await page.route('**/api/staff/app/config**', async (route) => {
    if (route.request().method() === 'PATCH') {
      requests.stationPatch += 1
      const base = stationConfig()
      currentStationConfig = {
        ...base,
        station_name: 'Longmont Public Apps',
        build_profile: {
          ...base.build_profile,
          app_name: 'Longmont Channels',
          tier: 'branded',
          store_ready: true,
        },
        analytics_enabled: true,
        channels: [currentAppChannel],
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentStationConfig),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(currentStationConfig),
    })
  })
  await page.route('**/api/staff/app/channels/public/branding**', async (route) => {
    requests.brandingPatch += 1
    currentAppChannel = {
      ...appChannel,
      branding: {
        ...appChannel.branding,
        display_name: 'Public Access Live',
        short_name: 'Access',
        color: '#114488',
        logo_text: 'PAL',
      },
    }
    currentStationConfig = {
      ...currentStationConfig,
      channels: [currentAppChannel],
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(currentAppChannel),
    })
  })
  await page.route('**/api/staff/cable/channels/*/now-next', async (route) => {
    const block = {
      block_id: 'public-now',
      channel_id: 'public',
      kind: 'live',
      title: 'Public live programming',
      starts_at: now,
      duration_seconds: 1800,
      source_ref: 'live-source-public',
      status: 'playing',
      caption_refs: ['public-live.vtt'],
      failover_from: null,
      failover_reason: null,
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: now,
        channel: cableProfile,
        current: block,
        next: null,
        fallback_active: false,
        proof_boundary: 'software-schedule-and-playout-contract',
      }),
    })
  })
  await page.route('**/api/staff/cable/channels/*/proof-log', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: now,
        channel: cableProfile,
        events: [],
        export_formats: ['json'],
        not_claimed: [],
      }),
    })
  })
  await page.route('**/api/staff/cable/channels/*/playout-plan', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: now,
        channel: cableProfile,
        source: 'sample-contract',
        blocks: [],
        gap_blocks: [],
        export_formats: ['json'],
        proof_boundary: 'software-schedule-to-playout-plan',
        not_claimed: [],
      }),
    })
  })
  await page.route('**/api/staff/egress/channels/public/state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(egressState),
    })
  })
  await page.route('**/api/staff/egress/channels', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          channel_id: 'public',
          enabled: true,
          sink_count: Array.isArray(egressConfig.sinks) ? egressConfig.sinks.length : 0,
          fill_policy: egressConfig.fill_policy,
          auto_start: egressConfig.auto_start,
        },
      ]),
    })
  })
  await page.route('**/api/staff/egress/channels/public/health?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          channel_id: 'public',
          sampled_at: now,
          state: egressState.state,
          sink_connected: { Headend: egressState.state === 'ON_AIR' },
          encoder_fps: null,
          encoder_bitrate_kbps: null,
          dropped_frames: 0,
          seconds_on_air: egressState.state === 'ON_AIR' ? 12 : 0,
          last_loudness_lufs: null,
        },
      ]),
    })
  })
  await page.route('**/api/staff/egress/channels/public/commands', async (route) => {
    const payload = await route.request().postDataJSON() as { action: string }
    requests.egressCommands.push(payload.action)
    egressState = {
      ...egressState,
      state: payload.action === 'start' ? 'ON_AIR' : payload.action === 'stop' ? 'STOPPED' : egressState.state,
      current_source_label: payload.action === 'start' ? 'Public live programming' : null,
      pid: payload.action === 'start' ? 4321 : null,
    }
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        queued: true,
        command: {
          channel_id: 'public',
          action: payload.action,
          issued_at: now,
          issued_by: 'operator-console',
          command_id: `egress-${payload.action}`,
        },
      }),
    })
  })
  await page.route('**/api/public/channels/ctv/feed**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: now,
        station_name: 'CivicCast station',
        items: [],
        browse_facets: ['channel'],
        proof_boundary: 'reference-feed-api-not-channel-store-publication',
      }),
    })
  })
  return requests
}

test('operator can edit station app config and channel branding', async ({ page }) => {
  const requests = await mockChannelOps(page)
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Station app config' })).toBeVisible()
  await page.getByLabel('Station name').fill('Longmont Public Apps')
  await page.getByLabel('App name').fill('Longmont Channels')
  await page.getByLabel('Build tier').selectOption('branded')
  await page.getByLabel('Analytics enabled').check()
  await page.getByLabel('Store ready').check()
  await page.getByRole('button', { name: 'Save station config' }).click()
  await expect.poll(() => requests.stationPatch).toBe(1)

  await page.getByLabel('Display name').fill('Public Access Live')
  await page.getByLabel('Short name').fill('Access')
  await page.getByLabel('Color').fill('#114488')
  await page.getByLabel('Logo text').fill('PAL')
  await page.getByRole('button', { name: 'Save channel branding' }).click()
  await expect.poll(() => requests.brandingPatch).toBe(1)
  await expect(page.getByText('Public Access Live').first()).toBeVisible()
  await expect(page.getByText('PAL').first()).toBeVisible()
})

test('operator can queue channel egress start and stop commands', async ({ page }) => {
  const requests = await mockChannelOps(page, { roles: ['meeting_operator'] })
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Outgoing channel feed' })).toBeVisible()
  await expect(page.getByText('State: Stopped')).toBeVisible()

  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Start feed' }).click()
  await expect.poll(() => requests.egressCommands).toEqual(['start'])
  await expect(page.getByText('State: On air')).toBeVisible()
  await expect(page.getByText('Source: Public live programming')).toBeVisible()

  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Stop feed' }).click()
  await expect.poll(() => requests.egressCommands).toEqual(['start', 'stop'])
  await expect(page.getByText('State: Stopped')).toBeVisible()
})

test('setup admin can save 24/7 automation settings (CA-5)', async ({ page }) => {
  const requests = await mockChannelOps(page)
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Run this channel 24/7' })).toBeVisible()

  await page.getByLabel(/Keep this channel on air/).check()
  await page.getByRole('radio', { name: /Community bulletins/ }).click()
  await page.getByLabel('Slate message').fill('Back after the bulletin board.')
  // Issue #116: the BYO-NDI output name rides the same config save.
  await page.getByLabel(/NDI output name/).fill('CivicCast Public')
  // Issue #117: the BYO-SDI output device rides the same config save.
  await page.getByLabel(/SDI output device/).fill('DeckLink Mini Monitor 4K')
  await page.getByRole('button', { name: 'Save automation settings' }).click()

  await expect.poll(() => requests.configPuts.length).toBe(1)
  expect(requests.configPuts[0]).toMatchObject({
    channel_id: 'public',
    auto_start: true,
    fill_policy: 'bulletins',
    slate_message: 'Back after the bulletin board.',
    ndi_relay_name: 'CivicCast Public',
    sdi_relay_device: 'DeckLink Mini Monitor 4K',
  })

  // Audit TEST-006: clearing the SDI field must send an explicit null
  // (disable), never an empty string the backend would 422.
  await page.getByLabel(/SDI output device/).fill('')
  await page.getByRole('button', { name: 'Save automation settings' }).click()
  await expect.poll(() => requests.configPuts.length).toBe(2)
  expect(requests.configPuts[1]).toMatchObject({ sdi_relay_device: null })
})

test('automation settings stay read-only without setup admin role', async ({ page }) => {
  const requests = await mockChannelOps(page, { roles: ['meeting_operator'] })
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Run this channel 24/7' })).toBeVisible()
  await expect(
    page.getByText('Automation settings require the setup admin role.'),
  ).toBeVisible()
  await expect(page.getByLabel(/Keep this channel on air/)).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Save automation settings' })).toBeDisabled()
  expect(requests.configPuts).toEqual([])
})

test('setup admin can apply a headend delivery preset (CA-6)', async ({ page }) => {
  const requests = await mockChannelOps(page)
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Cable headend delivery' })).toBeVisible()
  // The preset surfaces what the operator must supply and the honesty boundary.
  await expect(page.getByText(/You supply: Multicast group address/)).toBeVisible()
  await expect(page.getByText(/provider validation is still required against the real cable headend/)).toBeVisible()

  await page
    .getByLabel(/Destination \(udp:\/\/address:port\)/)
    .fill('udp://239.255.0.1:5000')
  // The panel defaults to keeping the channel's other outputs -- uncheck it
  // so this test still exercises (and the ConfirmDialog body still names)
  // the "removes the other outputs" branch it always covered.
  await page
    .getByRole('checkbox', { name: "Keep the channel's other outputs alongside the headend feed" })
    .uncheck()
  await page.getByRole('button', { name: 'Apply headend preset' }).click()
  const applyDialog = page.getByRole('alertdialog', { name: 'Apply this headend preset?' })
  await expect(applyDialog).toBeVisible()
  await expect(applyDialog).toContainText("removes the channel's other outputs")
  await applyDialog.getByRole('button', { name: 'Apply preset' }).click()
  await expect(applyDialog).toBeHidden()

  await expect.poll(() => requests.headendApplies.length).toBe(1)
  expect(requests.headendApplies[0]).toMatchObject({
    profile_id: 'comcast-mtd-sd',
    destination_uri: 'udp://239.255.0.1:5000',
    keep_existing_sinks: false,
  })
  await expect(
    page.getByText('Current headend output: udp-ts → udp://239.255.0.1:5000'),
  ).toBeVisible()
})

test('operator can verify the headend stream with TSDuck (CA-7)', async ({ page }) => {
  const requests = await mockChannelOps(page)
  let probeCalls = 0
  await page.route('**/api/staff/egress/channels/public/compliance-probe', async (route) => {
    probeCalls += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        channel_id: 'public',
        destination: 'udp://239.255.0.1:5000',
        probed_at: now,
        seconds: 10,
        expected_muxrate_kbps: 3750,
        tsduck_version: 'tsp: TSDuck 3.44',
        checks: [
          { check: 'cbr-mux-rate', status: 'pass', detail: '0.00% drift' },
          { check: 'continuity', status: 'pass', detail: '0 discontinuities' },
        ],
        verdict: 'pass',
        detail: '',
        raw_report_path: null,
        not_claimed: ['Analyze-plugin subset; not the full TR 101 290 suite.'],
      }),
    })
  })
  await page.goto('/#/channels')

  // Apply a preset first so the udp-ts sink (and the verify button) exists.
  await page
    .getByLabel(/Destination \(udp:\/\/address:port\)/)
    .fill('udp://239.255.0.1:5000')
  await page.getByRole('button', { name: 'Apply headend preset' }).click()
  const applyDialog = page.getByRole('alertdialog', { name: 'Apply this headend preset?' })
  await expect(applyDialog).toBeVisible()
  await applyDialog.getByRole('button', { name: 'Apply preset' }).click()
  await expect(applyDialog).toBeHidden()
  await expect.poll(() => requests.headendApplies.length).toBe(1)

  // Verifying with TSDuck is a read-only probe -- it still fires immediately,
  // with no confirmation step.
  await page.getByRole('button', { name: 'Verify stream (TSDuck)' }).click()
  await expect.poll(() => probeCalls).toBe(1)
  await expect(page.getByText('Verification: pass')).toBeVisible()
  await expect(
    page.getByText(/Not claimed: Analyze-plugin subset; not the full TR 101 290 suite/),
  ).toBeVisible()
  await expect(page.getByText(/cbr-mux-rate: pass/)).toBeVisible()
})

test('headend delivery stays read-only without setup admin role', async ({ page }) => {
  const requests = await mockChannelOps(page, { roles: ['meeting_operator'] })
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Cable headend delivery' })).toBeVisible()
  await expect(page.getByText('Headend delivery requires the setup admin role.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Apply headend preset' })).toBeDisabled()
  expect(requests.headendApplies).toEqual([])
})

test('channel egress controls stay read-only without meeting operator role', async ({ page }) => {
  const requests = await mockChannelOps(page, { roles: ['setup_admin', 'publish_operator'] })
  await page.goto('/#/channels')

  await expect(page.getByRole('heading', { name: 'Outgoing channel feed' })).toBeVisible()
  await expect(page.getByText('Outgoing feed controls require the meeting operator role.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeDisabled()
  expect(requests.egressCommands).toEqual([])
})

test('a missing staff session redirects away from channel controls', async ({ page }) => {
  const requests = await mockChannelOps(page, { identityStatus: 401 })
  await page.goto('/#/channels')

  await expect(page).toHaveURL(/#\/setup/)
  await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Outgoing channel feed' })).toHaveCount(0)
  expect(requests.egressCommands).toEqual([])
  expect(requests.headendApplies).toEqual([])
})
