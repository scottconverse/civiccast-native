import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { getStaffIdentity } from '../api/client'
import {
  getFederationCatalog, getFederationChannels, listFederationStations, queueFederationCommand,
  type FederationAction, type FederationStation,
} from '../api/federation'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { manualLink } from './manual-link'

const readRoles = ['setup_admin', 'meeting_operator', 'support_admin', 'publish_operator']
const buttonClass = 'rounded-md border px-3 py-2 text-sm disabled:opacity-50'
const panelStyle = { background: 'var(--cc-surface)', border: '1px solid var(--cc-line)' }

function LoadError({ subject, retry }: { subject: string; retry: () => void }) {
  return <div role="alert" className="grid gap-2 rounded-md p-3" style={{ background: 'var(--cc-err-soft)' }}>
    <p>Could not load {subject}.</p>
    <button type="button" className={buttonClass} onClick={retry}>Retry {subject}</button>
  </div>
}

function publicLink(url: string, origin: string): string | null {
  try {
    const target = new URL(url)
    const configured = new URL(origin)
    return target.protocol === 'https:' && !target.username && !target.password && target.origin === configured.origin ? target.href : null
  } catch { return null }
}
function dateLabel(value: string | null) {
  if (!value) return 'No status reported'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'Date unavailable' : parsed.toLocaleString()
}

function StationPanel({ station, canControl }: { station: FederationStation; canControl: boolean }) {
  const catalog = useQuery({ queryKey: ['federation-catalog', station.station_id], queryFn: () => getFederationCatalog(station.station_id) })
  const channels = useQuery({ queryKey: ['federation-channels', station.station_id], queryFn: () => getFederationChannels(station.station_id), enabled: station.control_configured })
  const [pending, setPending] = useState<{ channel: string; action: FederationAction } | null>(null)
  const command = useMutation({
    mutationFn: ({ channel, action }: { channel: string; action: FederationAction }) => queueFederationCommand(station.station_id, channel, action),
    onSuccess: () => setPending(null),
    onError: () => setPending(null),
  })
  return <div className="grid gap-6">
    <section className="grid gap-3 rounded-md p-4" style={panelStyle} aria-labelledby="station-catalog-title">
      <h2 id="station-catalog-title" className="text-lg font-semibold">Published programs at {station.label}</h2>
      {catalog.isPending && <p>Loading published programs…</p>}
      {catalog.isError && <LoadError subject="published programs" retry={() => void catalog.refetch()} />}
      {catalog.data && <>
        {catalog.data.items.length === 0 && <p>No published programs are available.</p>}
        <ul className="grid gap-3">{catalog.data.items.map(item => {
          const href = publicLink(item.portal_url, station.public_origin)
          return <li key={item.asset_id} className="grid gap-1 border-b pb-3" style={{ borderColor: 'var(--cc-line)' }}>
            <h3 className="font-semibold">{item.title}</h3>
            <p className="text-sm" style={{ color: 'var(--cc-ink-2)' }}>Published {dateLabel(item.published_at)}{item.duration_seconds !== null && ` · ${Math.round(item.duration_seconds / 60)} min`}</p>
            {href ? <a className="w-fit underline" href={href} target="_blank" rel="noopener noreferrer" aria-label={`Watch ${item.title} at ${station.label}`}>Watch on {station.label} ↗</a> : <p>Public playback link unavailable.</p>}
          </li>
        })}</ul>
        {catalog.data.truncated && <p className="text-sm">This is a limited list of published programs. Visit the station’s public portal for more.</p>}
      </>}
    </section>
    <section className="grid gap-3 rounded-md p-4" style={panelStyle} aria-labelledby="station-channels-title">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="station-channels-title" className="text-lg font-semibold">Channels at {station.label}</h2>
        {station.control_configured && <button type="button" className={buttonClass} disabled={channels.isFetching} onClick={() => void channels.refetch()}>Refresh channel status</button>}
      </div>
      {!station.control_configured ? <p>Channel status and control are not configured for this station.</p> : <>
        {channels.isPending && <p>Loading channel status…</p>}
        {channels.isError && <LoadError subject="channel status" retry={() => void channels.refetch()} />}
        {channels.data?.channels.length === 0 && <p>No shared channels are configured.</p>}
        {channels.data?.channels.map(channel => <div key={channel.channel_id} className="grid gap-2 border-b pb-3" style={{ borderColor: 'var(--cc-line)' }}>
          <h3 className="font-semibold">{channel.channel_id}</h3>
          <dl className="grid gap-1 text-sm">
            <div><dt className="inline">State: </dt><dd className="inline">{channel.state ?? 'No status reported'}</dd></div>
            <div><dt className="inline">Channel enabled: </dt><dd className="inline">{channel.enabled ? 'Yes' : 'No'}</dd></div>
            <div><dt className="inline">Current program: </dt><dd className="inline">{channel.current_source_label ?? 'No program reported'}</dd></div>
            <div><dt className="inline">Last health report: </dt><dd className="inline">{dateLabel(channel.last_health_at)}</dd></div>
          </dl>
          {canControl && <div className="flex gap-2">{(['start', 'stop'] as const).map(action => <button key={action} type="button" className={buttonClass} disabled={command.isPending} aria-label={`${action === 'start' ? 'Start' : 'Stop'} ${channel.channel_id}`} onClick={() => { command.reset(); setPending({ channel: channel.channel_id, action }) }}>{action === 'start' ? 'Start' : 'Stop'}</button>)}</div>}
        </div>)}
        {!canControl && <p className="text-sm">Starting and stopping channels requires a setup administrator or meeting operator.</p>}
      </>}
      {command.isSuccess && <p role="status">Command {command.data.command_id} queued on {station.label}. Refresh status to confirm execution.</p>}
      {command.isError && <p role="alert">Could not queue the command. Refresh channel status before trying again.</p>}
    </section>
    {pending && <ConfirmDialog
      title={`${pending.action === 'start' ? 'Start' : 'Stop'} ${pending.channel} at ${station.label}?`}
      body={pending.action === 'stop' ? 'This requests a stop on the remote station and may interrupt its on-air stream. The command is queued; check channel status to confirm what happened.' : 'This requests a start on the remote station and may put its configured program on air. The command is queued; check channel status to confirm what happened.'}
      confirmLabel={`Confirm ${pending.action}`} tone={pending.action === 'stop' ? 'danger' : 'brand'} busy={command.isPending}
      onCancel={() => { if (!command.isPending) setPending(null) }}
      onConfirm={() => { if (!command.isPending) command.mutate(pending) }}
    />}
  </div>
}

