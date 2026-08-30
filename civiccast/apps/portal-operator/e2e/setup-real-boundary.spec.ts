import { expect, test } from '@playwright/test'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

declare global {
  interface Window {
    __CIVICCAST_API_BASE__?: string
    __CIVICCAST_STAFF_TOKEN__?: string
  }
}

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(E2E_DIR, '../../../..')
const PUBLIC_PORTAL_DIST = path.join(REPO_ROOT, 'civiccast/apps/portal-public/dist')
const E2E_YOUTUBE_SECRET = 'e2e-youtube-secret-value'
const E2E_WEBHOOK_SECRET = 'e2e-webhook-secret-value'
const PYTHON =
  process.env.PYTHON ??
  path.join(
    REPO_ROOT,
    '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
  )

let backendProcess: ChildProcessWithoutNullStreams | undefined
let backendUrl = ''
let backendOutput = ''
let storageDir = ''

function backendLogTail() {
  return backendOutput.slice(-8_000)
}

function requirePublicPortalDist() {
  if (!fs.existsSync(path.join(PUBLIC_PORTAL_DIST, 'index.html'))) {
    throw new Error(
      [
        'setup-real-boundary needs the built public portal for resident-preview proof.',
        'Run from civiccast/apps/portal-operator:',
        '  npm run prepare:public-portal',
      ].join('\n'),
    )
  }
}

async function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      server.close(() => {
        if (typeof address === 'object' && address != null) {
          resolve(address.port)
        } else {
          reject(new Error('Could not allocate a loopback port for setup boundary.'))
        }
      })
    })
  })
}

async function waitForBackendReady() {
  const deadline = Date.now() + 90_000
  let lastError = ''
  while (Date.now() < deadline) {
    if (backendProcess?.exitCode != null) {
      throw new Error(
        `Setup-boundary API exited with ${backendProcess.exitCode}.\n${backendLogTail()}`,
      )
    }
    try {
      const response = await fetch(`${backendUrl}/health`)
      if (response.ok) return
      lastError = `HTTP ${response.status}`
    } catch (error) {
      lastError = String(error)
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`Setup-boundary API did not become ready: ${lastError}\n${backendLogTail()}`)
}

async function stopBackendProcess() {
  if (!backendProcess || backendProcess.exitCode != null) return
  await new Promise<void>((resolve) => {
    const child = backendProcess
    if (!child) {
      resolve()
      return
    }
    const timer = setTimeout(resolve, 5_000)
    child.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
    child.kill()
  })
}

async function removeStorageDir() {
  if (!storageDir) return
  let lastError: unknown
  for (let attempt = 0; attempt < 12; attempt += 1) {
    try {
      fs.rmSync(storageDir, { recursive: true, force: true })
      return
    } catch (error) {
      lastError = error
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
  }
  throw lastError
}

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  requirePublicPortalDist()
  const port = await findFreePort()
  backendUrl = `http://127.0.0.1:${port}`
  backendOutput = ''
  storageDir = fs.mkdtempSync(path.join(os.tmpdir(), 'civiccast-setup-boundary-'))

  backendProcess = spawn(
    PYTHON,
    [
      '-m',
      'uvicorn',
      'tests.integration.operator_setup_boundary_app:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        CIVICCAST_ACTIVITYPUB_MODE: 'disabled',
        CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN: '1',
        CIVICCAST_ALLOW_EPHEMERAL_STORES: '',
        CIVICCAST_MANAGED_STORAGE_DIR: storageDir,
        CIVICCAST_PUBLIC_PORTAL_DIST: PUBLIC_PORTAL_DIST,
        CIVICCAST_RESIDENT_PORTAL_URL: backendUrl,
        CIVICCAST_SUPPORT_BUNDLE_DIR: path.join(storageDir, 'support-bundles'),
        CIVICCAST_STATION_STATE_PATH: path.join(storageDir, 'station-state.json'),
        CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET: E2E_WEBHOOK_SECRET,
        CIVICCAST_YOUTUBE_CLIENT_SECRET: E2E_YOUTUBE_SECRET,
        DATABASE_URL: '',
        CIVICCAST_UPLOAD_DIR: '',
        PYTHONPATH: REPO_ROOT,
      },
      windowsHide: true,
    },
  )
  backendProcess.stdout.on('data', (chunk: Buffer) => {
    backendOutput += chunk.toString()
  })
  backendProcess.stderr.on('data', (chunk: Buffer) => {
    backendOutput += chunk.toString()
  })
  await waitForBackendReady()
})

