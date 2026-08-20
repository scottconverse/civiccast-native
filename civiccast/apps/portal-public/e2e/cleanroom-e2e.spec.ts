import { test, expect } from '@playwright/test'

const cleanroomManifestPath =
  process.env.CLEANROOM_MANIFEST_PATH ?? '/cleanroom-asset/playlist.m3u8'

/**
 * Cleanroom end-to-end smoke test.
 *
 * Tagged @cleanroom and run by docker/run-cleanroom.sh. The runner
 * encodes a sample source into an HLS tree, points this spec at that
 * manifest, and asserts hls.js attaches and the player reaches a playable
 * readyState. Gate 6 uses a packaged VOD asset; Gate 8 sets
 * CLEANROOM_MANIFEST_PATH to a synthetic RTMP live-source HLS manifest.
 *
 * NOT part of npm run test:a11y — the asset is only present inside
 * the cleanroom workdir.
 */

test.describe('@cleanroom packager-to-portal end-to-end', () => {
  test('locally-encoded asset plays through hls.js to readyState>=3', async ({
    page,
  }) => {
    const manifestResponse = page.waitForResponse((response) =>
      response.url().includes(cleanroomManifestPath),
    )

    await page.goto(`/?manifest=${encodeURIComponent(cleanroomManifestPath)}`)
    expect((await manifestResponse).ok()).toBe(true)

    // Wait for hls.js to parse the manifest, attach the variant, and buffer
    // enough to be playable. Real-world encode + parse + first-segment fetch
    // takes a couple seconds even on a fast box; 15s is generous.
    await page.waitForFunction(
      () => {
        const v = document.querySelector('video') as HTMLVideoElement | null
        return !!v && v.readyState >= 3 && !v.error
      },
      undefined,
      { timeout: 15_000 },
    )

    const state = await page.evaluate(() => {
      const v = document.querySelector('video') as HTMLVideoElement
      return {
        src: v.currentSrc || v.src,
        readyState: v.readyState,
        duration: v.duration,
        videoWidth: v.videoWidth,
        videoHeight: v.videoHeight,
        error: v.error?.message ?? null,
      }
    })

    expect(state.error).toBeNull()
    expect(state.readyState).toBeGreaterThanOrEqual(3)
    expect(state.videoWidth).toBeGreaterThan(0)
    expect(state.videoHeight).toBeGreaterThan(0)
    // VOD manifests are finite; the synthetic Gate 8 live manifest reports
    // Infinity. In both cases the strict contract is playable video data.
    if (Number.isFinite(state.duration)) {
      expect(state.duration).toBeGreaterThan(0.5)
      expect(state.duration).toBeLessThan(60)
    } else {
      expect(state.duration).toBe(Infinity)
    }
  })

  test('@cleanroom no console errors during playback', async ({ page }) => {
    // Stage G portal analytics is fail-soft by design, but the browser
    // still logs the 404 against the cleanroom's static server. Accept the
    // events like a configured station so this gate stays about PLAYBACK
    // errors (same posture as the operator real-boundary smoke).
    await page.route('**/api/public/app/analytics/events', async (route) => {
      await route.fulfill({ status: 202, contentType: 'application/json', body: '{}' })
    })
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text())
    })
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto(`/?manifest=${encodeURIComponent(cleanroomManifestPath)}`)
    await page.waitForFunction(
      () => {
        const v = document.querySelector('video') as HTMLVideoElement | null
        return !!v && v.readyState >= 3
      },
      undefined,
      { timeout: 15_000 },
    )

    expect(errors).toEqual([])
  })
})
