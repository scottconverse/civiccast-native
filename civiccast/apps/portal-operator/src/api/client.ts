import type { AssetMetadataUpdate, AssetRow } from '../types/asset'
import type {
  ActivityPubDeliveriesResponse,
  ActivityPubDeliveryRetriesResponse,
  ActivityPubFollowersResponse,
  ActivityPubModerationResponse,
  ActivityPubOutboxResponse,
  ActivityPubStatusResponse,
  AiModelAvailability,
  AiModelConfiguration,
  FeatureModelRegistry,
  ModelSelectionRequest,
  AlertChannel,
  AlertChannelInput,
  AlertEvent,
  AlertRule,
  AlertRuleUpdate,
  AnalyticsReport,
  BackupSetupRequest,
  BackupStatus,
  BulletinCreate,
  BulletinUpdate,
  CgBulletinQueue,
  CgBulletinSubmission,
  BoardView,
  CgBoard,
  CgBoardAuditEvent,
  CgFeedItem,
  CgFeedItemApproval,
  CgFeedSource,
  CgZoneConfig,
  FeedInput,
  FeedUpdateInput,
  ResolvedBoard,
  ZoneInput,
  ZoneUpdateInput,
  ChannelLogEntry,
  CommitRequest,
  CommitToAirPlan,
  CommitToAirReport,
  HandbackRequest,
  ManualRouteState,
  PrepareCommitRequest,
  RollbackRequest,
  TakeoverRequest,
  TakeoverSession,
  CaptionStatusResponse,
  ChannelLoudnessPlan,
  ComplianceProbeResult,
  EgressCaptionProofSample,
  EgressConfig,
  GstreamerRepairResponse,
  OfflineCaptionJobRecord,
  HeadendProfile,
  HeadendProfileApplyRequest,
  MaterializeResult,
  ProgramSlot,
  ProgramSlotCreate,
  SlotOccurrence,
  ChannelBrandingUpdate,
  ChannelNowNext,
  ChannelPlayoutPlan,
  ChannelProfile,
  ChannelProofLog,
  ChannelPublicConfig,
  CgPortalDisplay,
  ContributorNotificationOutbox,
  ContributorReviewQueue,
  ContributorReviewRequest,
  ContributorSubmission,
  CtvFeed,
  DiagnosticBundleRequest,
  DiagnosticBundleResponse,
  FirstAdminSetupRequest,
  FirstAdminSetupResponse,
  HandoffRecoveryCompleteRequest,
  HandoffRecoveryCompleteResponse,
  HandoffRecoveryStartResponse,
  FollowerModerationRequest,
  DeliveryRetryRecord,
  FollowerRecord,
  LiveFinalizationStatusResponse,
  ManagedStorageStatus,
  OverlayCompositorPlan,
  OverlayCompositorRequest,
  PlaybackPolicyAuditLog,
  PlaybackPolicyConfig,
  PlaybackPolicyUpdate,
  ProducerActivityReport,
  ProviderCredentialSetupRequest,
  ProviderConnectionTestResponse,
  ProviderCredentialSetupResponse,
  ProviderKeyRequest,
  ProviderKeyStatus,
  ProviderProofRecordRequest,
  ProviderProofRecordResponse,
  ProviderReadinessReport,
  R2ConciergeRequest,
  R2ConciergeResponse,
  RehearsalReport,
  RecordExportApiRequest,
  RecordExportResponse,
  ResidentPreview,
  RestoreStatus,
  DrillReport,
  RouterInventory,
  RouterScheduledTakePlan,
  RouterScheduledTakePreviewRequest,
  RouterTakePlan,
  RouterTakePreviewRequest,
  RollbackArtifactRequest,
  RuntimeSafeToAirStatus,
  SampleSeedStatus,
  SourceSetupCreateRequest,
  SourceSetupMutationResponse,
  SourceSetupReport,
  SourceSetupSampleUploadResponse,
  StaffEgressChannelSummary,
  StaffIdentityResponse,
  StationAppConfig,
  StationAppConfigUpdate,
  AppBuildRecord,
  BuildRequest,
  StoreSubmissionMetadata,
  StoreSubmissionUpdate,
  StationAuthResponse,
  StationLoginRequest,
  StationRecoveryRequest,
  StationSetupState,
  SummaryApprovalRequest,
  SummaryDraft,
  SummaryReviewQueueResponse,
  SystemHealthReport,
  SystemResourceSample,
  SystemSelfTest,
  TsduckInstallReport,
  TsduckStatus,
  UpdateRollbackStatus,
  UploadedAssetResponse,
  VirtualRouterPanel,
  SavedSearch,
  SavedSearchInput,
  ScheduleBlock,
  ScheduleBlockInput,
  AutoScheduleRule,
  AutoScheduleRuleInput,
  RulePreview,
  CompileReport,
} from '../types/api.generated'
import type {
  AgendaItem,
  AgendaItemInput,
  AgendaItemUpdate,
  AsRunReport,
  AudioProgramTrack,
  AudioTrackInput,
  ControlRoomReadinessReport,
  ControlRoomSession,
  ControlSurface,
  ControlSurfaceInput,
  CueFiredEvent,
  CuePlan,
  FireCueInput,
  CustomFieldDef,
  CustomFieldDefInput,
  CustomFieldDefUpdate,
  CustomFieldValue,
  AssetCustomFieldsUpdate,
  EpgExportConfig,
  EpgExportConfigInput,
  EpgExportConfigUpdate,
  EpgGenerateResult,
  HoursByCategoryReport,
  MeetingAgenda,
  MeetingAgendaInput,
  MeetingAgendaUpdate,
  ShowsReport,
  SpotFlight,
  SpotFlightInput,
  SpotFlightUpdate,
  SpotPlacement,
  UnderwriterAffidavit,
  UnderwritingSpot,
  UnderwritingSpotInput,
  UnderwritingSpotUpdate,
  DeviceProfile,
  DeviceProfileInput,
  DisplayInput,
  EasCapAlert,
  EasCapSource,
  EasDisplayDecision,
  ManualAlertInput,
  ProductionDevice,
  ProductionDeviceInput,
  SessionOpenInput,
  SourceInput,
  SurfaceDetail,
  TimelineCue,
  TimelineCueInput,
  TsrProbeResult,
} from '../types/api.generated'
import type {
  ContributionRoom,
  CreateRoomInput,
  GuestInvite,
  MintInviteInput,
  RemoteGuestSession,
  RoomDetail,
  RoomOpened,
  VdoDiagnostics,
} from '../types/api.generated'
import type {
  CaptionReviewDecision,
  CaptionReviewEdit,
  CaptionReviewItemResponse,
  CaptionReviewStatus,
} from '../types/captions'
import type {
  LiveSessionCreate,
  LiveSessionResponse,
  LiveIngestPlan,
  LiveRelayConfigResponse,
  LiveSourceResponse,
  PreflightEvaluation,
  PreflightInputs,
  RecordingTargetResponse,
} from '../types/live'
import type {
  PublishApprovalRequest,
  PublishAssetStatus,
  PublishDashboardResponse,
  PublishRetryRequest,
} from '../types/publish'
import type {
  ScheduleConflictDetail,
  ScheduleItem,
  ScheduleItemCreate,
  ScheduleState,
} from '../types/schedule'

declare global {
  interface Window {
    __CIVICCAST_API_BASE__?: string
    __CIVICCAST_STAFF_TOKEN__?: string
  }
}

function runtimeApiBase(): string {
  if (typeof window === 'undefined') return ''
  return (window.__CIVICCAST_API_BASE__ ?? '').replace(/\/$/, '')
}

function runtimeStaffToken(): string | null {
  if (typeof window === 'undefined') return null
  const localToken = window.localStorage.getItem('civiccast.staffToken')
  const sessionToken = window.sessionStorage.getItem('civiccast.staffToken')
  const injectedToken = window.__CIVICCAST_STAFF_TOKEN__
  return (
    localToken ??
    sessionToken ??
    injectedToken ??
    null
  )
}

/**
 * Whether this browser holds the installer's one-time setup handoff.
 *
 * Every `/api/setup/*` mutation is 403 without it (GauntletGate W-2), so a
 * screen that offers such an action must ask this first rather than presenting
 * a control that cannot succeed.
 */
export function hasSetupNonce(): boolean {
  return runtimeSetupNonce() !== null
}

function runtimeSetupNonce(): string | null {
  if (typeof window === 'undefined') return null
  const hash = window.location.hash
  const hashQuery = hash.includes('?') ? hash.slice(hash.indexOf('?')) : ''
  const urlNonce =
    new URLSearchParams(window.location.search).get('nonce') ??
    new URLSearchParams(hashQuery).get('nonce')
  return urlNonce ?? window.sessionStorage.getItem('civiccast.setupNonce')
}

function userFacingApiDetail(detail?: string): string | undefined {
  if (!detail) return detail
  const normalized = detail.toLowerCase()
  if (normalized.includes('missing authorization header') || normalized.includes('bearer <staff-token>')) {
    return 'Sign in with the local station admin account, then try again.'
  }
  if (normalized.includes('setup nonce') || normalized.includes('x-civiccast-setup-nonce')) {
    return 'Open the operator console from the CivicCast installer handoff, then continue setup.'
  }
  return detail
}

export class ApiError extends Error {
  status: number
  detail?: string
  conflict?: ScheduleConflictDetail
  retryAfterSeconds?: number

  constructor(
    message: string,
    status: number,
    detail?: string,
    conflict?: ScheduleConflictDetail,
    retryAfterSeconds?: number,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    const userDetail = userFacingApiDetail(detail)
    this.detail =
      status === 429 &&
      retryAfterSeconds != null &&
      userDetail?.toLowerCase().includes('staff authentication')
        ? `Too many unsuccessful sign-in attempts from this network. Wait ${retryAfterSeconds} ${retryAfterSeconds === 1 ? 'second' : 'seconds'}, then try again.`
        : userDetail
    this.conflict = conflict
    this.retryAfterSeconds = retryAfterSeconds
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  /** Abort the request after this many ms (e.g. the multi-minute TSDuck install). */
  timeoutMs?: number
}

function responseRetryAfterSeconds(response: Response): number | undefined {
  const raw = response.headers.get('Retry-After')
  const parsed = raw == null ? Number.NaN : Number(raw)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
}

export type EgressCommandAction = 'start' | 'stop' | 'reload' | 'drain'

export interface EgressCommand {
  channel_id: string
  action: EgressCommandAction
  issued_at: string
  issued_by: string
  command_id: string
}

export interface EgressCommandResponse {
  command: EgressCommand
  queued: boolean
}

export interface EgressStateRow {
  channel_id: string
  state: 'STOPPED' | 'STARTING' | 'ON_AIR' | 'TRANSITIONING' | 'FALLBACK_SLATE' | 'DRAINING' | 'STOPPING' | 'ERROR'
  current_source_label?: string | null
  current_proof_event_id?: string | null
  updated_at: string
  pid?: number | null
  last_error?: string | null
}

export interface EgressHealthSample {
  channel_id: string
  sampled_at: string
  state: EgressStateRow['state']
  sink_connected: Record<string, boolean>
  encoder_fps?: number | null
  encoder_bitrate_kbps?: number | null
  dropped_frames: number
  seconds_on_air: number
  last_loudness_lufs?: number | null
  caption_status?: 'not-verified' | 'on'
  // S9: schema-currency stamp + proof-event churn rate (operator visibility).
  schema_version?: number
  proof_events_appended_since_last_sample?: number
}

// Mirrors the generated contract (src/types/api.generated.ts) — kept hand-written here
// for the same reason every type in this client surface is. Optionality MUST match the
// OpenAPI shape: proof_events_appended_since_last_sample has a server default, so it is
// optional on the wire (do not mark it required).
export interface EgressSchemaCurrency {
  channel_id: string
  current_schema_version: number
  sample_schema_version?: number | null
  is_current: boolean
  proof_events_appended_since_last_sample?: number
  latest_sampled_at?: string | null
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, timeoutMs } = opts
  const staffToken = runtimeStaffToken()
  const setupNonce = runtimeSetupNonce()

  if (setupNonce && typeof window !== 'undefined') {
    window.sessionStorage.setItem('civiccast.setupNonce', setupNonce)
  }

