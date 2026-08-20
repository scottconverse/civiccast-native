import { expect, test } from '@playwright/test'

const generatedAt = '2026-06-01T16:00:00Z'

const inventory = {
  generated_at: generatedAt,
  endpoints: [
    {
      endpoint_id: 'router-main',
      label: 'Main SDI matrix',
      vendor: 'blackmagic-design',
      protocol: 'blackmagic-videohub',
      transport: 'tcp',
      host: '192.0.2.10',
      port: 9990,
      enabled: true,
      notes: 'Preview-only fixture',
    },
  ],
  sources: [
    {
      input_id: 'src-council',
      label: 'Council chamber',
      physical_port: 'IN 1',
      live_source_id: 'council-live',
      enabled: true,
    },
    {
      input_id: 'src-slides',
      label: 'Presentation laptop',
      physical_port: 'IN 2',
      enabled: true,
    },
  ],
  destinations: [
    {
      output_id: 'dst-air',
      label: 'Channel 12 encoder',
      physical_port: 'OUT 1',
      channel_id: 'government',
      enabled: true,
    },
  ],
  proof_boundary: 'preview-only-no-hardware-send',
}

const panel = {
  panel_id: 'panel-router-main',
  label: 'Main router panel',
  endpoint_id: 'router-main',
  mobile_columns: 2,
  buttons: [
    {
      button_id: 'btn-council-air',
      label: 'Council to air',
      source_id: 'src-council',
      destination_id: 'dst-air',
      enabled: true,
      requires_confirmation: true,
      operator_action: 'Confirm before taking Council chamber to Channel 12 encoder.',
    },
  ],
}

async function mockFacilityRouter(page: import('@playwright/test').Page) {
  const requests: Array<Record<string, unknown>> = []
  const scheduleRequests: Array<Record<string, unknown>> = []
  const overlayRequests: Array<Record<string, unknown>> = []
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'operator',
        operator_display_name: 'Operator',
        token_id: 'token',
        scopes: ['operator'],
        roles: ['broadcast_operator'],
      }),
    })
  })
  await page.route('**/api/staff/facility/router-inventory', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(inventory),
    })
  })
  await page.route('**/api/staff/facility/router-panel**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(panel),
    })
  })
  await page.route('**/api/staff/facility/router-take-plan', async (route) => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    requests.push(payload)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        request_id: payload.request_id,
        endpoint_id: payload.endpoint_id,
        vendor: 'blackmagic-design',
        protocol: 'blackmagic-videohub',
        transport: 'tcp',
        target: '192.0.2.10:9990',
        command_preview: 'VIDEO OUTPUT ROUTING:\\n1 1\\n\\n',
        command_bytes_hex: '564944454f',
        source_label: 'Council chamber',
        destination_label: 'Channel 12 encoder',
        scheduled_for: null,
        ready_to_send: true,
        operator_action: 'Review the command preview before enabling facility hardware send.',
        proof_boundary: 'preview-only-no-hardware-send',
      }),
    })
  })
  await page.route('**/api/staff/facility/router-schedule-plan', async (route) => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    scheduleRequests.push(payload)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        request_id: payload.request_id,
        schedule_item_id: payload.schedule_item_id,
        channel_id: payload.channel_id,
        starts_at: payload.starts_at,
        scheduled_take_at: '2026-06-01T17:59:45Z',
        preroll_seconds: payload.preroll_seconds,
        take_plan: {
          request_id: payload.request_id,
          endpoint_id: payload.endpoint_id,
          vendor: 'blackmagic-design',
          protocol: 'blackmagic-videohub',
          transport: 'tcp',
          target: 'tcp://192.0.2.10:9990',
          command_preview: 'VIDEO OUTPUT ROUTING:\\n1 1\\n\\n',
          command_bytes_hex: '564944454f',
          source_label: 'Council chamber',
          destination_label: 'Channel 12 encoder',
          scheduled_for: '2026-06-01T17:59:45Z',
          ready_to_send: true,
          operator_action: 'Confirm the previewed route, then send the command from the router panel.',
          proof_boundary: 'Command planning only; no hardware connection is opened by this API.',
        },
        automatic_take_ready: true,
        operator_action: 'Arm this schedule rule to preview the source before the event starts.',
        proof_boundary: 'Schedule-to-router command planning only; no hardware command is sent.',
      }),
    })
  })
  await page.route('**/api/staff/stream/overlay-compositor-plan', async (route) => {
    const payload = route.request().postDataJSON() as Record<string, unknown>
    overlayRequests.push(payload)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        channel_id: 'government',
        acceleration_mode: 'nvenc',
        gpu_accelerated: true,
        ordered_layers: payload.layers,
        z_order: {
          squeezeback: 10,
          'l-bar': 20,
          bug: 30,
          'lower-third': 40,
          emergency: 90,
        },
        filter_complex: '[0:v]scale=1306:778,pad=1920:1080:77:43:black[v0];[v0]drawbox=x=0:y=821:w=1920:h=259:color=0x111827@0.92:t=fill[v1];[v1]format=yuv420p[composited]',
        ffmpeg_args: ['-i', 'rtmp://127.0.0.1/live/government', '-c:v', 'h264_nvenc'],
        proof_boundary: 'overlay-compositor-command-planning-no-ffmpeg-execution',
        operator_action: 'Preview the overlay plan, then start the compositor from the live output panel.',
      }),
    })
  })
  return { requests, scheduleRequests, overlayRequests }
}

