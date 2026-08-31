import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

afterEach(cleanup)

import type { StoreSubmissionMetadata } from '../types/api.generated'
import { NewBuildForm, StoreSubmissionRow } from './AppAdminScreen'

describe('NewBuildForm', () => {
  it('keeps Queue build disabled until both fields are chosen (blank form cannot queue)', () => {
    const onSubmit = vi.fn()
    const { getByText, getByLabelText } = render(<NewBuildForm submitting={false} onSubmit={onSubmit} />)
    const button = getByText('Queue build') as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(onSubmit).not.toHaveBeenCalled()

    fireEvent.change(getByLabelText('Platform target'), { target: { value: 'roku' } })
    expect(button.disabled).toBe(true)
    fireEvent.change(getByLabelText('Tier'), { target: { value: 'branded' } })
    expect(button.disabled).toBe(false)
  })

  it('submits the chosen target + tier only after the confirmation dialog', () => {
    const onSubmit = vi.fn()
    const { getByText, getByRole, getByLabelText } = render(
      <NewBuildForm submitting={false} onSubmit={onSubmit} />,
    )
    fireEvent.change(getByLabelText('Platform target'), { target: { value: 'roku' } })
    fireEvent.change(getByLabelText('Tier'), { target: { value: 'branded' } })
    fireEvent.click(getByText('Queue build'))

    // Dialog open, nothing submitted yet.
    expect(getByRole('alertdialog')).toBeTruthy()
    expect(onSubmit).not.toHaveBeenCalled()

    fireEvent.click(getByRole('alertdialog').querySelector('button:last-child') as HTMLElement)
    expect(onSubmit).toHaveBeenCalledWith({ app_target: 'roku', build_tier: 'branded' })
  })

  it('submits nothing when the dialog is cancelled', () => {
    const onSubmit = vi.fn()
    const { getByText, getByRole, queryByRole, getByLabelText } = render(
      <NewBuildForm submitting={false} onSubmit={onSubmit} />,
    )
    fireEvent.change(getByLabelText('Platform target'), { target: { value: 'roku' } })
    fireEvent.change(getByLabelText('Tier'), { target: { value: 'branded' } })
    fireEvent.click(getByText('Queue build'))
    fireEvent.click(getByRole('button', { name: 'Cancel' }))

    expect(queryByRole('alertdialog')).toBeNull()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

describe('StoreSubmissionRow', () => {
  const SUB: StoreSubmissionMetadata = {
    app_target: 'roku',
    version_code: 1,
    version_name: '0.1.0',
    submission_status: 'draft',
  }

  it('saves status + package + url + version', () => {
    const onSave = vi.fn()
    const { getByText, getByLabelText } = render(
      <StoreSubmissionRow submission={SUB} saving={false} canWrite onSave={onSave} />,
    )
    fireEvent.change(getByLabelText('roku status'), { target: { value: 'published' } })
    fireEvent.change(getByLabelText('roku package'), { target: { value: 'tv.civiccast.roku' } })
    fireEvent.change(getByLabelText('roku url'), { target: { value: 'https://store' } })
    fireEvent.click(getByText('Save'))
    expect(onSave).toHaveBeenCalledWith('roku', {
      submission_status: 'published',
      package_id: 'tv.civiccast.roku',
      published_url: 'https://store',
      version_name: '0.1.0',
    })
  })

  it('hides Save and makes controls read-only when canWrite is false', () => {
    const onSave = vi.fn()
    const { queryByText, getByLabelText } = render(
      <StoreSubmissionRow submission={SUB} saving={false} canWrite={false} onSave={onSave} />,
    )
    expect(queryByText('Save')).toBeNull()
    expect((getByLabelText('roku package') as HTMLInputElement).readOnly).toBe(true)
    expect((getByLabelText('roku status') as HTMLSelectElement).disabled).toBe(true)
  })
})

// --- container role gate (mocked client) ---

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    detail?: string
    constructor(message: string, status = 500, detail?: string) {
      super(message)
      this.status = status
      this.detail = detail
    }
  },
  getStaffIdentity: vi.fn(),
  getAppPlatformConfig: vi.fn(),
  listAppBuilds: vi.fn(),
  listStoreSubmissions: vi.fn(),
  createAppBuild: vi.fn(),
  updateStoreSubmission: vi.fn(),
  downloadAppBuild: vi.fn(),
}))

import type { StaffIdentityResponse } from '../types/api.generated'
import {
  ApiError,
  createAppBuild,
  getAppPlatformConfig,
  getStaffIdentity,
  listAppBuilds,
  listStoreSubmissions,
} from '../api/client'
import { AppAdminScreen } from './AppAdminScreen'

function identity(roles: StaffIdentityResponse['roles']): StaffIdentityResponse {
  return { operator_id: 'op', operator_display_name: 'Op', roles }
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AppAdminScreen />
    </QueryClientProvider>,
  )
}

const _CONFIG = { build_profile: { app_name: 'CivicCast', tier: 'unbranded', store_ready: false } }

describe('AppAdminScreen container role gate', () => {
  it('shows an access note for an operator without an OTT role', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['meeting_operator']))
    const { findByText } = renderScreen()
    expect(await findByText(/requires the setup admin or publish operator role/)).toBeTruthy()
  })

  it('offers New Build to a setup admin', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getAppPlatformConfig).mockResolvedValue(_CONFIG as never)
    vi.mocked(listAppBuilds).mockResolvedValue([])
    vi.mocked(listStoreSubmissions).mockResolvedValue([])
    const { findByText } = renderScreen()
    expect(await findByText('Queue build')).toBeTruthy()
  })

  it('hides queueing from a publish operator (read-only build, can still track)', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['publish_operator']))
    vi.mocked(getAppPlatformConfig).mockResolvedValue(_CONFIG as never)
    vi.mocked(listAppBuilds).mockResolvedValue([])
    vi.mocked(listStoreSubmissions).mockResolvedValue([])
    const { findByText, queryByText } = renderScreen()
    expect(await findByText(/Queueing a build requires the setup admin role/)).toBeTruthy()
    expect(queryByText('Queue build')).toBeNull()
  })

  it('shows readable build-tooling failures from Queue build', async () => {
    vi.mocked(getStaffIdentity).mockResolvedValue(identity(['setup_admin']))
    vi.mocked(getAppPlatformConfig).mockResolvedValue(_CONFIG as never)
    vi.mocked(listAppBuilds).mockResolvedValue([])
    vi.mocked(listStoreSubmissions).mockResolvedValue([])
    vi.mocked(createAppBuild).mockRejectedValue(
      new ApiError(
        'Request failed',
        422,
        'App build tooling is not configured in this runtime. Meeting capture and scheduled recording are unaffected; app-shell builds are optional and require the station app build toolchain.',
      ),
    )
    const { findByText, findByRole, findByLabelText } = renderScreen()
    fireEvent.change(await findByLabelText('Platform target'), { target: { value: 'web_pwa' } })
    fireEvent.change(await findByLabelText('Tier'), { target: { value: 'unbranded' } })
    fireEvent.click(await findByText('Queue build'))
    const dialog = await findByRole('alertdialog')
    fireEvent.click(dialog.querySelector('button:last-child') as HTMLElement)
    expect(await findByText(/App build tooling is not configured/)).toBeTruthy()
    expect(await findByText(/Meeting capture and scheduled recording are unaffected/)).toBeTruthy()
  })
})