  const controller = timeoutMs != null ? new AbortController() : undefined
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : undefined
  let res: Response
  try {
    res = await fetch(`${runtimeApiBase()}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(staffToken ? { Authorization: `Bearer ${staffToken}` } : {}),
        ...(setupNonce ? { 'X-CivicCast-Setup-Nonce': setupNonce } : {}),
        ...(body != null ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body != null ? JSON.stringify(body) : undefined,
      signal: controller?.signal,
    })
  } catch (err) {
    if (controller?.signal.aborted) {
      throw new ApiError(
        'The request timed out; it may still be completing on the server. Re-check status.',
        408,
      )
    }
    throw err
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
  if (!res.ok) {
    let detailString: string | undefined
    let conflict: ScheduleConflictDetail | undefined
    const retryAfterSeconds = responseRetryAfterSeconds(res)
    try {
      const parsed = (await res.json()) as { detail?: unknown }
      const raw = parsed?.detail
      if (typeof raw === 'string') {
        detailString = raw
      } else if (raw && typeof raw === 'object') {
        // Conflict shape: { detail: { message, conflicting_item } }
        const obj = raw as Partial<ScheduleConflictDetail>
        if (
          typeof obj.message === 'string' &&
          obj.conflicting_item &&
          typeof obj.conflicting_item === 'object'
        ) {
          conflict = obj as ScheduleConflictDetail
          detailString = obj.message
        } else {
          detailString = JSON.stringify(raw)
        }
      }
    } catch {
      // non-JSON body — leave detail undefined
    }
    throw new ApiError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      detailString,
      conflict,
      retryAfterSeconds,
    )
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const staffToken = runtimeStaffToken()
  const setupNonce = runtimeSetupNonce()

  if (setupNonce && typeof window !== 'undefined') {
    window.sessionStorage.setItem('civiccast.setupNonce', setupNonce)
  }

  const res = await fetch(`${runtimeApiBase()}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      ...(staffToken ? { Authorization: `Bearer ${staffToken}` } : {}),
      ...(setupNonce ? { 'X-CivicCast-Setup-Nonce': setupNonce } : {}),
    },
    body,
  })
  if (!res.ok) {
    let detailString: string | undefined
    try {
      const parsed = (await res.json()) as { detail?: unknown }
      const raw = parsed?.detail
      detailString = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : undefined
    } catch {
      // non-JSON body - leave detail undefined
    }
    throw new ApiError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      detailString,
      undefined,
      responseRetryAfterSeconds(res),
    )
  }
  return (await res.json()) as T
}

export function listStaffAssets(): Promise<AssetRow[]> {
  return request<AssetRow[]>('/api/staff/assets')
}

export function getCivicCastVersion(): Promise<{ version: string }> {
  return request<{ version: string }>('/api/version')
}

export function getStationSetupState(): Promise<StationSetupState> {
  return request<StationSetupState>('/api/setup/station-state')
}

export function getPublicStorageState(): Promise<ManagedStorageStatus> {
  return request<ManagedStorageStatus>('/api/setup/storage')
}

export function preparePublicStorage(): Promise<ManagedStorageStatus> {
  return request<ManagedStorageStatus>('/api/setup/storage', {
    method: 'POST',
    body: {},
  })
}

export function completePublicFirstAdminSetup(
  payload: FirstAdminSetupRequest,
): Promise<FirstAdminSetupResponse> {
  return request<FirstAdminSetupResponse>('/api/setup/first-admin', {
    method: 'POST',
    body: payload,
  })
}

export function acknowledgeRecoveryKit(): Promise<StationSetupState> {
  return request<StationSetupState>('/api/setup/recovery-kit/acknowledge', {
    method: 'POST',
    body: { confirmed: true },
  })
}

export function loginStationAdmin(
  payload: StationLoginRequest,
): Promise<StationAuthResponse> {
  return request<StationAuthResponse>('/api/setup/login', {
    method: 'POST',
    body: payload,
  })
}

export function recoverStationAdmin(
  payload: StationRecoveryRequest,
): Promise<StationAuthResponse> {
  return request<StationAuthResponse>('/api/setup/recover', {
    method: 'POST',
    body: payload,
  })
}

/**
 * W-2: issue a local-admin setup-recovery code for a lost or expired setup
 * link. Never receives the code itself -- only the file path an
 * administrator of this computer can open to read it.
 */
export function startHandoffRecovery(): Promise<HandoffRecoveryStartResponse> {
  return request<HandoffRecoveryStartResponse>('/api/setup/handoff-recovery/start', {
    method: 'POST',
    body: {},
  })
}

/**
 * W-2: redeem the code an administrator read from that file. On success the
 * response carries the station's own setup nonce -- store it exactly where
 * a nonce read from the handoff URL is stored (`civiccast.setupNonce`) so
 * every following `/api/setup/*` call resumes through the ordinary
 * nonce-header path.
 */
export function completeHandoffRecovery(
  payload: HandoffRecoveryCompleteRequest,
): Promise<HandoffRecoveryCompleteResponse> {
  return request<HandoffRecoveryCompleteResponse>('/api/setup/handoff-recovery/complete', {
    method: 'POST',
    body: payload,
  })
}

export function getSystemHealth(): Promise<SystemHealthReport> {
  return request<SystemHealthReport>('/api/staff/installer/system-health')
}

export function getSampleSeedStatus(): Promise<SampleSeedStatus> {
  return request<SampleSeedStatus>('/api/staff/installer/sample-seed-status')
}

export function dismissSampleSeedStatus(): Promise<SampleSeedStatus> {
  return request<SampleSeedStatus>('/api/staff/installer/sample-seed-status/dismiss', {
    method: 'POST',
  })
}

export function retrySampleSeedStatus(): Promise<SampleSeedStatus> {
  return request<SampleSeedStatus>('/api/staff/installer/sample-seed-status/retry', {
    method: 'POST',
  })
}

export function getSafeToBroadcast(): Promise<SystemHealthReport> {
  return request<SystemHealthReport>('/api/staff/installer/safe-to-broadcast')
}

export function getStaffIdentity(): Promise<StaffIdentityResponse> {
  return request<StaffIdentityResponse>('/api/staff/auth/me')
}

export function startFirstBroadcastRehearsal(): Promise<RehearsalReport> {
  return request<RehearsalReport>('/api/staff/installer/rehearsal', {
    method: 'POST',
  })
}

export function getResidentPreview(): Promise<ResidentPreview> {
  return request<ResidentPreview>('/api/staff/installer/resident-preview')
}

export function getProviderReadiness(): Promise<ProviderReadinessReport> {
  return request<ProviderReadinessReport>('/api/staff/installer/provider-readiness')
}

export function saveProviderCredentials(
  payload: ProviderCredentialSetupRequest,
): Promise<ProviderCredentialSetupResponse> {
  return request<ProviderCredentialSetupResponse>('/api/staff/installer/provider-credentials', {
    method: 'POST',
    body: payload,
  })
}

export function recordProviderProof(
  payload: ProviderProofRecordRequest,
): Promise<ProviderProofRecordResponse> {
  return request<ProviderProofRecordResponse>('/api/staff/installer/provider-proof', {
    method: 'POST',
    body: payload,
  })
}

export function testProviderConnection(
  providerId: string,
): Promise<ProviderConnectionTestResponse> {
  return request<ProviderConnectionTestResponse>(
    `/api/staff/installer/provider-credentials/${encodeURIComponent(providerId)}/test-connection`,
    { method: 'POST' },
  )
}

export function provisionR2Concierge(
  payload: R2ConciergeRequest,
): Promise<R2ConciergeResponse> {
  return request<R2ConciergeResponse>('/api/staff/installer/cdn-concierge/r2', {
    method: 'POST',
    body: payload,
  })
}

export function getSourceSetup(): Promise<SourceSetupReport> {
  return request<SourceSetupReport>('/api/staff/installer/source-setup')
}

export function createSetupLiveSource(
  payload: SourceSetupCreateRequest,
): Promise<SourceSetupMutationResponse> {
  return request<SourceSetupMutationResponse>(
    '/api/staff/installer/source-setup/live-source',
    { method: 'POST', body: payload },
  )
}

export function createSampleRehearsalUpload(): Promise<SourceSetupSampleUploadResponse> {
  return request<SourceSetupSampleUploadResponse>(
    '/api/staff/installer/source-setup/sample-upload',
    { method: 'POST' },
  )
}

export function uploadAssetFile({
  assetId,
  title,
  description,
  file,
  selectForRehearsal = false,
}: {
  assetId: string
  title: string
  description?: string
  file: File
  selectForRehearsal?: boolean
}): Promise<UploadedAssetResponse> {
  const body = new FormData()
  body.set('asset_id', assetId)
  body.set('title', title)
  if (description) body.set('description', description)
  if (selectForRehearsal) body.set('select_for_rehearsal', 'true')
  body.set('file', file)
  return requestForm<UploadedAssetResponse>('/api/staff/assets/upload', body)
}

export function getBackupStatus(): Promise<BackupStatus> {
  return request<BackupStatus>('/api/staff/installer/backup')
}

export function configureBackup(
  payload: BackupSetupRequest,
): Promise<BackupStatus> {
  return request<BackupStatus>('/api/staff/installer/backup', {
    method: 'POST',
    body: payload,
  })
}

export function getRestoreStatus(): Promise<RestoreStatus> {
  return request<RestoreStatus>('/api/staff/installer/restore')
}

export function runRestoreRehearsal(): Promise<RestoreStatus> {
  return request<RestoreStatus>('/api/staff/installer/restore/rehearsal', {
    method: 'POST',
  })
}

export function runDisasterRecoveryDrill(): Promise<DrillReport> {
  return request<DrillReport>('/api/staff/installer/dr/run-drill', {
    method: 'POST',
  })
}

export function getUpdateRollbackStatus(): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback')
}

export function runUpdatePreflight(): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback/preflight', {
    method: 'POST',
  })
}

export function openUpdateMaintenanceWindow(durationMinutes = 60): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback/maintenance-window', {
    method: 'POST',
    body: { duration_minutes: durationMinutes },
  })
}

export function configureRollbackArtifact(
  payload: RollbackArtifactRequest,
): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback/rollback-artifact', {
    method: 'POST',
    body: payload,
  })
}

export function runRollbackRehearsal(): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback/rollback-rehearsal', {
    method: 'POST',
  })
}

export function runFailedUpdateRollbackRehearsal(): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback/failed-update-rehearsal', {
    method: 'POST',
  })
}

export function runPostUpdateProof(): Promise<UpdateRollbackStatus> {
  return request<UpdateRollbackStatus>('/api/staff/installer/update-rollback/post-update-proof', {
    method: 'POST',
  })
}

export function createSupportBundle(
  payload: DiagnosticBundleRequest,
): Promise<DiagnosticBundleResponse> {
  return request<DiagnosticBundleResponse>('/api/staff/installer/support-bundle', {
    method: 'POST',
    body: payload,
  })
}

/** Download a generated redacted support bundle to the operator computer. */
export function downloadSupportBundle(bundleId: string): Promise<Blob> {
  return downloadStaffBlob(
    `/api/staff/installer/support-bundle/${encodeURIComponent(bundleId)}/download`,
  )
}

export function listPublishAssets(): Promise<PublishDashboardResponse> {
  return request<PublishDashboardResponse>('/api/staff/publish/assets')
}

export function approvePublishAsset(
  assetId: string,
  payload: PublishApprovalRequest,
): Promise<PublishAssetStatus> {
  return request<PublishAssetStatus>(
    `/api/staff/publish/assets/${encodeURIComponent(assetId)}/approve`,
    { method: 'POST', body: payload },
  )
}

export function retryPublishSurface(
  assetId: string,
  surfaceId: string,
  payload: PublishRetryRequest,
): Promise<PublishAssetStatus> {
  return request<PublishAssetStatus>(
    `/api/staff/publish/assets/${encodeURIComponent(assetId)}/surfaces/${encodeURIComponent(surfaceId)}/retry`,
    { method: 'POST', body: payload },
  )
}

export function getStaffAsset(assetId: string): Promise<AssetRow> {
  return request<AssetRow>(`/api/staff/assets/${encodeURIComponent(assetId)}`)
}

export function packageStaffAsset(assetId: string): Promise<AssetRow> {
  return request<AssetRow>(
    `/api/staff/assets/${encodeURIComponent(assetId)}/package`,
    { method: 'POST' },
  )
}

/** Withdraw an asset from Portal visibility (the inverse of publish approval). */
export function unpublishStaffAsset(assetId: string): Promise<AssetRow> {
  return request<AssetRow>(
    `/api/staff/assets/${encodeURIComponent(assetId)}/unpublish`,
    { method: 'POST' },
  )
}

export function getEgressState(channelId: string): Promise<EgressStateRow | null> {
  return request<EgressStateRow | null>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/state`,
  )
}

export function getEgressHealth(channelId: string): Promise<EgressHealthSample[]> {
  return request<EgressHealthSample[]>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/health?limit=5`,
  )
}

export function getEgressSchemaCurrency(channelId: string): Promise<EgressSchemaCurrency> {
  return request<EgressSchemaCurrency>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/schema-currency`,
  )
}

export function queueEgressCommand(
  channelId: string,
  action: EgressCommandAction,
): Promise<EgressCommandResponse> {
  return request<EgressCommandResponse>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/commands`,
    {
      method: 'POST',
      body: { action },
    },
  )
}

/**
 * POST /api/staff/egress/repair-gstreamer — operator recovery for a station
 * degraded onto the FFmpeg egress engine by a corrupt GStreamer closure
 * (civiccast/egress/router.py's repair_gstreamer_runtime, setup_admin /
 * support_admin gated). Re-verifies the closure in place, or launches a
 * signed re-stage if it's still broken; never a reinstall.
 */
export function repairGstreamerRuntime(): Promise<GstreamerRepairResponse> {
  return request<GstreamerRepairResponse>('/api/staff/egress/repair-gstreamer', {
    method: 'POST',
  })
}

export function updateStaffAsset(
  assetId: string,
  patch: AssetMetadataUpdate,
): Promise<AssetRow> {
  return request<AssetRow>(
    `/api/staff/assets/${encodeURIComponent(assetId)}`,
    { method: 'PATCH', body: patch },
  )
}