test.afterAll(async () => {
  await stopBackendProcess()
  await removeStorageDir()
})

test.beforeEach(async ({ page }) => {
  await page.addInitScript((apiBase) => {
    window.__CIVICCAST_API_BASE__ = apiBase
  }, backendUrl)
})

test('@fullstack @realboundary loopback-only setup prepares storage and creates first admin', async ({
  page,
}) => {
  test.setTimeout(180_000)
  await page.addInitScript(() => {
    window.__CIVICCAST_STAFF_TOKEN__ = 'CIVICCAST_STAFF_TOKENS'
    window.sessionStorage.setItem('civiccast.staffToken', 'operator-token-a')
  })
  // No nonce, no header, no query string: the Node test process and the
  // backend it spawned are both on loopback, so this plain request is
  // admitted on peer IP alone (`_require_local_setup_request`).
  const admitted = await fetch(`${backendUrl}/api/setup/storage`, {
    headers: { Accept: 'application/json' },
  })
  expect(admitted.status).toBe(200)

  await page.goto('/setup')
  await expect(page.getByRole('heading', { name: 'First setup' })).toBeVisible()
  const prepareButton = page.getByRole('button', { name: 'Prepare storage' })
  const readyBadge = page.getByText('Storage ready')
  const prepareVisible = await prepareButton.isVisible({ timeout: 5_000 }).catch(() => false)
  if (prepareVisible) {
    await prepareButton.click()
  } else {
    await expect(readyBadge).toBeVisible()
  }
  await expect(page.getByText('Storage ready')).toBeVisible({ timeout: 30_000 })

  await page.getByLabel('Station name').fill('Pinegrove School Board')
  await page.getByLabel('Admin display name').fill('Avery Admin')
  await page.getByLabel('Admin username').fill('avery')
  await page.locator('#admin_password').fill('correct horse battery staple')
  await page.locator('#confirm_password').fill('correct horse battery staple')
  await page
    .getByLabel('Where will you keep the recovery kit?')
    .fill('printed and stored in the clerk safe')
  await page.getByRole('button', { name: 'Create first admin' }).click()

  await expect(page.getByText('Recovery kit ready')).toBeVisible()
  // Field fix (candidate #17): the kit must show the routine admin
  // password, not just the emergency recovery codes.
  await expect(page.getByText('correct horse battery staple')).toBeVisible()

  // Lockout gate: nothing past the kit until save/print is confirmed.
  await expect(page.getByLabel('Backup folder')).toHaveCount(0)
  const confirmBox = page.getByRole('checkbox', {
    name: /I have saved or printed this kit/,
  })
  await expect(confirmBox).toBeDisabled()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Save kit' }).click()
  const kitDownload = await downloadPromise
  expect(kitDownload.suggestedFilename()).toMatch(/^civiccast-recovery-kit-rk_.+\.txt$/)
  await confirmBox.check()
  await page.getByRole('button', { name: 'Continue to the console' }).click()
  await expect(page.getByLabel('Backup folder')).toBeVisible()

  await expect(
    page.evaluate(() => window.localStorage.getItem('civiccast.staffToken')),
  ).resolves.toMatch(/^ccst_/)
  const staffToken = await page.evaluate(() => window.localStorage.getItem('civiccast.staffToken'))
  expect(staffToken).toMatch(/^ccst_/)

  const status = await fetch(`${backendUrl}/api/setup/storage`, {
    headers: { Accept: 'application/json' },
  })
  expect(status.status).toBe(200)
  const body = (await status.json()) as { upload_dir?: string; database_path?: string }
  expect(body.database_path).toContain('civiccast.sqlite3')
  expect(body.upload_dir).toContain('uploads')
  expect(fs.existsSync(path.join(storageDir, 'uploads'))).toBe(true)

  await page.getByLabel('Backup folder').fill(path.join(storageDir, 'backups'))
  await page.getByRole('button', { name: 'Verify backup' }).click()
  await expect(page.getByText('ready').first()).toBeVisible({ timeout: 30_000 })

  await page.getByRole('button', { name: 'USB webcam or HDMI capture' }).click()
  await page.getByLabel('Source name').fill('Council Room Camera')
  await page.getByLabel('Private RTMP stream address').fill('rtmp://127.0.0.1/live/e2e')
  await page.getByRole('button', { name: 'Save meeting source' }).click()
  await expect(page.getByText('Council Room Camera is saved as a meeting source.')).toBeVisible({
    timeout: 30_000,
  })

  await page.getByRole('button', { name: 'Bundled sample video' }).click()
  await page.getByRole('button', { name: 'Create sample media' }).click()
  await expect(page.getByText(/Ready: sample-rehearsal-/)).toBeVisible({ timeout: 30_000 })

  await page.goto('/#/health')
  await expect(page.getByRole('heading', { name: 'Safe to broadcast' })).toBeVisible()
  const [previewPage] = await Promise.all([
    page.context().waitForEvent('page'),
    page.getByRole('link', { name: 'Open resident preview' }).click(),
  ])
  await expect(previewPage.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()
  await expect(previewPage.getByText('Live now')).toBeVisible()
  await previewPage.close()

  const rehearsalResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/staff/installer/rehearsal') &&
      response.request().method() === 'POST',
    { timeout: 90_000 },
  )
  await page.getByRole('button', { name: 'Check broadcast readiness' }).click()
  const rehearsalResponse = await rehearsalResponsePromise
  expect(rehearsalResponse.status()).toBe(200)
  const rehearsalPayload = (await rehearsalResponse.json()) as {
    status?: string
    private_session_id?: string
    recording_asset_id?: string | null
    resident_preview_proof?: string | null
    message?: string
    evidence?: string[]
  }
  expect(rehearsalPayload.private_session_id).toMatch(/^rehearsal-/)
  // The validated recorded sample is the explicit private-rehearsal source. It
  // must produce end-to-end recording and resident-preview proof without being
  // represented as proof that the separately configured RTMP source was live.
  expect(rehearsalPayload.status).toBe('needs_attention')
  expect(rehearsalPayload.recording_asset_id).toBe(rehearsalPayload.private_session_id)
  expect(rehearsalPayload.resident_preview_proof).toMatch(/^Resident preview loaded/)
  expect(rehearsalPayload.message).toContain('passed required checks')
  expect(rehearsalPayload.evidence ?? []).toEqual(
    expect.arrayContaining([
      expect.stringContaining('validated sample asset'),
      expect.stringContaining('Live preflight passed'),
    ]),
  )
  await expect(page.getByRole('heading', { name: 'Broadcast readiness check result' })).toBeVisible()
  await expect(page.getByText(/private rehearsal passed required checks/i)).toBeVisible()
  await expect(page.getByText('Recording proof')).toBeVisible()
  await expect(page.getByText('Resident preview', { exact: true })).toBeVisible()

  await page.getByLabel('Short note').fill('Operator pasted a secret into the note.')
  const supportResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/staff/installer/support-bundle') &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: 'Create support bundle' }).click()
  const supportResponse = await supportResponsePromise
  expect(supportResponse.status()).toBe(200)
  const supportPayload = (await supportResponse.json()) as { path: string; redacted: boolean }
  expect(supportPayload.redacted).toBe(true)
  await expect(page.getByText('Support bundle ready')).toBeVisible()
  const bundle = fs.readFileSync(supportPayload.path, 'utf8')
  expect(bundle).not.toContain(E2E_YOUTUBE_SECRET)
  expect(bundle).not.toContain(E2E_WEBHOOK_SECRET)
  expect(bundle).not.toContain('Operator pasted a secret into the note.')
  expect(bundle).toContain('"value": "[redacted]"')

  expect(rehearsalPayload.recording_asset_id).toBe(rehearsalPayload.private_session_id)
})
