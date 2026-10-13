import { type ReactNode, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AuthRequiredState } from '../components/AuthRequiredState'
import { ApiError, getNetworkSettings, getStaffIdentity, saveNetworkSettings } from '../api/client'
import type { NetworkSettings, NetworkSettingsResponse } from '../types/network'
import { hasRole } from './contribution-format'

const READ_ROLES = ['setup_admin', 'support_admin']
const WRITE_ROLES = ['setup_admin']

const EMPTY_SETTINGS: NetworkSettings = {
  mode: 'loopback',
  public_base_url: null,
  staff_hostname: null,
  staff_allowed_cidrs: [],
  caddy_bind_addresses: [],
  upstream_host: '127.0.0.1',
  upstream_port: 8000,
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail || error.message
  if (error instanceof Error) return error.message
  return 'The request could not be completed.'
}

function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'ok' | 'warn' }) {
  const colors = {
    info: ['var(--cc-info-soft)', 'var(--cc-info)'],
    ok: ['var(--cc-ok-soft)', 'var(--cc-ok)'],
    warn: ['var(--cc-warn-soft)', 'var(--cc-warn)'],
  } as const
  const [background, border] = colors[tone]
  return (
    <div role={tone === 'warn' ? 'alert' : 'status'} className="rounded-md p-3 text-sm" style={{ background, border: `1px solid ${border}` }}>
      {children}
    </div>
  )
}