function Stations({ canControl }: { canControl: boolean }) {
  const stations = useQuery({ queryKey: ['federation-stations'], queryFn: listFederationStations })
  const [selectedId, setSelectedId] = useState('')
  const selected = stations.data?.find(station => station.station_id === selectedId) ?? stations.data?.[0]
  if (stations.isPending) return <p>Loading other stations…</p>
  if (stations.isError) return <LoadError subject="other stations" retry={() => void stations.refetch()} />
  if (!selected) return <p>No other stations are configured. A setup administrator can configure trusted station connections in the service settings.</p>
  return <div className="grid gap-4">
    <label className="grid max-w-lg gap-1">Other station
      <select className="rounded-md border p-2" style={panelStyle} value={selected.station_id} onChange={event => setSelectedId(event.target.value)}>
        {stations.data.map(station => <option value={station.station_id} key={station.station_id}>{station.label}</option>)}
      </select>
    </label>
    <StationPanel key={selected.station_id} station={selected} canControl={canControl} />
  </div>
}

export function StationFederationScreen() {
  const identity = useQuery({ queryKey: ['staff-identity'], queryFn: getStaffIdentity })
  const roles = identity.data?.roles ?? []
  return <div className="grid gap-5 p-6">
    <header className="grid gap-2"><h1 className="text-2xl font-semibold">Other stations</h1>
      <p>Browse published programs and check channels at trusted stations configured by your administrator.</p>
      <Link className="w-fit text-sm underline" to={manualLink('station-federation')}>Station connections help</Link>
    </header>
    {identity.isPending ? <p>Checking staff access…</p> : identity.isError ? <LoadError subject="staff access" retry={() => void identity.refetch()} /> :
      roles.some(role => readRoles.includes(role)) ? <Stations canControl={roles.some(role => role === 'setup_admin' || role === 'meeting_operator')} /> : <p>Your staff role does not allow access to other stations.</p>}
  </div>
}
