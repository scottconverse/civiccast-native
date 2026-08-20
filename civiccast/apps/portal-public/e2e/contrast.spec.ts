import { test as base, expect, type Page } from '@playwright/test'

/**
 * S20 DC-4 — WCAG 2.1 AA contrast gate for the public portal.
 *
 * See the operator console's sibling spec
 * (`portal-operator/e2e/contrast.spec.ts`) for the full rationale: this
 * computes contrast directly from the rendered DOM/CSSOM against the
 * WCAG 2.1 AA thresholds (4.5:1 normal text, 3:1 large text) and refuses
 * to report a pass when the scanned element set is empty. Duplicated here
 * rather than shared because this repo's e2e specs are each self-contained
 * (see `a11y.spec.ts` in both portals, which independently duplicate their
 * own axe-core helper the same way).
 *
 * DC-4 explicitly calls out operator-uploaded branding/theme colors (S12)
 * as the thing this gate constrains — those colors render on the public
 * portal (channel branding), so the public portal needs its own gate, not
 * just the operator console.
 */

export interface ContrastFinding {
  selector: string
  text: string
  ratio: number
  required: number
  isLargeText: boolean
  foreground: string
  background: string
}

async function scanContrast(page: Page, selector = 'body *'): Promise<ContrastFinding[]> {
  return page.evaluate((sel) => {
    function relativeLuminance(r: number, g: number, b: number): number {
      const channel = (c: number) => {
        const s = c / 255
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
      }
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    }

    function parseRgb(value: string): [number, number, number, number] | null {
      const m = value.match(/rgba?\(([^)]+)\)/)
      if (!m) return null
      const parts = m[1].split(',').map((p) => parseFloat(p.trim()))
      const [r, g, b] = parts
      const a = parts.length > 3 ? parts[3] : 1
      if ([r, g, b].some((n) => Number.isNaN(n))) return null
      return [r, g, b, a]
    }

    // Chromium serializes modern color syntax (oklch(), color-mix(), lab())
    // verbatim from getComputedStyle — the operator console's stylesheet uses
    // oklch throughout, which made every element skip and fired the honesty
    // guard on this gate's FIRST real CI run (working as designed). The canvas
    // fillStyle round-trip is the browser's own normalizer: any valid CSS
    // color comes back as #rrggbb or rgba(), both parseable.
    // oklch() -> sRGB, numerically (Bjorn Ottosson's OKLab matrices). The
    // canvas-fillStyle round-trip CANNOT normalize modern color syntax: per
    // CSS Color 4 serialization, Chromium returns oklch colors AS oklch from
    // the fillStyle getter too — proven by this gate's second CI run. Doing
    // the math removes every browser-serialization dependency.
    function parseOklch(value: string): [number, number, number, number] | null {
      const m = value.match(/oklch\(\s*([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+)(?:deg)?\s*(?:\/\s*([\d.]+%?))?\s*\)/)
      if (!m) return null
      let L = parseFloat(m[1])
      if (m[1].endsWith('%')) L /= 100
      let C = parseFloat(m[2])
      if (m[2].endsWith('%')) C = (C / 100) * 0.4
      const H = parseFloat(m[3])
      let alpha = 1
      if (m[4]) {
        alpha = parseFloat(m[4])
        if (m[4].endsWith('%')) alpha /= 100
      }
      const aa = C * Math.cos((H * Math.PI) / 180)
      const bb = C * Math.sin((H * Math.PI) / 180)
      const l_ = L + 0.3963377774 * aa + 0.2158037573 * bb
      const m_ = L - 0.1055613458 * aa - 0.0638541728 * bb
      const s_ = L - 0.0894841775 * aa - 1.291485548 * bb
      const l = l_ ** 3
      const mm = m_ ** 3
      const s = s_ ** 3
      const lr = 4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * s
      const lg = -1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * s
      const lb = -0.0041960863 * l - 0.7034186147 * mm + 1.707614701 * s
      const gam = (c: number) => {
        const cc = Math.min(1, Math.max(0, c))
        return cc <= 0.0031308 ? 12.92 * cc : 1.055 * cc ** (1 / 2.4) - 0.055
      }
      return [Math.round(gam(lr) * 255), Math.round(gam(lg) * 255), Math.round(gam(lb) * 255), alpha]
    }

    const _colorCtx = document.createElement('canvas').getContext('2d')
    function toRgb(value: string): [number, number, number, number] | null {
      const direct = parseRgb(value)
      if (direct) return direct
      const oklch = parseOklch(value)
      if (oklch) return oklch
      // Legacy syntaxes (named colors, hex, hsl) DO canvas-normalize to hex/rgba.
      if (!_colorCtx) return null
      _colorCtx.fillStyle = '#000000'
      _colorCtx.fillStyle = value
      const normalized = _colorCtx.fillStyle as string
      if (normalized.startsWith('#')) {
        return [
          parseInt(normalized.slice(1, 3), 16),
          parseInt(normalized.slice(3, 5), 16),
          parseInt(normalized.slice(5, 7), 16),
          1,
        ]
      }
      return parseRgb(normalized)
    }

    function effectiveBackground(el: Element): [number, number, number] {
      let node: Element | null = el
      while (node) {
        const parsed = toRgb(getComputedStyle(node).backgroundColor)
        if (parsed && parsed[3] > 0) return [parsed[0], parsed[1], parsed[2]]
        node = node.parentElement
      }
      return [255, 255, 255]
    }

    function contrastRatio(fg: [number, number, number], bg: [number, number, number]): number {
      const l1 = relativeLuminance(fg[0], fg[1], fg[2]) + 0.05
      const l2 = relativeLuminance(bg[0], bg[1], bg[2]) + 0.05
      return l1 > l2 ? l1 / l2 : l2 / l1
    }

    function hasOwnText(el: Element): boolean {
      for (const child of Array.from(el.childNodes)) {
        if (child.nodeType === Node.TEXT_NODE && (child.textContent ?? '').trim().length > 0) {
          return true
        }
      }
      return false
    }

    function isVisible(el: Element): boolean {
      const style = getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) {
        return false
      }
      const rect = el.getBoundingClientRect()
      return rect.width > 0 && rect.height > 0
    }

    function describe(el: Element): string {
      const id = el.id ? `#${el.id}` : ''
      const cls =
        typeof el.className === 'string' && el.className.trim().length > 0
          ? `.${el.className.trim().split(/\s+/).join('.')}`
          : ''
      return `${el.tagName.toLowerCase()}${id}${cls}`
    }

    const findings: {
      selector: string
      text: string
      ratio: number
      required: number
      isLargeText: boolean
      foreground: string
      background: string
    }[] = []

    for (const el of Array.from(document.querySelectorAll(sel))) {
      if (!hasOwnText(el) || !isVisible(el)) continue
      const style = getComputedStyle(el)
      const fg = toRgb(style.color)
      if (!fg) continue
      const bg = effectiveBackground(el)
      const fontSizePx = parseFloat(style.fontSize)
      const fontWeight = parseInt(style.fontWeight, 10) || 400
      const isLargeText = fontSizePx >= 24 || (fontSizePx >= 18.66 && fontWeight >= 700)
      const required = isLargeText ? 3.0 : 4.5
      const ratio = contrastRatio([fg[0], fg[1], fg[2]], bg)
      findings.push({
        selector: describe(el),
        text: (el.textContent ?? '').trim().slice(0, 60),
        ratio: Math.round(ratio * 100) / 100,
        required,
        isLargeText,
        foreground: style.color,
        background: `rgb(${bg[0]}, ${bg[1]}, ${bg[2]})`,
      })
    }
    return findings
  }, selector)
}

