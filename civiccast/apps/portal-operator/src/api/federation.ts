import { staffApiRequest } from './client'

export interface FederationStation {
  station_id: string
  label: string
  public_origin: string
  channel_ids: string[]
  control_configured: boolean
}
export interface FederationCatalog {
  station_id: string
  items: { asset_id: string; title: string; duration_seconds: number | null; published_at: string; portal_url: string }[]
  truncated: boolean
}
export interface FederationChannels {
  station_id: string
  channels: { channel_id: string; enabled: boolean; state: string | null; current_source_label: string | null; last_health_at: string | null }[]
}
export type FederationAction = 'start' | 'stop'
export interface FederationCommandReceipt {
  station_id: string
  channel_id: string
  action: FederationAction
  command_id: string
  queued: true
  message: string
}
const stationPath = (id: string) => `/api/staff/federation/stations/${encodeURIComponent(id)}`
export const listFederationStations = () => staffApiRequest<FederationStation[]>('/api/staff/federation/stations')
export const getFederationCatalog = (id: string) => staffApiRequest<FederationCatalog>(`${stationPath(id)}/catalog`)
export const getFederationChannels = (id: string) => staffApiRequest<FederationChannels>(`${stationPath(id)}/channels`)
export function queueFederationCommand(id: string, channel: string, action: FederationAction) {
  return staffApiRequest<FederationCommandReceipt>(`${stationPath(id)}/channels/${encodeURIComponent(channel)}/commands`, {
    method: 'POST', body: { action, ...(action === 'stop' ? { confirm_stop: true } : {}) },
  })
}
