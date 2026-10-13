export type NetworkMode = 'loopback' | 'caddy'

export interface NetworkSettings {
  mode: NetworkMode
  public_base_url: string | null
  staff_hostname: string | null
  staff_allowed_cidrs: string[]
  caddy_bind_addresses: string[]
  upstream_host: string
  upstream_port: number
}

export interface NetworkSettingsResponse {
  settings: NetworkSettings
  caddyfile: string
  restart_required: boolean
}