export interface ListScheduleParams {
  channel_id?: string
  state?: ScheduleState
}

export function listSchedule(
  params: ListScheduleParams = {},
): Promise<ScheduleItem[]> {
  const qs = new URLSearchParams()
  if (params.channel_id) qs.set('channel_id', params.channel_id)
  if (params.state) qs.set('state', params.state)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<ScheduleItem[]>(`/api/staff/schedule${suffix}`)
}

export function createSchedule(
  payload: ScheduleItemCreate,
): Promise<ScheduleItem> {
  return request<ScheduleItem>('/api/staff/schedule', {
    method: 'POST',
    body: payload,
  })
}

export function cancelSchedule(id: string): Promise<ScheduleItem> {
  return request<ScheduleItem>(`/api/staff/schedule/${id}/cancel`, {
    method: 'POST',
  })
}

export function createLiveSession(
  payload: LiveSessionCreate,
): Promise<LiveSessionResponse> {
  return request<LiveSessionResponse>('/api/staff/live/sessions', {
    method: 'POST',
    body: payload,
  })
}

export function getLiveSession(liveSessionId: string): Promise<LiveSessionResponse> {
  return request<LiveSessionResponse>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}`,
  )
}

export function startLivePreflight(
  liveSessionId: string,
): Promise<LiveSessionResponse> {
  return request<LiveSessionResponse>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}/start-preflight`,
    { method: 'POST' },
  )
}

export function evaluateLivePreflight(
  liveSessionId: string,
  payload: PreflightInputs,
): Promise<PreflightEvaluation> {
  return request<PreflightEvaluation>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}/preflight`,
    { method: 'POST', body: payload },
  )
}

export function goLiveOnAir(
  liveSessionId: string,
  payload: PreflightInputs,
): Promise<LiveSessionResponse> {
  return request<LiveSessionResponse>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}/go-on-air`,
    { method: 'POST', body: payload },
  )
}

export function endLiveBroadcast(
  liveSessionId: string,
): Promise<LiveSessionResponse> {
  return request<LiveSessionResponse>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}/end-broadcast`,
    { method: 'POST' },
  )
}

export function listLiveSources(): Promise<LiveSourceResponse[]> {
  return request<LiveSourceResponse[]>('/api/staff/live/sources')
}

export function listLiveRelayConfigs(): Promise<LiveRelayConfigResponse[]> {
  return request<LiveRelayConfigResponse[]>('/api/staff/live/relay-configs')
}

export function getLiveIngestPlan(channelId: string): Promise<LiveIngestPlan> {
  return request<LiveIngestPlan>(
    `/api/staff/live/ingest-plan?channel_id=${encodeURIComponent(channelId)}`,
  )
}

export function listChannelProfiles(): Promise<ChannelProfile[]> {
  return request<ChannelProfile[]>('/api/staff/cable/channels')
}

/**
 * Thin alias for the Reports filter's channel dropdown — the S23 channel-filter
 * select needs the same list ChannelOpsScreen reads (channel_id + label-ish slug)
 * but does not need the full ChannelProfile branding/outputs payload. We re-use
 * the existing endpoint so there is no separate role gate to maintain.
 */
export function listChannels(): Promise<ChannelProfile[]> {
  return listChannelProfiles()
}

export function getAppPlatformConfig(): Promise<StationAppConfig> {
  return request<StationAppConfig>('/api/staff/app/config')
}

export function updateAppPlatformConfig(
  payload: StationAppConfigUpdate,
): Promise<StationAppConfig> {
  return request<StationAppConfig>('/api/staff/app/config', {
    method: 'PATCH',
    body: payload,
  })
}

export function updateAppPlatformChannelBranding(
  channelId: string,
  payload: ChannelBrandingUpdate,
): Promise<ChannelPublicConfig> {
  return request<ChannelPublicConfig>(
    `/api/staff/app/channels/${encodeURIComponent(channelId)}/branding`,
    { method: 'PATCH', body: payload },
  )
}

// --- OTT app builds + store submissions (S12, build step 8) ---

export function listAppBuilds(appTarget?: string): Promise<AppBuildRecord[]> {
  const query = appTarget ? `?app_target=${encodeURIComponent(appTarget)}` : ''
  return request<AppBuildRecord[]>(`/api/staff/app/builds${query}`)
}

export function getAppBuild(recordId: string): Promise<AppBuildRecord> {
  return request<AppBuildRecord>(`/api/staff/app/builds/${encodeURIComponent(recordId)}`)
}

export function createAppBuild(payload: BuildRequest): Promise<AppBuildRecord> {
  return request<AppBuildRecord>('/api/staff/app/builds', { method: 'POST', body: payload })
}

async function downloadStaffBlob(path: string): Promise<Blob> {
  const token = runtimeStaffToken()
  const setupNonce = runtimeSetupNonce()

  if (setupNonce && typeof window !== 'undefined') {
    window.sessionStorage.setItem('civiccast.setupNonce', setupNonce)
  }

  const res = await fetch(`${runtimeApiBase()}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(setupNonce ? { 'X-CivicCast-Setup-Nonce': setupNonce } : {}),
    },
  })
  if (!res.ok) {
    let detailString: string | undefined
    try {
      const parsed = (await res.json()) as { detail?: unknown }
      const raw = parsed?.detail
      detailString = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : undefined
    } catch {
      // non-JSON body - leave detail undefined
    }
    throw new ApiError(
      `Download failed: ${res.status} ${res.statusText}`,
      res.status,
      userFacingApiDetail(detailString),
      undefined,
      responseRetryAfterSeconds(res),
    )
  }
  return res.blob()
}

/** Fetch a build artifact as a Blob (carries the staff bearer token). */
export async function downloadAppBuild(recordId: string): Promise<Blob> {
  return downloadStaffBlob(`/api/staff/app/builds/${encodeURIComponent(recordId)}/download`)
}

export function listStoreSubmissions(): Promise<StoreSubmissionMetadata[]> {
  return request<StoreSubmissionMetadata[]>('/api/staff/app/store-submissions')
}

export function updateStoreSubmission(
  appTarget: string,
  payload: StoreSubmissionUpdate,
): Promise<StoreSubmissionMetadata> {
  return request<StoreSubmissionMetadata>(
    `/api/staff/app/store-submissions/${encodeURIComponent(appTarget)}`,
    { method: 'PATCH', body: payload },
  )
}

export function getChannelNowNext(channelId: string): Promise<ChannelNowNext> {
  return request<ChannelNowNext>(
    `/api/staff/cable/channels/${encodeURIComponent(channelId)}/now-next`,
  )
}

export function getChannelProofLog(channelId: string): Promise<ChannelProofLog> {
  return request<ChannelProofLog>(
    `/api/staff/cable/channels/${encodeURIComponent(channelId)}/proof-log`,
  )
}

export function getChannelPlayoutPlan(channelId: string): Promise<ChannelPlayoutPlan> {
  return request<ChannelPlayoutPlan>(
    `/api/staff/cable/channels/${encodeURIComponent(channelId)}/playout-plan`,
  )
}

export function previewOverlayCompositorPlan(
  payload: OverlayCompositorRequest,
): Promise<OverlayCompositorPlan> {
  return request<OverlayCompositorPlan>('/api/staff/stream/overlay-compositor-plan', {
    method: 'POST',
    body: payload,
  })
}

export function getFacilityRouterInventory(): Promise<RouterInventory> {
  return request<RouterInventory>('/api/staff/facility/router-inventory')
}

export function getFacilityRouterPanel(endpointId?: string): Promise<VirtualRouterPanel> {
  const qs = new URLSearchParams()
  if (endpointId) qs.set('endpoint_id', endpointId)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<VirtualRouterPanel>(`/api/staff/facility/router-panel${suffix}`)
}

export function previewFacilityRouterTake(
  payload: RouterTakePreviewRequest,
): Promise<RouterTakePlan> {
  return request<RouterTakePlan>('/api/staff/facility/router-take-plan', {
    method: 'POST',
    body: payload,
  })
}

export function previewFacilityRouterSchedulePlan(
  payload: RouterScheduledTakePreviewRequest,
): Promise<RouterScheduledTakePlan> {
  return request<RouterScheduledTakePlan>('/api/staff/facility/router-schedule-plan', {
    method: 'POST',
    body: payload,
  })
}

// --- S16 Production Control Room -------------------------------------------

const CR = '/api/staff/control-room'

export function listProductionDevices(): Promise<ProductionDevice[]> {
  return request<ProductionDevice[]>(`${CR}/devices`)
}

export function createProductionDevice(payload: ProductionDeviceInput): Promise<ProductionDevice> {
  return request<ProductionDevice>(`${CR}/devices`, { method: 'POST', body: payload })
}

