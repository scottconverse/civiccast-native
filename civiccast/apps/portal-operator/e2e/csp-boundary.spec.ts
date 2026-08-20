import { expect, test } from '@playwright/test'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Real-CSP gate (audit item #27): the production Content-Security-Policy
 * header must not break the actual built operator console or public
 * portal. Boots the real FastAPI app (real security headers, real CSP)
 * serving the real `npm run build` output for both portals — the same
 * shape as a station install — and asserts each page renders past its
 * loading state with zero CSP console violations.
 */

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(E2E_DIR, '../../../..')
const OPERATOR_DIST = path.join(REPO_ROOT, 'civiccast/apps/portal-operator/dist')
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

function requireBuiltDist(dir: string, label: string) {
  if (!fs.existsSync(path.join(dir, 'index.html'))) {
    throw new Error(
      `csp-boundary needs the built ${label} (run \`npm run build\` in its app dir first).`,
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
          reject(new Error('Could not allocate a loopback port for the CSP boundary.'))
        }
      })
    })
  })
}

async function waitForBackendReady() {
  const deadline = Date.now() + 60_000
  let lastError = ''
  while (Date.now() < deadline) {
    if (backendProcess?.exitCode != null) {
      throw new Error(`CSP boundary API exited with ${backendProcess.exitCode}.\n${backendLogTail()}`)
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
  throw new Error(`CSP boundary API did not become ready: ${lastError}\n${backendLogTail()}`)
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

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  requireBuiltDist(OPERATOR_DIST, 'operator console (npm run build in portal-operator)')
  requireBuiltDist(PUBLIC_PORTAL_DIST, 'public portal (npm run build in portal-public)')
  const port = await findFreePort()
  backendUrl = `http://127.0.0.1:${port}`
  backendOutput = ''

  backendProcess = spawn(
    PYTHON,
    ['-m', 'uvicorn', 'tests.integration.csp_boundary_app:app', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        CIVICCAST_OPERATOR_CONSOLE_DIST: OPERATOR_DIST,
        CIVICCAST_PUBLIC_PORTAL_DIST: PUBLIC_PORTAL_DIST,
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
})

test('@fullstack the real CSP does not break the built operator console', async ({ page }) => {
  const cspViolations: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && /content security policy|refused to/i.test(message.text())) {
      cspViolations.push(message.text())
    }
  })

  const response = await page.goto(`${backendUrl}/operator/`)
  expect(response?.status()).toBe(200)
  expect(response?.headers()['content-security-policy']).toContain("default-src 'self'")
  await expect(page.locator('#root')).not.toBeEmpty()
  expect(cspViolations).toEqual([])
})

test('@fullstack the real CSP does not break the built public portal', async ({ page }) => {
  const cspViolations: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && /content security policy|refused to/i.test(message.text())) {
      cspViolations.push(message.text())
    }
  })

  const response = await page.goto(`${backendUrl}/`)
  expect(response?.status()).toBe(200)
  expect(response?.headers()['content-security-policy']).toContain("default-src 'self'")
  await expect(page.locator('#root')).not.toBeEmpty()
  expect(cspViolations).toEqual([])
})