async function scanContrastOrFail(page: Page, selector = 'body *'): Promise<ContrastFinding[]> {
  const findings = await scanContrast(page, selector)
  if (findings.length === 0) {
    throw new Error(
      `Contrast gate honesty guard: 0 elements survived the text/visibility/color filters for selector "${selector}". ` +
        'An empty scan is not a pass — fix the page/selector rather than trusting a silent green.',
    )
  }
  return findings
}

function failingRows(findings: ContrastFinding[]): ContrastFinding[] {
  return findings.filter((f) => f.ratio < f.required)
}

export const test = base.extend<{ scanContrast: typeof scanContrastOrFail }>({
  // eslint-disable-next-line no-empty-pattern -- Playwright fixture signature requires the first arg
  scanContrast: async ({}, runFixture) => {
    await runFixture(scanContrastOrFail)
  },
})

const liveOffline = {
  state: 'offline',
  live_session_id: null,
  channel_id: null,
  title: null,
  started_at: null,
  manifest_url: null,
}

const comingUp = [
  {
    id: 'ad8f4d91-5d43-4c1f-9ed2-b4e7e2fdd100',
    asset_id: 'budget-hearing',
    asset_title: 'Budget Hearing',
    channel_id: 'gov-ch12',
    mode: 'premiere',
    state: 'scheduled',
    scheduled_at: '2026-05-16T19:00:00Z',
    duration_seconds: 5400,
  },
]