export function updateProductionDevice(
  deviceId: string,
  payload: ProductionDeviceInput,
): Promise<ProductionDevice> {
  return request<ProductionDevice>(`${CR}/devices/${encodeURIComponent(deviceId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

export function deleteProductionDevice(deviceId: string): Promise<void> {
  return request<void>(`${CR}/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' })
}

export function upsertDeviceProfile(
  deviceId: string,
  payload: DeviceProfileInput,
): Promise<DeviceProfile> {
  return request<DeviceProfile>(`${CR}/devices/${encodeURIComponent(deviceId)}/profile`, {
    method: 'PUT',
    body: payload,
  })
}

export function probeProductionDevice(deviceId: string): Promise<TsrProbeResult> {
  return request<TsrProbeResult>(`${CR}/devices/${encodeURIComponent(deviceId)}/probe`, {
    method: 'POST',
  })
}

export function getControlRoomReadiness(): Promise<ControlRoomReadinessReport> {
  return request<ControlRoomReadinessReport>(`${CR}/readiness`)
}

export function listControlSurfaces(): Promise<ControlSurface[]> {
  return request<ControlSurface[]>(`${CR}/surfaces`)
}

export function getControlSurface(surfaceId: string): Promise<SurfaceDetail> {
  return request<SurfaceDetail>(`${CR}/surfaces/${encodeURIComponent(surfaceId)}`)
}

export function createControlSurface(payload: ControlSurfaceInput): Promise<ControlSurface> {
  return request<ControlSurface>(`${CR}/surfaces`, { method: 'POST', body: payload })
}

export function createTimelineCue(
  surfaceId: string,
  payload: TimelineCueInput,
): Promise<TimelineCue> {
  return request<TimelineCue>(`${CR}/surfaces/${encodeURIComponent(surfaceId)}/cues`, {
    method: 'POST',
    body: payload,
  })
}

export function deleteTimelineCue(cueId: string): Promise<void> {
  return request<void>(`${CR}/cues/${encodeURIComponent(cueId)}`, { method: 'DELETE' })
}

export function openControlRoomSession(payload: SessionOpenInput): Promise<ControlRoomSession> {
  return request<ControlRoomSession>(`${CR}/sessions`, { method: 'POST', body: payload })
}

export function getControlRoomSession(sessionId: string): Promise<ControlRoomSession> {
  return request<ControlRoomSession>(`${CR}/sessions/${encodeURIComponent(sessionId)}`)
}

export function getControlRoomSessionAudit(sessionId: string): Promise<CueFiredEvent[]> {
  return request<CueFiredEvent[]>(`${CR}/sessions/${encodeURIComponent(sessionId)}/audit`)
}

export function closeControlRoomSession(sessionId: string): Promise<ControlRoomSession> {
  return request<ControlRoomSession>(`${CR}/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export function planControlRoomCue(sessionId: string, cueId: string): Promise<CuePlan> {
  return request<CuePlan>(
    `${CR}/sessions/${encodeURIComponent(sessionId)}/cues/${encodeURIComponent(cueId)}/plan`,
    { method: 'POST' },
  )
}

export function fireControlRoomCue(
  sessionId: string,
  cueId: string,
  payload: FireCueInput | null = null,
): Promise<CueFiredEvent> {
  return request<CueFiredEvent>(
    `${CR}/sessions/${encodeURIComponent(sessionId)}/cues/${encodeURIComponent(cueId)}/fire`,
    { method: 'POST', body: payload },
  )
}

export function rollbackControlRoomSession(sessionId: string): Promise<CueFiredEvent> {
  return request<CueFiredEvent>(`${CR}/sessions/${encodeURIComponent(sessionId)}/rollback`, {
    method: 'POST',
  })
}

// --- S11c Public-safety alerts (EAS ingest + display) ----------------------

const EAS = '/api/staff/eas'

export function listEasSources(): Promise<EasCapSource[]> {
  return request<EasCapSource[]>(`${EAS}/sources`)
}

export function upsertEasSource(source: SourceInput): Promise<EasCapSource> {
  return request<EasCapSource>(`${EAS}/sources/${encodeURIComponent(source.source_id)}`, {
    method: 'PUT',
    body: source,
  })
}

export function deleteEasSource(sourceId: string): Promise<void> {
  return request<void>(`${EAS}/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' })
}

export function listEasAlerts(opts: { active?: boolean; sourceId?: string } = {}): Promise<EasCapAlert[]> {
  const params = new URLSearchParams()
  if (opts.active) params.set('active', 'true')
  if (opts.sourceId) params.set('source_id', opts.sourceId)
  const q = params.toString()
  return request<EasCapAlert[]>(`${EAS}/alerts${q ? `?${q}` : ''}`)
}

export function createManualEasAlert(payload: ManualAlertInput): Promise<EasCapAlert> {
  return request<EasCapAlert>(`${EAS}/alerts/manual`, { method: 'POST', body: payload })
}

export function displayEasAlert(alertId: string, payload: DisplayInput): Promise<EasDisplayDecision> {
  return request<EasDisplayDecision>(`${EAS}/alerts/${encodeURIComponent(alertId)}/display`, {
    method: 'POST',
    body: payload,
  })
}

export function listEasDecisions(channelId?: string): Promise<EasDisplayDecision[]> {
  const q = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ''
  return request<EasDisplayDecision[]>(`${EAS}/decisions${q}`)
}

export function clearEasDecision(decisionId: string): Promise<EasDisplayDecision> {
  return request<EasDisplayDecision>(`${EAS}/decisions/${encodeURIComponent(decisionId)}/clear`, {
    method: 'POST',
  })
}

// --- S22 Custom metadata fields --------------------------------------------

const CF = '/api/staff/custom-fields'

export function listCustomFieldDefs(): Promise<CustomFieldDef[]> {
  return request<CustomFieldDef[]>(CF)
}

export function createCustomFieldDef(payload: CustomFieldDefInput): Promise<CustomFieldDef> {
  return request<CustomFieldDef>(CF, { method: 'POST', body: payload })
}

export function getCustomFieldDef(fieldId: string): Promise<CustomFieldDef> {
  return request<CustomFieldDef>(`${CF}/${encodeURIComponent(fieldId)}`)
}

export function updateCustomFieldDef(
  fieldId: string,
  patch: CustomFieldDefUpdate,
): Promise<CustomFieldDef> {
  return request<CustomFieldDef>(`${CF}/${encodeURIComponent(fieldId)}`, {
    method: 'PATCH',
    body: patch,
  })
}

// DELETE is blocked with a 409 when values exist unless confirm=true cascades
// them (spec §4/§6) — never a silent data loss.
export function deleteCustomFieldDef(fieldId: string, confirm = false): Promise<void> {
  const q = confirm ? '?confirm=true' : ''
  return request<void>(`${CF}/${encodeURIComponent(fieldId)}${q}`, { method: 'DELETE' })
}

// Per-asset values: GET returns this asset's values; PUT full-replaces them
// (typed-validated server-side; a validation failure is a 422).
export function getAssetCustomFields(assetId: string): Promise<CustomFieldValue[]> {
  return request<CustomFieldValue[]>(
    `/api/staff/assets/${encodeURIComponent(assetId)}/custom-fields`,
  )
}

export function putAssetCustomFields(
  assetId: string,
  payload: AssetCustomFieldsUpdate,
): Promise<CustomFieldValue[]> {
  return request<CustomFieldValue[]>(
    `/api/staff/assets/${encodeURIComponent(assetId)}/custom-fields`,
    { method: 'PUT', body: payload },
  )
}

// --- S11 SAP / descriptive audio (audio program tracks) --------------------

const AUDIO = '/api/staff/audio-tracks'

export function listAudioTracks(
  opts: { scope?: 'asset' | 'channel'; targetId?: string } = {},
): Promise<AudioProgramTrack[]> {
  const params = new URLSearchParams()
  if (opts.scope) params.set('scope', opts.scope)
  if (opts.targetId) params.set('target_id', opts.targetId)
  const q = params.toString()
  return request<AudioProgramTrack[]>(`${AUDIO}${q ? `?${q}` : ''}`)
}

export function upsertAudioTrack(track: AudioTrackInput): Promise<AudioProgramTrack> {
  return request<AudioProgramTrack>(`${AUDIO}/${encodeURIComponent(track.track_id)}`, {
    method: 'PUT',
    body: track,
  })
}

export function deleteAudioTrack(trackId: string): Promise<void> {
  return request<void>(`${AUDIO}/${encodeURIComponent(trackId)}`, { method: 'DELETE' })
}

// --- S17 Remote Contribution (VDO.Ninja) -----------------------------------

const RC = '/api/staff/contribution'

export function listContributionRooms(channelId?: string): Promise<ContributionRoom[]> {
  const q = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ''
  return request<ContributionRoom[]>(`${RC}/rooms${q}`)
}

export function createContributionRoom(payload: CreateRoomInput): Promise<ContributionRoom> {
  return request<ContributionRoom>(`${RC}/rooms`, { method: 'POST', body: payload })
}

export function getContributionRoom(roomId: string): Promise<RoomDetail> {
  return request<RoomDetail>(`${RC}/rooms/${encodeURIComponent(roomId)}`)
}

export function openContributionRoom(roomId: string): Promise<RoomOpened> {
  return request<RoomOpened>(`${RC}/rooms/${encodeURIComponent(roomId)}/open`, { method: 'POST' })
}

export function closeContributionRoom(roomId: string): Promise<ContributionRoom> {
  return request<ContributionRoom>(`${RC}/rooms/${encodeURIComponent(roomId)}/close`, {
    method: 'POST',
  })
}

export function mintGuestInvite(roomId: string, payload: MintInviteInput): Promise<GuestInvite> {
  return request<GuestInvite>(`${RC}/rooms/${encodeURIComponent(roomId)}/invites`, {
    method: 'POST',
    body: payload,
  })
}

function guestAction(sessionId: string, action: string): Promise<RemoteGuestSession> {
  return request<RemoteGuestSession>(
    `${RC}/sessions/${encodeURIComponent(sessionId)}/${action}`,
    { method: 'POST' },
  )
}

export const admitContributionGuest = (id: string) => guestAction(id, 'admit')
export const putContributionGuestOnAir = (id: string) => guestAction(id, 'on-air')
export const muteContributionGuest = (id: string) => guestAction(id, 'mute')
export const takeContributionGuestOffAir = (id: string) => guestAction(id, 'off-air')
export const dropContributionGuest = (id: string) => guestAction(id, 'drop')

export function contributionDiagnostics(): Promise<VdoDiagnostics> {
  return request<VdoDiagnostics>(`${RC}/diagnostics`)
}

export function updateControlSurface(
  surfaceId: string,
  payload: ControlSurfaceInput,
): Promise<ControlSurface> {
  return request<ControlSurface>(`${CR}/surfaces/${encodeURIComponent(surfaceId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

export function deleteControlSurface(surfaceId: string): Promise<void> {
  return request<void>(`${CR}/surfaces/${encodeURIComponent(surfaceId)}`, {
    method: 'DELETE',
  })
}

export function listContributionRoomInvites(roomId: string): Promise<GuestInvite[]> {
  return request<GuestInvite[]>(`${RC}/rooms/${encodeURIComponent(roomId)}/invites`)
}

export function getPlaybackPolicy(
  subjectType: PlaybackPolicyConfig['subject_type'],
  subjectId: string,
): Promise<PlaybackPolicyConfig> {
  return request<PlaybackPolicyConfig>(
    `/api/staff/playback-policy/${subjectType}/${encodeURIComponent(subjectId)}`,
  )
}

export function updatePlaybackPolicy(
  subjectType: PlaybackPolicyConfig['subject_type'],
  subjectId: string,
  payload: PlaybackPolicyUpdate,
): Promise<PlaybackPolicyConfig> {
  return request<PlaybackPolicyConfig>(
    `/api/staff/playback-policy/${subjectType}/${encodeURIComponent(subjectId)}`,
    { method: 'POST', body: payload },
  )
}

export function getPlaybackPolicyAuditLog(): Promise<PlaybackPolicyAuditLog> {
  return request<PlaybackPolicyAuditLog>('/api/staff/playback-policy/audit/events')
}

export function getAnalyticsReport(rangeDays = 30): Promise<AnalyticsReport> {
  const qs = new URLSearchParams({ range_days: String(rangeDays) })
  return request<AnalyticsReport>(`/api/staff/analytics/reports/overview?${qs.toString()}`)
}

export function getCgPortalDisplay(
  channelId: string,
  templateId?: string,
): Promise<CgPortalDisplay> {
  const qs = new URLSearchParams()
  if (templateId) qs.set('template_id', templateId)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<CgPortalDisplay>(
    `/api/public/cg/channels/${encodeURIComponent(channelId)}/display${suffix}`,
  )
}

export function listContributorSubmissions(): Promise<ContributorReviewQueue> {
  return request<ContributorReviewQueue>('/api/staff/contribute/submissions')
}

export function reviewContributorSubmission(
  submissionId: string,
  payload: ContributorReviewRequest,
): Promise<ContributorSubmission> {
  return request<ContributorSubmission>(
    `/api/staff/contribute/submissions/${encodeURIComponent(submissionId)}/review`,
    { method: 'POST', body: payload },
  )
}

export function getProducerActivityReport(): Promise<ProducerActivityReport> {
  return request<ProducerActivityReport>('/api/staff/contribute/reports/producers')
}

export function getContributorNotificationOutbox(): Promise<ContributorNotificationOutbox> {
  return request<ContributorNotificationOutbox>('/api/staff/contribute/notifications/outbox')
}

export function getCtvFeed(stationName?: string): Promise<CtvFeed> {
  const qs = new URLSearchParams()
  if (stationName) qs.set('station_name', stationName)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<CtvFeed>(`/api/public/channels/ctv/feed${suffix}`)
}

export function listRecordingTargets(): Promise<RecordingTargetResponse[]> {
  return request<RecordingTargetResponse[]>('/api/staff/live/recording-targets')
}

export interface ListCaptionReviewParams {
  asset_id?: string
  status_filter?: CaptionReviewStatus
}

export function listCaptionReviewItems(
  params: ListCaptionReviewParams = {},
): Promise<CaptionReviewItemResponse[]> {
  const qs = new URLSearchParams()
  if (params.asset_id) qs.set('asset_id', params.asset_id)
  if (params.status_filter) qs.set('status_filter', params.status_filter)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<CaptionReviewItemResponse[]>(
    `/api/staff/captions/review-items${suffix}`,
  )
}

export function approveCaptionReviewItem(
  reviewItemId: string,
  payload: CaptionReviewDecision = {},
): Promise<CaptionReviewItemResponse> {
  return request<CaptionReviewItemResponse>(
    `/api/staff/captions/review-items/${encodeURIComponent(reviewItemId)}/approve`,
    { method: 'POST', body: payload },
  )
}

export async function getCaptionReviewAudioClip(
  reviewItemId: string,
): Promise<Blob> {
  const staffToken = runtimeStaffToken()
  const setupNonce = runtimeSetupNonce()
  const response = await fetch(
    `${runtimeApiBase()}/api/staff/captions/review-items/${encodeURIComponent(reviewItemId)}/clip`,
    {
      headers: {
        Accept: 'audio/wav',
        ...(staffToken ? { Authorization: `Bearer ${staffToken}` } : {}),
        ...(setupNonce ? { 'X-CivicCast-Setup-Nonce': setupNonce } : {}),
      },
    },
  )
  if (!response.ok) {
    let detail: string | undefined
    try {
      const body = (await response.json()) as { detail?: unknown }
      detail =
        typeof body.detail === 'string'
          ? body.detail
          : body.detail
            ? JSON.stringify(body.detail)
            : undefined
    } catch {
      // Non-JSON response: the status remains the actionable boundary.
    }
    throw new ApiError(
      `Request failed: ${response.status} ${response.statusText}`,
      response.status,
      detail,
      undefined,
      responseRetryAfterSeconds(response),
    )
  }
  return response.blob()
}

export function editCaptionReviewItem(
  reviewItemId: string,
  payload: CaptionReviewEdit,
): Promise<CaptionReviewItemResponse> {
  return request<CaptionReviewItemResponse>(
    `/api/staff/captions/review-items/${encodeURIComponent(reviewItemId)}/edit`,
    { method: 'POST', body: payload },
  )
}

export function rejectCaptionReviewItem(
  reviewItemId: string,
  payload: CaptionReviewDecision = {},
): Promise<CaptionReviewItemResponse> {
  return request<CaptionReviewItemResponse>(
    `/api/staff/captions/review-items/${encodeURIComponent(reviewItemId)}/reject`,
    { method: 'POST', body: payload },
  )
}

export function listSummaryReviewItems(): Promise<SummaryReviewQueueResponse> {
  return request<SummaryReviewQueueResponse>('/api/staff/summaries/review-items')
}

export function approveSummary(
  summaryId: string,
  payload: SummaryApprovalRequest,
): Promise<SummaryDraft> {
  return request<SummaryDraft>(
    `/api/staff/summaries/${encodeURIComponent(summaryId)}/approve`,
    { method: 'POST', body: payload },
  )
}

export function exportSignedRecord(
  payload: RecordExportApiRequest,
): Promise<RecordExportResponse> {
  return request<RecordExportResponse>('/api/staff/records', {
    method: 'POST',
    body: payload,
  })
}

export function getActivityPubStatus(): Promise<ActivityPubStatusResponse> {
  return request<ActivityPubStatusResponse>('/api/staff/activitypub/status')
}

export function listActivityPubFollowers(
  status: FollowerRecord['status'] = 'pending',
): Promise<ActivityPubFollowersResponse> {
  const qs = new URLSearchParams({ status })
  return request<ActivityPubFollowersResponse>(
    `/api/staff/activitypub/followers?${qs.toString()}`,
  )
}

export function approveActivityPubFollower(
  payload: FollowerModerationRequest,
): Promise<ActivityPubModerationResponse> {
  return request<ActivityPubModerationResponse>(
    '/api/staff/activitypub/followers/approve',
    { method: 'POST', body: payload },
  )
}

export function rejectActivityPubFollower(
  payload: FollowerModerationRequest,
): Promise<ActivityPubModerationResponse> {
  return request<ActivityPubModerationResponse>(
    '/api/staff/activitypub/followers/reject',
    { method: 'POST', body: payload },
  )
}

export function blockActivityPubFollower(
  payload: FollowerModerationRequest,
): Promise<ActivityPubModerationResponse> {
  return request<ActivityPubModerationResponse>(
    '/api/staff/activitypub/followers/block',
    { method: 'POST', body: payload },
  )
}

export function listActivityPubOutbox(): Promise<ActivityPubOutboxResponse> {
  return request<ActivityPubOutboxResponse>('/api/staff/activitypub/outbox')
}

export function listActivityPubDeliveries(
  activityId?: string,
): Promise<ActivityPubDeliveriesResponse> {
  const qs = new URLSearchParams()
  if (activityId) qs.set('activity_id', activityId)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<ActivityPubDeliveriesResponse>(
    `/api/staff/activitypub/deliveries${suffix}`,
  )
}

export function listActivityPubDeliveryRetries(): Promise<ActivityPubDeliveryRetriesResponse> {
  return request<ActivityPubDeliveryRetriesResponse>(
    '/api/staff/activitypub/delivery-retries',
  )
}

export function replayActivityPubDeliveryRetry(
  retryId: string,
): Promise<DeliveryRetryRecord> {
  return request<DeliveryRetryRecord>(
    `/api/staff/activitypub/delivery-retries/${encodeURIComponent(retryId)}/replay`,
    { method: 'POST' },
  )
}

export function listProgramSlots(channelId?: string): Promise<ProgramSlot[]> {
  const qs = new URLSearchParams()
  if (channelId) qs.set('channel_id', channelId)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<ProgramSlot[]>(`/api/staff/programlog/slots${suffix}`)
}

export function createProgramSlot(payload: ProgramSlotCreate): Promise<ProgramSlot> {
  return request<ProgramSlot>('/api/staff/programlog/slots', {
    method: 'POST',
    body: payload,
  })
}

export function disableProgramSlot(slotId: string): Promise<SlotOccurrence[]> {
  return request<SlotOccurrence[]>(
    `/api/staff/programlog/slots/${encodeURIComponent(slotId)}/disable`,
    { method: 'POST' },
  )
}

export function getChannelProgramLog(
  channelId: string,
  hours = 168,
): Promise<ChannelLogEntry[]> {
  const qs = new URLSearchParams({ hours: String(hours) })
  return request<ChannelLogEntry[]>(
    `/api/staff/programlog/channels/${encodeURIComponent(channelId)}/log?${qs.toString()}`,
  )
}

export function materializeProgramLog(): Promise<MaterializeResult> {
  return request<MaterializeResult>('/api/staff/programlog/materialize', {
    method: 'POST',
  })
}

// --- S4 Commit-to-Air gate ---
export function prepareCommit(body: PrepareCommitRequest): Promise<CommitToAirPlan> {
  return request<CommitToAirPlan>('/api/staff/playout/prepare-commit', {
    method: 'POST',
    body,
  })
}

export function commitToAir(body: CommitRequest): Promise<CommitToAirReport> {
  return request<CommitToAirReport>('/api/staff/playout/commit', {
    method: 'POST',
    body,
  })
}

export function listCommits(
  channelId: string,
  opts: { startAt?: string; endAt?: string; limit?: number } = {},
): Promise<CommitToAirReport[]> {
  const qs = new URLSearchParams({ channel_id: channelId })
  if (opts.startAt) qs.set('start_at', opts.startAt)
  if (opts.endAt) qs.set('end_at', opts.endAt)
  if (opts.limit != null) qs.set('limit', String(opts.limit))
  return request<CommitToAirReport[]>(`/api/staff/playout/commits?${qs.toString()}`)
}

export function getCommit(reportId: string): Promise<CommitToAirReport> {
  return request<CommitToAirReport>(
    `/api/staff/playout/commits/${encodeURIComponent(reportId)}`,
  )
}

export function rollbackCommit(
  reportId: string,
  body: RollbackRequest,
): Promise<CommitToAirReport> {
  return request<CommitToAirReport>(
    `/api/staff/playout/rollback/${encodeURIComponent(reportId)}`,
    { method: 'POST', body },
  )
}

// --- S5 Force Matrix: live takeover ---
export function beginTakeover(
  channelId: string,
  body: TakeoverRequest = {},
): Promise<TakeoverSession> {
  return request<TakeoverSession>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/takeover`,
    { method: 'POST', body },
  )
}

export function handbackTakeover(
  channelId: string,
  body: HandbackRequest = {},
): Promise<TakeoverSession> {
  return request<TakeoverSession>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/takeover`,
    { method: 'DELETE', body },
  )
}

export function getTakeoverState(channelId: string): Promise<ManualRouteState> {
  return request<ManualRouteState>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/takeover-state`,
  )
}

export function listTakeoverAudit(
  channelId: string,
  limit = 50,
): Promise<TakeoverSession[]> {
  const qs = new URLSearchParams({ limit: String(limit) })
  return request<TakeoverSession[]>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/takeover-audit?${qs.toString()}`,
  )
}

export function listEgressChannels(): Promise<StaffEgressChannelSummary[]> {
  return request<StaffEgressChannelSummary[]>('/api/staff/egress/channels')
}

export function getEgressConfig(channelId: string): Promise<EgressConfig> {
  return request<EgressConfig>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/config`,
  )
}