test('operator previews a facility router take without hardware send', async ({ page }) => {
  const { requests, scheduleRequests, overlayRequests } = await mockFacilityRouter(page)

  await page.goto('/#/facility')

  await expect(page.getByRole('heading', { name: 'Facility router' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Main SDI matrix/ })).toBeVisible()
  await page.getByRole('button', { name: /Council to air/ }).click()

  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toMatchObject({
    endpoint_id: 'router-main',
    source_id: 'src-council',
    destination_id: 'dst-air',
    requested_by: 'facility-operator',
  })
  await expect(page.getByRole('heading', { name: 'Take preview' })).toBeVisible()
  await expect(page.getByText('Council chamber to Channel 12 encoder', { exact: true })).toBeVisible()
  await expect(page.getByText('192.0.2.10:9990', { exact: true })).toBeVisible()
  await expect(page.getByText('VIDEO OUTPUT ROUTING:')).toBeVisible()
  await expect(page.getByText('preview-only-no-hardware-send').first()).toBeVisible()
  await expect(page.getByText('hardware send disabled')).toBeVisible()

  await page.getByRole('button', { name: 'Preview scheduled take' }).click()
  await expect.poll(() => scheduleRequests.length).toBe(1)
  expect(scheduleRequests[0]).toMatchObject({
    endpoint_id: 'router-main',
    source_id: 'src-council',
    destination_id: 'dst-air',
    channel_id: 'government',
    preroll_seconds: 15,
  })
  await expect(page.getByText('Schedule-to-router command planning only; no hardware command is sent.')).toBeVisible()

  await page.getByRole('button', { name: 'Preview L-bar and squeezeback' }).click()
  await expect.poll(() => overlayRequests.length).toBe(1)
  expect(overlayRequests[0]).toMatchObject({
    channel_id: 'government',
    acceleration_preference: 'auto',
  })
  await expect(page.getByText('Layer order:')).toBeVisible()
  await expect(page.getByText('squeezeback -> l-bar')).toBeVisible()
  await expect(page.getByText('h264_nvenc')).toBeVisible()
  await expect(page.getByText('overlay-compositor-command-planning-no-ffmpeg-execution')).toBeVisible()
})

test('facility router screen shows API failures as operator alerts', async ({ page }) => {
  await page.route('**/api/staff/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        operator_id: 'operator',
        operator_display_name: 'Operator',
        token_id: 'token',
        scopes: ['operator'],
        roles: ['broadcast_operator'],
      }),
    })
  })
  await page.route('**/api/staff/facility/router-inventory', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Facility router inventory unavailable' }),
    })
  })

  await page.goto('/#/facility')

  await expect(page.getByRole('alert')).toContainText('Facility router status could not load.')
  await expect(page.getByRole('alert')).toContainText('Facility router inventory unavailable')
})
