export type PublishDashboardState =
  | 'draft'
  | 'preflight_blocked'
  | 'publishing'
  | 'portal_live'
  | 'reach_degraded'
  | 'archive_pending'
  | 'archive_verified'
  | 'complete'
  | 'failed_needs_action'

export type PublishSurfaceKind = 'canonical' | 'archive' | 'reach' | 'record' | 'audience'
export type PublishSurfaceState =
  | 'blocked'
  | 'not_configured'
  | 'coming_soon'
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'overridden'
export type PublishSurfaceApproval = 'pending' | 'approved' | 'overridden'

export interface PublishSurfaceOverride {
  surface_id: string
  justification: string
}

export interface PublishApprovalRequest {
  operator_id: string
  operator_display_name: string
  approved_surface_ids: string[]
  overrides?: PublishSurfaceOverride[]
}

export interface PublishRetryRequest {
  operator_id: string
  operator_display_name: string
}

export interface PublishSurfaceStatus {
  id: string
  label: string
  kind: PublishSurfaceKind
  state: PublishSurfaceState
  approval: PublishSurfaceApproval
  required: boolean
  url: string | null
  path?: string | null
  verification_hash?: string | null
  last_attempt_at: string | null
  completed_at: string | null
  retry_count?: number
  health: 'ok' | 'warning' | 'error' | 'unknown'
  message: string
  next_step: string
  override_justification?: string | null
  /**
   * True when a simulated (mock) provider completed this surface — the default
   * until an admin sets `CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real` /
   * `CIVICCAST_PROVIDER_LOCAL_NAS=real`. The dashboard must badge it: a clerk
   * approving an archive surface has to be able to tell a real archival write
   * from one that never happened (GauntletGate TW-1).
   */
  simulated?: boolean
}

export interface PublishAssetStatus {
  asset_id: string
  title: string
  dashboard_state: PublishDashboardState
  dashboard_label: string
  canonical_public: boolean
  archive_verified: boolean
  reach_degraded: boolean
  needs_operator_action: boolean
  public_record_required: boolean
  published_at: string | null
  surfaces: PublishSurfaceStatus[]
}

export interface PublishDashboardSummary {
  total_assets: number
  draft: number
  portal_live: number
  archive_verified: number
  degraded: number
  needs_operator_action: number
}

export interface PublishDashboardResponse {
  summary: PublishDashboardSummary
  assets: PublishAssetStatus[]
}

// WP-11 item 5: mirrors civiccast/publish/models.py's PublishPreflightCheck
// / PublishPreflightResponse (PR #129), the same shape the generated
// api.generated.ts carries. Hand-curated here (like every other Publish
// type in this file) so the Publish screens can import from one place.
export interface PublishPreflightCheck {
  id: string
  label: string
  kind: PublishSurfaceKind
  required: boolean
  health: 'ok' | 'warning' | 'error' | 'unknown'
  credential_reference?: string | null
  message: string
  next_step: string
}

export interface PublishPreflightResponse {
  asset_id: string
  ready: boolean
  checks: PublishPreflightCheck[]
}