export function getLoudnessPlan(channelId: string): Promise<ChannelLoudnessPlan> {
  return request<ChannelLoudnessPlan>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/loudness-plan`,
  )
}

export function getCaptionStatus(channelId: string): Promise<CaptionStatusResponse> {
  return request<CaptionStatusResponse>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/caption-status`,
  )
}

export function getCaptionProofs(
  channelId: string,
  limit = 20,
): Promise<EgressCaptionProofSample[]> {
  const qs = new URLSearchParams({ limit: String(limit) })
  return request<EgressCaptionProofSample[]>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/caption-proofs?${qs.toString()}`,
  )
}

export type OfflineCaptionJobState = OfflineCaptionJobRecord['state']

/**
 * GET /api/staff/captions/offline-jobs — offline caption job rows (K3):
 * state / attempts / last_error, for operator visibility. Optionally
 * narrowed to one asset and/or one state (e.g. `state: 'failed'` for a
 * retry queue view). No React screen called this before the captions job
 * drawer (civiccast/captions/router.py's list_offline_caption_jobs).
 */
export function listOfflineCaptionJobs(
  params: { assetId?: string; state?: OfflineCaptionJobState } = {},
): Promise<OfflineCaptionJobRecord[]> {
  const qs = new URLSearchParams()
  if (params.assetId) qs.set('asset_id', params.assetId)
  if (params.state) qs.set('state', params.state)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<OfflineCaptionJobRecord[]>(`/api/staff/captions/offline-jobs${suffix}`)
}

/**
 * POST /api/staff/captions/offline-jobs/{job_id}/retry — manually retry a
 * failed offline caption job (records_clerk gated). 409 if a different job
 * is already active for the same asset; the caller surfaces that message.
 */
export function retryOfflineCaptionJob(jobId: string): Promise<OfflineCaptionJobRecord> {
  return request<OfflineCaptionJobRecord>(
    `/api/staff/captions/offline-jobs/${encodeURIComponent(jobId)}/retry`,
    { method: 'POST' },
  )
}

export function updateEgressConfig(
  channelId: string,
  payload: EgressConfig,
): Promise<EgressConfig> {
  return request<EgressConfig>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/config`,
    { method: 'PUT', body: payload },
  )
}

export function listHeadendProfiles(): Promise<HeadendProfile[]> {
  return request<HeadendProfile[]>('/api/staff/egress/headend-profiles')
}