export function NetworkSettingsScreen() {
  const queryClient = useQueryClient()
  const identityQuery = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity, retry: false })
  const canRead = hasRole(identityQuery.data, READ_ROLES)
  const canWrite = hasRole(identityQuery.data, WRITE_ROLES)
  const settingsQuery = useQuery({
    queryKey: ['network-settings'],
    queryFn: getNetworkSettings,
    retry: false,
    enabled: identityQuery.isSuccess && canRead,
  })
  const [settings, setSettings] = useState<NetworkSettings>(EMPTY_SETTINGS)
  const [cidrText, setCidrText] = useState('')
  const [bindText, setBindText] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const loaded = settingsQuery.data?.settings
    if (loaded) {
      setSettings(loaded)
      setCidrText(loaded.staff_allowed_cidrs.join('\n'))
      setBindText(loaded.caddy_bind_addresses.join('\n'))
    }
  }, [settingsQuery.data])

  const saveMutation = useMutation({
    mutationFn: saveNetworkSettings,
    onSuccess: async (result) => {
      await queryClient.setQueryData<NetworkSettingsResponse>(['network-settings'], result)
      setSettings(result.settings)
      setCidrText(result.settings.staff_allowed_cidrs.join('\n'))
      setBindText(result.settings.caddy_bind_addresses.join('\n'))
    },
  })

  if (identityQuery.isLoading) {
    return <div className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-3)' }}>Loading…</div>
  }
  if (identityQuery.isError) {
    return <div className="px-6 py-10"><AuthRequiredState error={identityQuery.error} /></div>
  }
  if (!canRead) {
    return (
      <div className="px-6 py-10">
        <Notice>Network Settings requires the setup admin or support admin role. Ask your station admin for access.</Notice>
      </div>
    )
  }

  const current = settingsQuery.data
  const caddyfile = current?.caddyfile ?? ''
  const busy = settingsQuery.isLoading || saveMutation.isPending
  const hasChanges = current != null && JSON.stringify(settings) !== JSON.stringify(current.settings)
  const cidrs = cidrText.split(/[\r\n,]+/).map((item) => item.trim()).filter(Boolean)
  const bindAddresses = bindText.split(/[\r\n,]+/).map((item) => item.trim()).filter(Boolean)

  function update<K extends keyof NetworkSettings>(key: K, value: NetworkSettings[K]) {
    setSettings((previous) => ({ ...previous, [key]: value }))
  }

  async function copyCaddyfile() {
    try {
      await navigator.clipboard.writeText(caddyfile)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="space-y-4 px-6 py-6">
      <header className="max-w-3xl space-y-1">
        <h1 className="text-lg font-semibold">Network Settings</h1>
        <p className="text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          Keep the application listener on this computer. For remote access, use the supported Caddy edge with a public resident host and a separate staff host restricted to approved networks.
        </p>
      </header>

      {settingsQuery.isLoading && <p role="status" className="text-sm">Loading network settings…</p>}
      {settingsQuery.isError && <Notice tone="warn">Could not load network settings. {errorMessage(settingsQuery.error)}</Notice>}
      {saveMutation.isError && <Notice tone="warn">Could not save network settings. {errorMessage(saveMutation.error)}</Notice>}
      {saveMutation.isSuccess && !hasChanges && (
        <Notice tone="ok">Settings saved. Restart the CivicCast service before these listener settings take effect.</Notice>
      )}

      {current && (
        <section aria-labelledby="listener-heading" className="max-w-3xl space-y-4 rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
          <div className="space-y-1">
            <h2 id="listener-heading" className="text-sm font-semibold">Application listener</h2>
            <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>CivicCast listens only on a loopback address. It is never bound directly to a LAN or public interface.</p>
          </div>

          <label className="grid max-w-sm gap-1 text-xs">
            <span>Access mode</span>
            <select aria-label="Access mode" value={settings.mode} disabled={!canWrite || busy} onChange={(event) => update('mode', event.target.value as NetworkSettings['mode'])} className="rounded-md px-2 py-2" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}>
              <option value="loopback">This computer only</option>
              <option value="caddy">Caddy HTTPS reverse proxy</option>
            </select>
          </label>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-xs">
              <span>Loopback listener address</span>
              <select aria-label="Loopback listener address" value={settings.upstream_host} disabled={!canWrite || busy} onChange={(event) => update('upstream_host', event.target.value)} className="rounded-md px-2 py-2" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }}>
                <option value="127.0.0.1">127.0.0.1 (IPv4)</option>
                <option value="::1">::1 (IPv6)</option>
              </select>
            </label>
            <label className="grid gap-1 text-xs">
              <span>Listener port</span>
              <input aria-label="Listener port" type="number" min={1024} max={65535} value={settings.upstream_port} disabled={!canWrite || busy} onChange={(event) => update('upstream_port', Number(event.target.value))} className="rounded-md px-2 py-2" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
            </label>
          </div>

          {settings.mode === 'loopback' ? (
            <Notice>The station remains available on this computer only. No proxy configuration is generated.</Notice>
          ) : (
            <div className="space-y-3 rounded-md p-3" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
              <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>Use two DNS names. The public host serves resident pages and media only; the staff host requires an approved source network. First Setup stays on the station computer.</p>
              {settings.staff_hostname && <a className="block text-xs" style={{ color: 'var(--cc-brand)' }} href={`https://${settings.staff_hostname}/operator/#/login`}>Staff sign-in: https://{settings.staff_hostname}/operator/#/login</a>}
              <label className="grid gap-1 text-xs">
                <span>Public HTTPS URL</span>
                <input aria-label="Public HTTPS URL" type="url" placeholder="https://watch.example.gov" value={settings.public_base_url ?? ''} disabled={!canWrite || busy} onChange={(event) => update('public_base_url', event.target.value || null)} className="rounded-md px-2 py-2" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
              </label>
              <label className="grid gap-1 text-xs">
                <span>Staff HTTPS hostname</span>
                <input aria-label="Staff HTTPS hostname" type="text" placeholder="staff.example.gov" value={settings.staff_hostname ?? ''} disabled={!canWrite || busy} onChange={(event) => update('staff_hostname', event.target.value || null)} className="rounded-md px-2 py-2" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
              </label>
              <label className="grid gap-1 text-xs">
                <span>Staff network CIDRs</span>
                <textarea aria-label="Staff network CIDRs" rows={3} placeholder={'192.168.50.0/24\n2001:db8:50::/64'} value={cidrText} disabled={!canWrite || busy} onChange={(event) => { setCidrText(event.target.value); update('staff_allowed_cidrs', event.target.value.split(/[\r\n,]+/).map((item) => item.trim()).filter(Boolean)) }} className="rounded-md px-2 py-2 font-mono text-xs" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
                <span style={{ color: 'var(--cc-ink-3)' }}>Enter the source networks allowed to reach the staff hostname, one CIDR per line.</span>
              </label>
              <label className="grid gap-1 text-xs">
                <span>Caddy listener IP addresses (optional)</span>
                <textarea aria-label="Caddy listener IP addresses" rows={2} placeholder={'192.168.50.10\n2001:db8:50::10'} value={bindText} disabled={!canWrite || busy} onChange={(event) => { setBindText(event.target.value); update('caddy_bind_addresses', event.target.value.split(/[\r\n,]+/).map((item) => item.trim()).filter(Boolean)) }} className="rounded-md px-2 py-2 font-mono text-xs" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
                <span style={{ color: 'var(--cc-ink-3)' }}>One assigned, non-loopback interface IP per line. Leave blank to let Caddy bind all available interfaces.</span>
              </label>
              <Notice tone="warn">Caddy must be directly reachable from clients. Do not place an untrusted CDN or reverse proxy in front; the generated staff network check relies on the direct client address.</Notice>
            </div>
          )}

          {canWrite && (
            <div className="flex justify-end">
              <button type="button" aria-label="Save network settings" disabled={!hasChanges || busy} onClick={() => saveMutation.mutate({ ...settings, public_base_url: settings.mode === 'caddy' ? settings.public_base_url : null, staff_hostname: settings.mode === 'caddy' ? settings.staff_hostname : null, staff_allowed_cidrs: settings.mode === 'caddy' ? cidrs : [], caddy_bind_addresses: settings.mode === 'caddy' ? bindAddresses : [] })} className="rounded-md px-3 py-1.5 font-semibold disabled:opacity-50" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
                {saveMutation.isPending ? 'Saving…' : 'Save network settings'}
              </button>
            </div>
          )}
          {!canWrite && <p className="text-xs" style={{ color: 'var(--cc-ink-3)' }}>Read-only. Only the setup admin can change network settings.</p>}
          {current.restart_required && <Notice tone="warn">Saved settings differ from the running process. Restart the CivicCast service to apply the listener and public URL.</Notice>}
        </section>
      )}

      {settings.mode === 'caddy' && current?.caddyfile && (
        <section aria-labelledby="caddy-heading" className="max-w-3xl space-y-2 rounded-md p-4" style={{ background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="caddy-heading" className="text-sm font-semibold">Generated Caddy configuration</h2>
            <div className="flex gap-2">
              <button type="button" onClick={copyCaddyfile} className="rounded-md px-3 py-1.5 text-xs font-semibold" style={{ border: '1px solid var(--cc-line)' }}>{copied ? 'Copied' : 'Copy Caddyfile'}</button>
              <a download="Caddyfile" href={`data:text/plain;charset=utf-8,${encodeURIComponent(current.caddyfile)}`} className="rounded-md px-3 py-1.5 text-xs font-semibold" style={{ border: '1px solid var(--cc-line)', color: 'var(--cc-brand)' }}>Download Caddyfile</a>
            </div>
          </div>
          <p className="text-xs" style={{ color: 'var(--cc-ink-2)' }}>Review and deploy this file on the station computer using the network access guide. CivicCast does not open firewall ports or start a proxy when you save settings.</p>
          <textarea aria-label="Generated Caddy configuration" readOnly rows={16} value={caddyfile} className="w-full rounded-md px-3 py-2 font-mono text-xs" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)', color: 'var(--cc-ink)' }} />
        </section>
      )}
    </div>
  )
}