const recordings = [
  {
    asset_id: 'planning-board',
    title: 'Planning Board',
    description: 'May planning board meeting.',
    manifest_url: 'https://cdn.example/planning/playlist.m3u8',
    poster_url: null,
    duration_seconds: 3600,
    published_at: '2026-05-12T20:00:00Z',
  },
]

test.beforeEach(async ({ page }) => {
  await page.route('**/api/public/live/current', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liveOffline) })
  })
  await page.route('**/api/public/schedule/coming-up', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(comingUp) })
  })
  await page.route('**/api/public/assets', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(recordings) })
  })
  await page.route('**/api/public/contribute/agreements/current', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        agreement_id: 'community-media-submission',
        version: '2026-05-31',
        title: 'Community media submission agreement',
        summary: 'Submitter confirms they have permission to share this media.',
        effective_at: '2026-05-31T00:00:00Z',
      }),
    })
  })
  await page.route('**/api/public/cg/idle', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        channel_id: 'gov-ch12',
        title: 'CivicCast is ready',
        message: 'No meeting is live right now. The next scheduled broadcast will start here.',
        next_broadcast_label: 'Next broadcast: Public Meetings test broadcast',
        action_label: 'View published recordings',
        action_url: '/',
      }),
    })
  })
  await page.route('**/api/public/app/analytics/events', async (route) => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        event_id: 'contrast-mock',
        retained_fields: [],
        proof_boundary: 'privacy-safe-contract-no-direct-viewer-identifiers',
      }),
    })
  })
})

test.describe('public portal contrast gate (WCAG 2.1 AA, S20 DC-4)', () => {
  test('resident landing page meets 4.5:1 / 3:1 thresholds', async ({ page, scanContrast }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()

    const findings = await scanContrast(page)
    const failures = failingRows(findings)
    expect(failures, `low-contrast elements:\n${JSON.stringify(failures, null, 2)}`).toEqual([])
  })

  test('mobile landing page meets thresholds', async ({ page, scanContrast }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()

    const findings = await scanContrast(page)
    const failures = failingRows(findings)
    expect(failures, `low-contrast elements:\n${JSON.stringify(failures, null, 2)}`).toEqual([])
  })

  test('honesty guard fails a scan when the selector matches nothing', async ({ page, scanContrast }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()

    await expect(scanContrast(page, '.no-such-selector-anywhere-on-this-page')).rejects.toThrow(
      /honesty guard/i,
    )
  })

  test('gate catches an injected low-contrast element (falsification proof)', async ({
    page,
    scanContrast,
  }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'CivicCast public portal' })).toBeVisible()

    await page.evaluate(() => {
      const probe = document.createElement('p')
      probe.id = 'contrast-falsification-probe'
      probe.textContent = 'This text is deliberately unreadable.'
      probe.style.color = '#fefefe'
      probe.style.backgroundColor = '#ffffff'
      probe.style.fontSize = '16px'
      document.body.appendChild(probe)
    })

    const findings = await scanContrast(page, '#contrast-falsification-probe')
    expect(findings).toHaveLength(1)
    expect(findings[0].ratio).toBeLessThan(findings[0].required)

    await page.evaluate(() => {
      document.getElementById('contrast-falsification-probe')?.remove()
    })
  })
})