export function applyHeadendProfile(
  channelId: string,
  payload: HeadendProfileApplyRequest,
): Promise<EgressConfig> {
  return request<EgressConfig>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/config/headend-profile`,
    { method: 'POST', body: payload },
  )
}

export function runComplianceProbe(
  channelId: string,
  seconds = 10,
): Promise<ComplianceProbeResult> {
  return request<ComplianceProbeResult>(
    `/api/staff/egress/channels/${encodeURIComponent(channelId)}/compliance-probe`,
    { method: 'POST', body: { seconds } },
  )
}

export function getStaffBulletinQueue(channelId: string): Promise<CgBulletinQueue> {
  return request<CgBulletinQueue>(
    `/api/staff/cg/channels/${encodeURIComponent(channelId)}/bulletins`,
  )
}

export function createCgBulletin(
  channelId: string,
  payload: BulletinCreate,
): Promise<CgBulletinSubmission> {
  return request<CgBulletinSubmission>(
    `/api/staff/cg/channels/${encodeURIComponent(channelId)}/bulletins`,
    { method: 'POST', body: payload },
  )
}

export function moderateCgBulletin(
  channelId: string,
  submissionId: string,
  payload: BulletinUpdate,
): Promise<CgBulletinSubmission> {
  return request<CgBulletinSubmission>(
    `/api/staff/cg/channels/${encodeURIComponent(channelId)}/bulletins/${encodeURIComponent(submissionId)}`,
    { method: 'PATCH', body: payload },
  )
}

// --- CG bulletin-board designer (S6 V1, build step 7) ---

function cgBoardBase(channelId: string): string {
  return `/api/staff/cg/channels/${encodeURIComponent(channelId)}`
}

export function getCgBoard(channelId: string): Promise<BoardView | null> {
  return request<BoardView | null>(`${cgBoardBase(channelId)}/board`)
}

export function createCgBoard(channelId: string, payload: { template_id: string }): Promise<CgBoard> {
  return request<CgBoard>(`${cgBoardBase(channelId)}/board`, { method: 'POST', body: payload })
}

export function updateCgBoard(
  channelId: string,
  payload: { template_id?: string; active?: boolean },
): Promise<CgBoard> {
  return request<CgBoard>(`${cgBoardBase(channelId)}/board`, { method: 'PATCH', body: payload })
}

export function addCgZone(channelId: string, payload: ZoneInput): Promise<CgZoneConfig> {
  return request<CgZoneConfig>(`${cgBoardBase(channelId)}/zones`, { method: 'POST', body: payload })
}

export function updateCgZone(
  channelId: string,
  zoneId: string,
  payload: ZoneUpdateInput,
): Promise<CgZoneConfig> {
  return request<CgZoneConfig>(`${cgBoardBase(channelId)}/zones/${encodeURIComponent(zoneId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

export function deleteCgZone(channelId: string, zoneId: string): Promise<void> {
  return request<void>(`${cgBoardBase(channelId)}/zones/${encodeURIComponent(zoneId)}`, {
    method: 'DELETE',
  })
}

export function addCgFeed(channelId: string, payload: FeedInput): Promise<CgFeedSource> {
  return request<CgFeedSource>(`${cgBoardBase(channelId)}/feeds`, { method: 'POST', body: payload })
}

export function updateCgFeed(
  channelId: string,
  feedSourceId: string,
  payload: FeedUpdateInput,
): Promise<CgFeedSource> {
  return request<CgFeedSource>(`${cgBoardBase(channelId)}/feeds/${encodeURIComponent(feedSourceId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

export function deleteCgFeed(channelId: string, feedSourceId: string): Promise<void> {
  return request<void>(`${cgBoardBase(channelId)}/feeds/${encodeURIComponent(feedSourceId)}`, {
    method: 'DELETE',
  })
}

export function listCgFeedItemsForReview(
  channelId: string,
  feedSourceId: string,
): Promise<CgFeedItem[]> {
  return request<CgFeedItem[]>(
    `${cgBoardBase(channelId)}/feeds/${encodeURIComponent(feedSourceId)}/items`,
  )
}

export function approveCgFeedItem(
  channelId: string,
  feedSourceId: string,
  itemId: string,
): Promise<CgFeedItemApproval> {
  return request<CgFeedItemApproval>(
    `${cgBoardBase(channelId)}/feeds/${encodeURIComponent(feedSourceId)}/items/${encodeURIComponent(itemId)}/approve`,
    { method: 'POST' },
  )
}

export function previewCgBoard(channelId: string): Promise<ResolvedBoard> {
  return request<ResolvedBoard>(`${cgBoardBase(channelId)}/preview`)
}

export function listCgBoardAudit(
  channelId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<CgBoardAuditEvent[]> {
  const params = new URLSearchParams()
  if (opts.limit != null) params.set('limit', String(opts.limit))
  if (opts.offset != null) params.set('offset', String(opts.offset))
  const query = params.toString()
  return request<CgBoardAuditEvent[]>(`${cgBoardBase(channelId)}/board/audit${query ? `?${query}` : ''}`)
}

export function getLiveFinalizationStatus(
  liveSessionId: string,
): Promise<LiveFinalizationStatusResponse> {
  return request<LiveFinalizationStatusResponse>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}/finalization`,
  )
}

export function retryLiveFinalization(
  liveSessionId: string,
): Promise<LiveFinalizationStatusResponse> {
  return request<LiveFinalizationStatusResponse>(
    `/api/staff/live/sessions/${encodeURIComponent(liveSessionId)}/finalization/retry`,
    { method: 'POST' },
  )
}

// ---------------------------------------------------------------------------
// S8-5 operational alerting hub: runtime safe-to-air, system resources,
// self-tests, alert rules/channels/events.
// ---------------------------------------------------------------------------

export function getRuntimeSafeToAir(): Promise<RuntimeSafeToAirStatus> {
  return request<RuntimeSafeToAirStatus>('/api/staff/runtime-safe-to-air')
}

export function listSystemResources(windowMinutes = 60): Promise<SystemResourceSample[]> {
  const qs = new URLSearchParams({ window_minutes: String(windowMinutes) })
  return request<SystemResourceSample[]>(`/api/staff/system-resources?${qs.toString()}`)
}

export function listSelfTests(kind?: 'daily' | 'weekly'): Promise<SystemSelfTest[]> {
  const qs = new URLSearchParams()
  if (kind) qs.set('kind', kind)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<SystemSelfTest[]>(`/api/staff/self-tests${suffix}`)
}

export function runSelfTestNow(kind: 'daily' | 'weekly'): Promise<SystemSelfTest> {
  const qs = new URLSearchParams({ kind })
  return request<SystemSelfTest>(`/api/staff/self-tests/run?${qs.toString()}`, {
    method: 'POST',
  })
}

export function listAlertRules(): Promise<AlertRule[]> {
  return request<AlertRule[]>('/api/staff/alert-rules')
}

export function updateAlertRule(ruleId: string, payload: AlertRuleUpdate): Promise<AlertRule> {
  return request<AlertRule>(`/api/staff/alert-rules/${encodeURIComponent(ruleId)}`, {
    method: 'PUT',
    body: payload,
  })
}

export function listAlertChannels(): Promise<AlertChannel[]> {
  return request<AlertChannel[]>('/api/staff/alert-channels')
}

export function createAlertChannel(payload: AlertChannelInput): Promise<AlertChannel> {
  return request<AlertChannel>('/api/staff/alert-channels', { method: 'POST', body: payload })
}

export function updateAlertChannel(
  channelId: string,
  payload: AlertChannelInput,
): Promise<AlertChannel> {
  return request<AlertChannel>(`/api/staff/alert-channels/${encodeURIComponent(channelId)}`, {
    method: 'PUT',
    body: payload,
  })
}

export function deleteAlertChannel(channelId: string): Promise<void> {
  return request<void>(`/api/staff/alert-channels/${encodeURIComponent(channelId)}`, {
    method: 'DELETE',
  })
}

// --- S18 query-driven auto-scheduling (saved searches / daypart blocks / rules) ---

export function listSavedSearches(): Promise<SavedSearch[]> {
  return request<SavedSearch[]>('/api/staff/auto-schedule/saved-searches')
}

export function createSavedSearch(payload: SavedSearchInput): Promise<SavedSearch> {
  return request<SavedSearch>('/api/staff/auto-schedule/saved-searches', {
    method: 'POST',
    body: payload,
  })
}

export function updateSavedSearch(
  savedSearchId: string,
  payload: SavedSearchInput,
): Promise<SavedSearch> {
  return request<SavedSearch>(
    `/api/staff/auto-schedule/saved-searches/${encodeURIComponent(savedSearchId)}`,
    { method: 'PUT', body: payload },
  )
}

export function deleteSavedSearch(savedSearchId: string): Promise<void> {
  return request<void>(
    `/api/staff/auto-schedule/saved-searches/${encodeURIComponent(savedSearchId)}`,
    { method: 'DELETE' },
  )
}

export function listScheduleBlocks(channelId?: string): Promise<ScheduleBlock[]> {
  const query = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ''
  return request<ScheduleBlock[]>(`/api/staff/auto-schedule/blocks${query}`)
}

export function createScheduleBlock(payload: ScheduleBlockInput): Promise<ScheduleBlock> {
  return request<ScheduleBlock>('/api/staff/auto-schedule/blocks', {
    method: 'POST',
    body: payload,
  })
}

export function updateScheduleBlock(
  blockId: string,
  payload: ScheduleBlockInput,
): Promise<ScheduleBlock> {
  return request<ScheduleBlock>(
    `/api/staff/auto-schedule/blocks/${encodeURIComponent(blockId)}`,
    { method: 'PUT', body: payload },
  )
}

export function deleteScheduleBlock(blockId: string): Promise<void> {
  return request<void>(`/api/staff/auto-schedule/blocks/${encodeURIComponent(blockId)}`, {
    method: 'DELETE',
  })
}

export function listAutoScheduleRules(channelId?: string): Promise<AutoScheduleRule[]> {
  const query = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : ''
  return request<AutoScheduleRule[]>(`/api/staff/auto-schedule/rules${query}`)
}

export function createAutoScheduleRule(payload: AutoScheduleRuleInput): Promise<AutoScheduleRule> {
  return request<AutoScheduleRule>('/api/staff/auto-schedule/rules', {
    method: 'POST',
    body: payload,
  })
}

export function updateAutoScheduleRule(
  ruleId: string,
  payload: AutoScheduleRuleInput,
): Promise<AutoScheduleRule> {
  return request<AutoScheduleRule>(
    `/api/staff/auto-schedule/rules/${encodeURIComponent(ruleId)}`,
    { method: 'PUT', body: payload },
  )
}

export function deleteAutoScheduleRule(ruleId: string): Promise<void> {
  return request<void>(`/api/staff/auto-schedule/rules/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
  })
}

export function previewAutoScheduleRule(ruleId: string): Promise<RulePreview> {
  return request<RulePreview>(
    `/api/staff/auto-schedule/rules/${encodeURIComponent(ruleId)}/preview`,
    { method: 'POST' },
  )
}

export function compileAutoSchedule(): Promise<CompileReport> {
  return request<CompileReport>('/api/staff/auto-schedule/compile', { method: 'POST' })
}

export interface ListAlertEventsParams {
  state?: 'firing' | 'resolved'
  severity?: 'critical' | 'warning' | 'info'
  limit?: number
}

export function listAlertEvents(params: ListAlertEventsParams = {}): Promise<AlertEvent[]> {
  const qs = new URLSearchParams()
  if (params.state) qs.set('state', params.state)
  if (params.severity) qs.set('severity', params.severity)
  if (params.limit != null) qs.set('limit', String(params.limit))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<AlertEvent[]>(`/api/staff/alert-events${suffix}`)
}

export function acknowledgeAlertEvent(eventId: string): Promise<AlertEvent> {
  return request<AlertEvent>(
    `/api/staff/alert-events/${encodeURIComponent(eventId)}/ack`,
    { method: 'POST' },
  )
}

export function getTsduckStatus(): Promise<TsduckStatus> {
  return request<TsduckStatus>('/api/staff/installer/tsduck')
}

export function installTsduck(): Promise<TsduckInstallReport> {
  // The server download caps at 300s; give the client a little more headroom so
  // it fails deterministically instead of hanging indefinitely.
  return request<TsduckInstallReport>('/api/staff/installer/tsduck/install', {
    method: 'POST',
    timeoutMs: 330_000,
  })
}

// --- S13 AI model selection (operator chooses per-feature model + tier) ------

const AI_MODELS = '/api/staff/ai-models'

/** The station-wide configuration: every feature's registry (catalog + selection). */
export function getAiModelConfiguration(): Promise<AiModelConfiguration> {
  return request<AiModelConfiguration>(AI_MODELS)
}

/**
 * Per-feature availability of the effective model (present/absent + runtime
 * reachability). The console renders this as a §6.3 "AI runtime unavailable / model
 * not installed — this feature will defer" hint so the operator is not surprised
 * at meeting time. Role-gated read (setup_admin | meeting_operator).
 */
export function getAiModelAvailability(): Promise<AiModelAvailability> {
  return request<AiModelAvailability>(`${AI_MODELS}/availability`)
}

/** The catalog tiers + the operator's current selection for one feature. */
export function getFeatureModelRegistry(feature: string): Promise<FeatureModelRegistry> {
  return request<FeatureModelRegistry>(`${AI_MODELS}/${encodeURIComponent(feature)}`)
}

/** Record the operator's model selection for a feature (setup-admin only; catalog-validated). */
export function selectFeatureModel(
  feature: string,
  payload: ModelSelectionRequest,
): Promise<FeatureModelRegistry> {
  return request<FeatureModelRegistry>(
    `${AI_MODELS}/${encodeURIComponent(feature)}/select`,
    { method: 'POST', body: payload },
  )
}

/**
 * Whether a cloud-provider API key is stored (boolean only — the key is NEVER
 * returned). The console reads this to decide whether to show the "enter a key"
 * field for a staged hosted tier. Role-gated read (setup_admin | meeting_operator).
 */
export function getProviderKeyStatus(
  provider: 'ollama-cloud' | 'openrouter',
): Promise<ProviderKeyStatus> {
  return request<ProviderKeyStatus>(
    `${AI_MODELS}/credentials/${encodeURIComponent(provider)}`,
  )
}

/**
 * Store a cloud-provider API key in the OS keyring (write-only; the key is never
 * echoed back — the response is only a stored/not-stored signal). This is the
 * operator path that makes a hosted tier work end-to-end once selected with
 * consent (DONE-10 / D13). setup_admin only.
 */
export function saveProviderKey(
  provider: 'ollama-cloud' | 'openrouter',
  payload: ProviderKeyRequest,
): Promise<ProviderKeyStatus> {
  return request<ProviderKeyStatus>(
    `${AI_MODELS}/credentials/${encodeURIComponent(provider)}`,
    { method: 'PUT', body: payload },
  )
}

// --- S23 Reports + EPG export ----------------------------------------------
//
// Three families of staff endpoints, all role-gated server-side:
//   * /api/staff/reports/{as-run,shows,hours-by-category} — support_admin read
//   * /api/staff/reports/export — same role, returns a CSV/XML document
//   * /api/staff/epg/configs[/{id}][/generate] — setup_admin / publish_operator
//
// The screens read identity via getStaffIdentity() and surface a no-access
// banner without firing the request, so we don't need to inspect the 403 here.

const REPORTS = '/api/staff/reports'
const EPG = '/api/staff/epg'

export interface ReportRangeParams {
  /** ISO timestamp; the server reads `from` as datetime, alias of `from_ts`. */
  from: string
  /** ISO timestamp; exclusive upper bound `[from, to)`. */
  to: string
  /** Optional channel filter (channel_id). */
  channel?: string | null
}

export interface AsRunReportParams extends ReportRangeParams {
  /** Optional S22 custom-field key for category enrichment on each row. */
  field?: string | null
}

export interface HoursByCategoryParams extends ReportRangeParams {
  /** Required custom-field key (e.g. "category"). Unknown -> field_not_found=true. */
  field: string
}

function reportsQs(params: {
  from: string
  to: string
  channel?: string | null
  field?: string | null
  type?: 'as-run' | 'shows'
  format?: 'csv' | 'xml'
}): string {
  const qs = new URLSearchParams()
  qs.set('from', params.from)
  qs.set('to', params.to)
  if (params.channel) qs.set('channel', params.channel)
  if (params.field) qs.set('field', params.field)
  if (params.type) qs.set('type', params.type)
  if (params.format) qs.set('format', params.format)
  return qs.toString()
}

/** GET /api/staff/reports/as-run — engine-verified actual air times. */
export function getAsRunReport(params: AsRunReportParams): Promise<AsRunReport> {
  return request<AsRunReport>(`${REPORTS}/as-run?${reportsQs(params)}`)
}

/** GET /api/staff/reports/shows — per-asset play counts + airtime. */
export function getShowsReport(params: ReportRangeParams): Promise<ShowsReport> {
  return request<ShowsReport>(`${REPORTS}/shows?${reportsQs(params)}`)
}

/**
 * GET /api/staff/reports/hours-by-category — franchise hours grouped by an
 * S22 custom field. A missing field_key surfaces as `field_not_found=true` on
 * the response body rather than a 404 so the misnamed key is visible in-UI.
 */
export function getHoursByCategoryReport(
  params: HoursByCategoryParams,
): Promise<HoursByCategoryReport> {
  return request<HoursByCategoryReport>(`${REPORTS}/hours-by-category?${reportsQs(params)}`)
}

/**
 * Build the absolute URL for /api/staff/reports/export — used by the screens
 * as an `<a download href=...>` target so the browser handles the file save.
 * Includes the runtime API base so a cross-origin staff host still works.
 */
export function reportsExportUrl(params: {
  type: 'as-run' | 'shows'
  format: 'csv' | 'xml'
  from: string
  to: string
  channel?: string | null
  field?: string | null
}): string {
  const qs = reportsQs(params)
  return `${runtimeApiBase()}${REPORTS}/export?${qs}`
}

/** Fetch a report export as a Blob (carries the staff bearer token). */
export function downloadReportsExport(params: {
  type: 'as-run' | 'shows'
  format: 'csv' | 'xml'
  from: string
  to: string
  channel?: string | null
  field?: string | null
}): Promise<Blob> {
  return downloadStaffBlob(`${REPORTS}/export?${reportsQs(params)}`)
}

/** GET /api/staff/epg/configs — list configs for the station. */
export function listEpgConfigs(): Promise<EpgExportConfig[]> {
  return request<EpgExportConfig[]>(`${EPG}/configs`)
}

/** GET /api/staff/epg/configs/{config_id} — fetch one. 404 if unknown. */
export function getEpgConfig(configId: string): Promise<EpgExportConfig> {
  return request<EpgExportConfig>(`${EPG}/configs/${encodeURIComponent(configId)}`)
}

/** POST /api/staff/epg/configs — create. */
export function createEpgConfig(payload: EpgExportConfigInput): Promise<EpgExportConfig> {
  return request<EpgExportConfig>(`${EPG}/configs`, { method: 'POST', body: payload })
}

/** PATCH /api/staff/epg/configs/{config_id} — partial update (absent keys unchanged). */
export function patchEpgConfig(
  configId: string,
  payload: EpgExportConfigUpdate,
): Promise<EpgExportConfig> {
  return request<EpgExportConfig>(`${EPG}/configs/${encodeURIComponent(configId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

/** DELETE /api/staff/epg/configs/{config_id} — 204 on success, 404 if unknown. */
export function deleteEpgConfig(configId: string): Promise<void> {
  return request<void>(`${EPG}/configs/${encodeURIComponent(configId)}`, { method: 'DELETE' })
}

/**
 * POST /api/staff/epg/configs/{config_id}/generate — run the export. If the
 * config has no `endpoint`, the document is returned inline; otherwise it is
 * pushed to the aggregator and `pushed_to`/`pushed_at` are populated. A push
 * failure is reported on `error` rather than as a 500 (the staff API stays up).
 */
export function generateEpgExport(configId: string): Promise<EpgGenerateResult> {
  return request<EpgGenerateResult>(
    `${EPG}/configs/${encodeURIComponent(configId)}/generate`,
    { method: 'POST' },
  )
}

// --- S24 Underwriting (spots / flights / placements / affidavits) ----------
//
// Three role-gated surface families under /api/staff/underwriting/...:
//   * spots  + flights + placements → publish_operator OR setup_admin
//   * affidavits (read + export)    → support_admin
//
// As with reports, the screen surfaces an access banner without firing the
// request when the operator lacks the role, so we don't need to special-case
// 403 here. The affidavit export URL builder is used as an `<a download>`
// target so the browser handles the file save (binary PDF included).

const UNDERWRITING = '/api/staff/underwriting'

/** GET /api/staff/underwriting/spots — list spots, optional underwriter filter. */
export function listUnderwritingSpots(params: {
  underwriter?: string | null
} = {}): Promise<UnderwritingSpot[]> {
  const qs = new URLSearchParams()
  if (params.underwriter) qs.set('underwriter', params.underwriter)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<UnderwritingSpot[]>(`${UNDERWRITING}/spots${suffix}`)
}

/** GET /api/staff/underwriting/spots/{spot_id} — 404 if unknown. */
export function getUnderwritingSpot(spotId: string): Promise<UnderwritingSpot> {
  return request<UnderwritingSpot>(`${UNDERWRITING}/spots/${encodeURIComponent(spotId)}`)
}

/** POST /api/staff/underwriting/spots — create a spot. */
export function createUnderwritingSpot(
  payload: UnderwritingSpotInput,
): Promise<UnderwritingSpot> {
  return request<UnderwritingSpot>(`${UNDERWRITING}/spots`, { method: 'POST', body: payload })
}

/**
 * PATCH /api/staff/underwriting/spots/{spot_id} — partial update; absent keys
 * leave the stored field unchanged. `spot_id` / `station_id` are not editable.
 */
export function patchUnderwritingSpot(
  spotId: string,
  payload: UnderwritingSpotUpdate,
): Promise<UnderwritingSpot> {
  return request<UnderwritingSpot>(`${UNDERWRITING}/spots/${encodeURIComponent(spotId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

/**
 * DELETE /api/staff/underwriting/spots/{spot_id} — 204 on success. The server
 * cascades to every flight + placement that referenced this spot in a single
 * transaction; the UI surfaces a two-step confirm so the operator is warned.
 */
export function deleteUnderwritingSpot(spotId: string): Promise<void> {
  return request<void>(`${UNDERWRITING}/spots/${encodeURIComponent(spotId)}`, { method: 'DELETE' })
}

/**
 * GET /api/staff/underwriting/flights — list flights with optional filters.
 *  - `spot_id` narrows to one spot
 *  - `active_on` is an ISO date (YYYY-MM-DD); returns flights whose
 *    `[start_date, end_date]` window covers that date.
 */
export function listSpotFlights(params: {
  spot_id?: string | null
  active_on?: string | null
} = {}): Promise<SpotFlight[]> {
  const qs = new URLSearchParams()
  if (params.spot_id) qs.set('spot_id', params.spot_id)
  if (params.active_on) qs.set('active_on', params.active_on)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<SpotFlight[]>(`${UNDERWRITING}/flights${suffix}`)
}

/** GET /api/staff/underwriting/flights/{flight_id} — 404 if unknown. */
export function getSpotFlight(flightId: string): Promise<SpotFlight> {
  return request<SpotFlight>(`${UNDERWRITING}/flights/${encodeURIComponent(flightId)}`)
}

/** POST /api/staff/underwriting/flights — create a flight. */
export function createSpotFlight(payload: SpotFlightInput): Promise<SpotFlight> {
  return request<SpotFlight>(`${UNDERWRITING}/flights`, { method: 'POST', body: payload })
}

/** PATCH /api/staff/underwriting/flights/{flight_id} — patch semantics (absent unchanged). */
export function patchSpotFlight(
  flightId: string,
  payload: SpotFlightUpdate,
): Promise<SpotFlight> {
  return request<SpotFlight>(`${UNDERWRITING}/flights/${encodeURIComponent(flightId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

/** DELETE /api/staff/underwriting/flights/{flight_id} — cascades placements. */
export function deleteSpotFlight(flightId: string): Promise<void> {
  return request<void>(`${UNDERWRITING}/flights/${encodeURIComponent(flightId)}`, {
    method: 'DELETE',
  })
}

/**
 * GET /api/staff/underwriting/placements — read-only view of materialized
 * placements over a half-open `[from, to)` window on `scheduled_at`. Optional
 * `channel` + `flight` filters. Placements are written by the trafficking
 * compiler, not the UI.
 */
export function listSpotPlacements(params: {
  from: string
  to: string
  channel?: string | null
  flight?: string | null
}): Promise<SpotPlacement[]> {
  const qs = new URLSearchParams()
  qs.set('from', params.from)
  qs.set('to', params.to)
  if (params.channel) qs.set('channel', params.channel)
  if (params.flight) qs.set('flight', params.flight)
  return request<SpotPlacement[]>(`${UNDERWRITING}/placements?${qs.toString()}`)
}

/**
 * GET /api/staff/underwriting/affidavits — per-underwriter proof-of-airing
 * over an inclusive ISO date range. The route is support_admin-only; the
 * screen role-gates on the same set before firing.
 */
export function getUnderwriterAffidavit(params: {
  underwriter: string
  from: string
  to: string
}): Promise<UnderwriterAffidavit> {
  const qs = new URLSearchParams()
  qs.set('underwriter', params.underwriter)
  qs.set('from', params.from)
  qs.set('to', params.to)
  return request<UnderwriterAffidavit>(`${UNDERWRITING}/affidavits?${qs.toString()}`)
}

/**
 * Build the absolute URL for /api/staff/underwriting/affidavits/export, used
 * as an `<a download href=...>` target so the browser handles the file save
 * (binary PDF too). Includes the runtime API base for cross-origin staff
 * hosts. Mirrors the shape of `reportsExportUrl`.
 */
export function affidavitExportUrl(params: {
  underwriter: string
  from: string
  to: string
  format: 'csv' | 'xml' | 'pdf'
}): string {
  const qs = new URLSearchParams()
  qs.set('underwriter', params.underwriter)
  qs.set('from', params.from)
  qs.set('to', params.to)
  qs.set('format', params.format)
  return `${runtimeApiBase()}${UNDERWRITING}/affidavits/export?${qs.toString()}`
}

// --- S25 Meeting agendas (CRUD + items + sync + import) ---------------------
//
// Staff CRUD lives under /api/staff/agendas/...; the AUTHOR roles are
// records_clerk + meeting_operator (matches the router's _AUTHOR set). The
// screen role-gates on the same set before firing.
//
// Publish / unpublish rides PATCH /agendas/{id} with `{status: ...}` so the
// service's empty-agenda gate (DC-1) runs unconditionally — a generic PATCH
// can never bypass the 422 refusal.
//
// `importAgendaFromDoc` POSTs a raw body with an explicit Content-Type
// (default text/plain). The router parses `text/plain` (literal, line by
// line) and `application/pdf` (heuristic extraction, confidence-scored,
// civiccast/agenda/pdf_import.py) and refuses anything else with 415.

const AGENDAS = '/api/staff/agendas'

/** GET /api/staff/agendas — list station agendas; optional status filter. */
export function listMeetingAgendas(
  params: { status?: 'draft' | 'published' | null } = {},
): Promise<MeetingAgenda[]> {
  const qs = new URLSearchParams()
  if (params.status) qs.set('status', params.status)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<MeetingAgenda[]>(`${AGENDAS}${suffix}`)
}

/** GET /api/staff/agendas/{agenda_id} — 404 if unknown. */
export function getMeetingAgenda(agendaId: string): Promise<MeetingAgenda> {
  return request<MeetingAgenda>(`${AGENDAS}/${encodeURIComponent(agendaId)}`)
}

/** POST /api/staff/agendas — create one (always draft per spec §5 / DC-1). */
export function createMeetingAgenda(payload: MeetingAgendaInput): Promise<MeetingAgenda> {
  return request<MeetingAgenda>(AGENDAS, { method: 'POST', body: payload })
}

/**
 * PATCH /api/staff/agendas/{agenda_id} — patch semantics (absent unchanged,
 * explicit null clears). Send `{status: 'published'}` to publish; the server
 * rejects with 422 when the agenda has zero items, and the screen surfaces
 * the message verbatim.
 */
export function patchMeetingAgenda(
  agendaId: string,
  payload: MeetingAgendaUpdate,
): Promise<MeetingAgenda> {
  return request<MeetingAgenda>(`${AGENDAS}/${encodeURIComponent(agendaId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

/**
 * DELETE /api/staff/agendas/{agenda_id} — 204 on success. Cascades every item
 * under the agenda in a single store transaction; the UI surfaces a two-step
 * confirm so the operator is warned about the cascade.
 */
export function deleteMeetingAgenda(agendaId: string): Promise<void> {
  return request<void>(`${AGENDAS}/${encodeURIComponent(agendaId)}`, { method: 'DELETE' })
}

/**
 * GET /api/staff/agendas/{agenda_id}/items — list items for one agenda.
 * `order_by='order'` (default) for the editor / sidebar; `order_by='timecode'`
 * for the player chapter list.
 */
export function listAgendaItems(
  agendaId: string,
  params: { order_by?: 'order' | 'timecode' } = {},
): Promise<AgendaItem[]> {
  const qs = new URLSearchParams()
  if (params.order_by) qs.set('order_by', params.order_by)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request<AgendaItem[]>(
    `${AGENDAS}/${encodeURIComponent(agendaId)}/items${suffix}`,
  )
}

/** POST /api/staff/agendas/{agenda_id}/items — create one item. */
export function createAgendaItem(
  agendaId: string,
  payload: AgendaItemInput,
): Promise<AgendaItem> {
  return request<AgendaItem>(
    `${AGENDAS}/${encodeURIComponent(agendaId)}/items`,
    { method: 'POST', body: payload },
  )
}

/** PATCH /api/staff/agendas/{agenda_id}/items/{item_id} — patch semantics. */
export function patchAgendaItem(
  agendaId: string,
  itemId: string,
  payload: AgendaItemUpdate,
): Promise<AgendaItem> {
  return request<AgendaItem>(
    `${AGENDAS}/${encodeURIComponent(agendaId)}/items/${encodeURIComponent(itemId)}`,
    { method: 'PATCH', body: payload },
  )
}

/** DELETE /api/staff/agendas/{agenda_id}/items/{item_id} — 204 on success. */
export function deleteAgendaItem(agendaId: string, itemId: string): Promise<void> {
  return request<void>(
    `${AGENDAS}/${encodeURIComponent(agendaId)}/items/${encodeURIComponent(itemId)}`,
    { method: 'DELETE' },
  )
}

/**
 * POST /api/staff/agendas/{agenda_id}/sync-from-chapters — seed items from
 * the meeting asset's chapter markers (DC-3). Idempotent: an existing item
 * at the same (agenda_id, order) is skipped — operator edits survive a
 * re-sync. Returns the items the service wrote on this call (the
 * "newly-seeded count" for the success banner).
 */
export function syncAgendaFromChapters(agendaId: string): Promise<AgendaItem[]> {
  return request<AgendaItem[]>(
    `${AGENDAS}/${encodeURIComponent(agendaId)}/sync-from-chapters`,
    { method: 'POST' },
  )
}

/**
 * POST /api/staff/agendas/{agenda_id}/import — parse a doc and seed items.
 *
 * `doc` is either the pasted text (`string`, `contentType` defaults to
 * `text/plain`) or an uploaded PDF's raw bytes (pass the `File`/`Blob`
 * directly with `contentType: 'application/pdf'` — a `File` already
 * satisfies `fetch`'s `BodyInit`, no manual read/convert needed). DOCX and
 * anything else return 415 Unsupported Media Type. A readable PDF with no
 * recognizable items returns 422 — the caller surfaces that message as-is.
 *
 * Raw-body POST — we cannot use the JSON `request<T>` helper here because
 * that one always sets Content-Type to application/json and JSON.stringifies
 * the body. We inline a small fetch instead and re-use the same auth
 * headers, abort behaviour, and error parsing as the main helper.
 */
export async function importAgendaFromDoc(
  agendaId: string,
  doc: string | Blob,
  contentType: string = 'text/plain',
): Promise<AgendaItem[]> {
  const staffToken = runtimeStaffToken()
  const setupNonce = runtimeSetupNonce()
  if (setupNonce && typeof window !== 'undefined') {
    window.sessionStorage.setItem('civiccast.setupNonce', setupNonce)
  }
  const res = await fetch(
    `${runtimeApiBase()}${AGENDAS}/${encodeURIComponent(agendaId)}/import`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': contentType,
        ...(staffToken ? { Authorization: `Bearer ${staffToken}` } : {}),
        ...(setupNonce ? { 'X-CivicCast-Setup-Nonce': setupNonce } : {}),
      },
      body: doc,
    },
  )
  if (!res.ok) {
    let detailString: string | undefined
    try {
      const parsed = (await res.json()) as { detail?: unknown }
      const raw = parsed?.detail
      if (typeof raw === 'string') detailString = raw
      else if (raw) detailString = JSON.stringify(raw)
    } catch {
      // non-JSON body — leave detail undefined
    }
    throw new ApiError(
      `Request failed: ${res.status} ${res.statusText}`,
      res.status,
      detailString,
      undefined,
      responseRetryAfterSeconds(res),
    )
  }
  return (await res.json()) as AgendaItem[]
}

// --- S26 Subscription paywall (operator config UI, slice 4) ----------------
//
// Hand-written types pending the next regen of api.generated.ts (the backend
// agent owns that file). Shapes mirror civiccast/paywall/models.py exactly —
// PaywallConfig / PaywallTier / AccessGrant + the input shapes for the
// upsert/patch/grant endpoints. NO PAN/card data is ever surfaced here:
// Stripe-hosted Checkout + Customer Portal handle every card touchpoint
// (DC-4). The operator console only configures tiers (Stripe price ids),
// flips the master enable toggle, rotates the signing secret, and issues
// comp grants by email.

export type PaywallProvider = 'stripe' | 'mock'
export type PaywallScopeKind = 'asset' | 'series' | 'all'
export type PaywallGrantedVia = 'subscription' | 'comp' | 'magic_link'

export interface PaywallTier {
  tier_id: string
  name: string
  price_id: string
  interval: 'month' | 'year'
}

export interface PaywallConfig {
  config_id: string
  station_id: string
  enabled: boolean
  provider: PaywallProvider
  tiers: PaywallTier[]
  signing_secret: string | null
  created_at: string
  updated_at: string
}

export interface PaywallConfigInput {
  config_id: string
  station_id: string
  enabled: boolean
  provider: PaywallProvider
  tiers: PaywallTier[]
  signing_secret: string | null
}

export interface PaywallConfigUpdate {
  enabled?: boolean | null
  provider?: PaywallProvider | null
  tiers?: PaywallTier[] | null
  signing_secret?: string | null
}

export interface AccessGrant {
  grant_id: string
  station_id: string
  email: string
  scope_kind: PaywallScopeKind
  scope_id: string
  granted_via: PaywallGrantedVia
  subscription_id?: string | null
  magic_link_token_id?: string | null
  expires_at?: string | null
  created_at: string
  updated_at: string
}

export interface AccessGrantInput {
  grant_id: string
  station_id: string
  email: string
  scope_kind: PaywallScopeKind
  scope_id: string
  granted_via: PaywallGrantedVia
  subscription_id?: string | null
  magic_link_token_id?: string | null
  expires_at?: string | null
}

const PAYWALL = '/api/staff/paywall'

/** GET /api/staff/paywall/config — returns the station's config or 404. The
 * screen treats the 404 as "no config yet; render an empty default". */
export function getPaywallConfig(): Promise<PaywallConfig> {
  return request<PaywallConfig>(`${PAYWALL}/config`)
}

/** PUT /api/staff/paywall/config — upsert. The screen sends the full config
 * (toggle + provider + tiers + signing_secret) on every save. */
export function upsertPaywallConfig(payload: PaywallConfigInput): Promise<PaywallConfig> {
  return request<PaywallConfig>(`${PAYWALL}/config`, { method: 'PUT', body: payload })
}

/** PATCH /api/staff/paywall/config/{config_id} — partial update; absent
 * keys unchanged. The screen uses PUT for ordinary saves and reserves PATCH
 * for future targeted edits (signing-secret rotation alone, for example). */
export function updatePaywallConfig(
  configId: string,
  payload: PaywallConfigUpdate,
): Promise<PaywallConfig> {
  return request<PaywallConfig>(`${PAYWALL}/config/${encodeURIComponent(configId)}`, {
    method: 'PATCH',
    body: payload,
  })
}

/** DELETE /api/staff/paywall/config/{config_id} — 204 on success. The screen
 * wraps this in a two-step confirm with a "this disables the paywall and
 * invalidates magic links" warning. */
export function deletePaywallConfig(configId: string): Promise<void> {
  return request<void>(`${PAYWALL}/config/${encodeURIComponent(configId)}`, {
    method: 'DELETE',
  })
}

/** POST /api/staff/paywall/grants — issue a comp / staff grant for an email.
 * granted_via is operator-controlled but the UI defaults to "comp" since
 * subscription/magic_link grants are created server-side (webhook / redeem). */
export function issueCompGrant(payload: AccessGrantInput): Promise<AccessGrant> {
  return request<AccessGrant>(`${PAYWALL}/grants`, { method: 'POST', body: payload })
}

/** DELETE /api/staff/paywall/grants/{grant_id} — 204 on success. Revoke a
 * comp grant; the screen uses a single-click delete here since each grant
 * row is small and easy to re-issue (no cascade). */
export function deleteAccessGrant(grantId: string): Promise<void> {
  return request<void>(`${PAYWALL}/grants/${encodeURIComponent(grantId)}`, {
    method: 'DELETE',
  })
}

// --- S21 Scheduled recording (operator UI, slice 4) -----------------------
//
// Hand-written types pending the next regen of api.generated.ts (the backend
// agent owns that file). Shapes mirror civiccast/recording/models.py
// (slice 1, shipped) and the router contract (slice 3, parallel). The screen
// configures forward-scheduled captures of live inputs (SDI/HDMI/NDI) or
// network streams (RTSP/SRT/HLS/RTMP/MPEG-TS), and tracks the materialized
// recording-job history. The production backend wires the capture pipeline,
// asset finalizer, alert sink, and scheduled-recording worker; the UI calls
// the same API for Record Now and Stop.

export type RecordingSourceKind =
  | 'sdi'
  | 'hdmi'
  | 'ndi'
  | 'rtsp'
  | 'srt'
  | 'hls'
  | 'rtmp'
  | 'mpegts'

export interface RecordingSource {
  kind: RecordingSourceKind
  input_id?: string
  uri?: string
}

export type RecurrenceSpec =
  | { kind: 'one_shot'; start: string }
  | { kind: 'weekly'; weekdays: number[]; time_hhmm: string }

export interface RecordingSchedule {
  schedule_id: string
  station_id: string
  name: string
  source: RecordingSource
  recurrence: RecurrenceSpec
  duration_seconds: number
  encoder_profile: string
  loudness_regime: string
  target_series: string | null
  custom_field_values: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface RecordingScheduleInput {
  schedule_id: string
  station_id: string
  name: string
  source: RecordingSource
  recurrence: RecurrenceSpec
  duration_seconds: number
  encoder_profile: string
  loudness_regime: string
  target_series: string | null
  custom_field_values: Record<string, unknown>
  enabled: boolean
}

export interface RecordingScheduleUpdate {
  name?: string | null
  source?: RecordingSource | null
  recurrence?: RecurrenceSpec | null
  duration_seconds?: number | null
  encoder_profile?: string | null
  loudness_regime?: string | null
  target_series?: string | null
  custom_field_values?: Record<string, unknown> | null
  enabled?: boolean | null
}

export type RecordingJobState =
  | 'scheduled'
  | 'arming'
  | 'recording'
  | 'finalizing'
  | 'done'
  | 'failed'
  | 'skipped'

export interface RecordingJob {
  job_id: string
  station_id: string
  schedule_id: string | null
  planned_start: string
  planned_end: string
  state: RecordingJobState
  started_at: string | null
  ended_at: string | null
  asset_id: string | null
  bytes_written: number
  failure_reason: string | null
  source_snapshot: RecordingSource
  encoder_profile: string
  loudness_regime: string
  target_series: string | null
  custom_field_values: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface RecordingJobsQuery {
  state?: RecordingJobState
  schedule_id?: string
  limit?: number
}

const RECORDING = '/api/staff/recording'

/** GET /api/staff/recording/schedules — every schedule for the station. The
 * UI sorts by name client-side; the backend's order is "as inserted". */
export function listRecordingSchedules(): Promise<RecordingSchedule[]> {
  return request<RecordingSchedule[]>(`${RECORDING}/schedules`)
}

/** POST /api/staff/recording/schedules — create a new forward-scheduled
 * capture. The screen converts its "HH:MM:SS" duration field to seconds
 * before calling. */
export function createRecordingSchedule(
  payload: RecordingScheduleInput,
): Promise<RecordingSchedule> {
  return request<RecordingSchedule>(`${RECORDING}/schedules`, {
    method: 'POST',
    body: payload,
  })
}

/** GET /api/staff/recording/schedules/{id} — single fetch; the screen
 * doesn't currently use this directly (the list endpoint is cheap enough)
 * but the helper ships so a future detail view doesn't need to refactor. */
export function getRecordingSchedule(scheduleId: string): Promise<RecordingSchedule> {
  return request<RecordingSchedule>(
    `${RECORDING}/schedules/${encodeURIComponent(scheduleId)}`,
  )
}

/** PATCH /api/staff/recording/schedules/{id} — partial edit; absent keys
 * unchanged. Used for the inline-edit flow. */
export function updateRecordingSchedule(
  scheduleId: string,
  payload: RecordingScheduleUpdate,
): Promise<RecordingSchedule> {
  return request<RecordingSchedule>(
    `${RECORDING}/schedules/${encodeURIComponent(scheduleId)}`,
    { method: 'PATCH', body: payload },
  )
}

/** DELETE /api/staff/recording/schedules/{id} — 204 on success. Two-step
 * confirm in the UI. Deleting a schedule does NOT delete the jobs it
 * already produced (those live on as audit history). */
export function deleteRecordingSchedule(scheduleId: string): Promise<void> {
  return request<void>(`${RECORDING}/schedules/${encodeURIComponent(scheduleId)}`, {
    method: 'DELETE',
  })
}

/** POST /api/staff/recording/schedules/{id}/record-now — ad-hoc one-shot. */
export function recordNow(scheduleId: string): Promise<RecordingJob> {
  return request<RecordingJob>(
    `${RECORDING}/schedules/${encodeURIComponent(scheduleId)}/record-now`,
    { method: 'POST' },
  )
}

/** GET /api/staff/recording/jobs — history + live status. Optional filters
 * for state, schedule, and a hard limit so the table stays bounded. */
export function listRecordingJobs(query: RecordingJobsQuery = {}): Promise<RecordingJob[]> {
  const params = new URLSearchParams()
  if (query.state) params.set('state', query.state)
  if (query.schedule_id) params.set('schedule_id', query.schedule_id)
  if (query.limit != null) params.set('limit', String(query.limit))
  const qs = params.toString()
  return request<RecordingJob[]>(`${RECORDING}/jobs${qs ? `?${qs}` : ''}`)
}

/** POST /api/staff/recording/jobs/{id}/stop — interrupt a running capture.
 * The engine finalizes whatever's been written; the resulting job moves to
 * "done" (with partial bytes) or "failed" (if there's nothing to flush). */
export function stopRecordingJob(jobId: string): Promise<RecordingJob> {
  return request<RecordingJob>(
    `${RECORDING}/jobs/${encodeURIComponent(jobId)}/stop`,
    { method: 'POST' },
  )
}
