import { expect, test } from '@playwright/test'
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process'
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
let staffToken = ''
let tokenFile = ''

function engineReachable(cmd: string): boolean {
  // `info` exits 0 only when the engine is actually reachable. No --format:
  // the exit code is what we need, and Docker vs podman expose different
  // template fields. No shell: spawnSync resolves the CLI via PATH/PATHEXT,
  // and a shell would need the args escaped (Node DEP0190).
  const result = spawnSync(cmd, ['info'], {
    stdio: 'ignore',
    windowsHide: true,
    timeout: 15_000,
  })
  return result.status === 0
}

function dockerAvailable(): boolean {
  // Any Docker-API engine reachable through its CLI. The old probe ran only
  // `docker`, so it reported "no engine" on every podman box (podman serves
  // the same API but ships no `docker` binary) — the testcontainers backend
  // this suite spawns talks to whichever is up. CI's Linux runners have the
  // docker CLI, so `docker` still covers them.
  return engineReachable('docker') || engineReachable('podman')
}

function requirePublicPortalDist() {
  if (!fs.existsSync(path.join(PUBLIC_PORTAL_DIST, 'index.html'))) {
    throw new Error(
      [
        'real-boundary smoke needs the built public portal for resident-view proof.',
        'Run from civiccast/apps/portal-operator:',
        '  npm run prepare:public-portal',
      ].join('\n'),
    )
  }
}

function backendLogTail() {
  return backendOutput.slice(-8_000)
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
          reject(new Error('Could not allocate a loopback port for the real-boundary API.'))
        }
      })
    })
  })
}

async function waitForBackendReady() {
  // Generous: testcontainer pull/start + 33 alembic migrations on cold Docker.
  const deadline = Date.now() + 150_000
  let lastError = ''
  while (Date.now() < deadline) {
    if (backendProcess?.exitCode != null) {
      throw new Error(
        `Real-boundary API exited with ${backendProcess.exitCode}.\n${backendLogTail()}`,
      )
    }
    try {
      const response = await fetch(`${backendUrl}/health`)
      if (response.ok && fs.existsSync(tokenFile)) {
        staffToken = fs.readFileSync(tokenFile, 'utf8').trim()
        if (staffToken) return
      }
      lastError = response.ok ? 'token file not ready' : `HTTP ${response.status}`
    } catch (error) {
      lastError = String(error)
    }
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  throw new Error(`Real-boundary API did not become ready: ${lastError}\n${backendLogTail()}`)
}

async function api(pathname: string, init: RequestInit = {}) {
  return fetch(`${backendUrl}${pathname}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${staffToken}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...init.headers,
    },
  })
}

test.describe.configure({ mode: 'serial' })
test.skip(!dockerAvailable(), 'Docker unavailable; real-boundary smoke needs Postgres testcontainer')

// Container cold-start + the full alembic chain (0001..0033+) legitimately
// exceeds Playwright's default 30s hook timeout on a cold Docker engine.
test.beforeAll(async () => {
  test.setTimeout(180_000)
  requirePublicPortalDist()
  const port = await findFreePort()
  backendUrl = `http://127.0.0.1:${port}`
  backendOutput = ''
  tokenFile = path.join(os.tmpdir(), `civiccast-real-boundary-token-${process.pid}.txt`)
  fs.rmSync(tokenFile, { force: true })

  backendProcess = spawn(
    PYTHON,
    [
      '-m',
      'uvicorn',
      'tests.integration.operator_real_boundary_app:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
    ],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        CIVICCAST_PUBLIC_PORTAL_DIST: PUBLIC_PORTAL_DIST,
        CIVICCAST_RESIDENT_PORTAL_URL: backendUrl,
        // Stage G portal analytics: the resident home emits view events;
        // configure ingest like a set-up station so the no-console-error
        // gate sees a healthy resident page instead of fail-soft 503s.
        CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS: backendUrl,
        CIVICCAST_REAL_BOUNDARY_TOKEN_FILE: tokenFile,
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
  if (backendProcess && backendProcess.exitCode == null) {
    backendProcess.kill()
  }
  if (tokenFile) fs.rmSync(tokenFile, { force: true })
})

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    ({ apiBase, token }) => {
      window.__CIVICCAST_API_BASE__ = apiBase
      window.__CIVICCAST_STAFF_TOKEN__ = token
    },
    { apiBase: backendUrl, token: staffToken },
  )
})

test('@fullstack @realboundary publishes, reviews, and subscribes against real API + Postgres', async ({ page }) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') {
      // Include the source URL so a failing-resource error names the endpoint.
      consoleErrors.push(`${message.text()} :: ${message.location().url}`)
    }
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await page.getByRole('button', { name: 'Publish' }).click()
  await expect(page.getByRole('heading', { name: 'Publish dashboard' })).toBeVisible()

  const panel = page.locator('article').filter({ hasText: 'Council - Real Boundary Smoke' })
  await expect(panel).toBeVisible()
  await panel.getByRole('button', { name: 'Approve and Publish selected' }).click()
  await expect(panel.getByText('Portal public')).toBeVisible()
  await expect(panel.getByText('IA and local NAS verified')).toBeVisible()

  await page.goto(`${backendUrl}/`)
  await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()
  // Issue #107 renamed the resident home section to "Latest recordings".
  await expect(page.getByRole('heading', { name: 'Latest recordings' })).toBeVisible()
  await expect(page.getByText('Council - Real Boundary Smoke')).toBeVisible()

  const review = await api('/api/staff/summaries/review-items')
  expect(review.status).toBe(200)
  const reviewBody = (await review.json()) as { items: Array<{ summary_id: string }> }
  expect(reviewBody.items.map((item) => item.summary_id)).toContain('summary-real-boundary')

  const approval = await api('/api/staff/summaries/summary-real-boundary/approve', {
    method: 'POST',
    body: JSON.stringify({ approval_note: 'Real-boundary smoke checked by Playwright.' }),
  })
  expect(approval.status).toBe(200)
  expect((await approval.json()).status).toBe('approved')

  const signup = await fetch(`${backendUrl}/api/public/subscribe/email`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: 'resident-real-boundary@example.org',
      target_type: 'channel',
      target_id: 'government',
    }),
  })
  expect(signup.status).toBe(200)
  const signupBody = (await signup.json()) as { confirmation_token?: string }
  expect(signupBody.confirmation_token).toBeTruthy()

  const confirm = await fetch(
    `${backendUrl}/api/public/subscribe/confirm?token=${encodeURIComponent(
      signupBody.confirmation_token ?? '',
    )}`,
  )
  expect(confirm.status).toBe(200)
  expect((await confirm.json()).status).toBe('confirmed')

  expect(consoleErrors).toEqual([])
  expect(pageErrors).toEqual([])
})
