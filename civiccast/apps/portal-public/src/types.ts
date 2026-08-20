// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
// Shared public-portal API types. Field shapes mirror the FastAPI public
// response models; keep them in lockstep with the backend.

export interface AssetMetadata {
  asset_id: string
  title: string
  description: string | null
  // #107 option b: meeting-body category tag; null = untagged.
  meeting_body: string | null
  manifest_url: string
  poster_url: string | null
  duration_seconds: number | null
  published_at: string | null
  // S22: exposed custom-field values (searchable && api_exposed only — the
  // public-exposure boundary is enforced server-side; the client renders only
  // what arrives). Absent on /api/public/assets, present on /api/public/search.
  custom_fields?: PublicCustomFieldValue[]
}

// S22: one exposed custom-field value on a public asset (key + label + canonical
// value). Mirrors the FastAPI PublicCustomFieldValue model.
export interface PublicCustomFieldValue {
  key: string
  label: string
  value: string
}

export interface ScheduleItem {
  id: string
  asset_id: string
  asset_title: string | null
  channel_id: string
  mode: 'premiere' | 'embargo'
  state: 'scheduled' | 'cancelled' | 'published'
  scheduled_at: string
  duration_seconds: number | null
}

export interface PublicGuideEntry {
  channel_id: string
  title: string
  starts_at: string
  duration_seconds: number | null
}

export interface PortalChannelInfo {
  channel_id: string
  branding: { display_name: string }
}

export interface PortalStationConfig {
  channels: PortalChannelInfo[]
}

export interface PublicLiveStatus {
  state: 'offline' | 'on_air' | string
  live_session_id: string | null
  channel_id: string | null
  title: string | null
  started_at: string | null
  manifest_url: string | null
}

export interface IdlePage {
  channel_id: string
  title: string
  message: string
  next_broadcast_label: string
  action_label: string
  action_url: string
}

export interface EmergencyOverlay {
  overlay_id: string
  severity: 'watch' | 'warning' | 'emergency'
  title: string
  message: string
  instructions: string
  cellular_fallback_enabled: boolean
  aria_live: 'polite' | 'assertive'
}

export interface LoadError {
  surface: string
  message: string
}

export interface SubscriptionPublicResponse {
  status: 'pending_confirmation' | 'confirmed' | 'unsubscribed'
  message: string
  next_step: string
  confirmation_token: string | null
  unsubscribe_token: string | null
}

export interface SubscriptionActionResponse {
  status: 'pending_confirmation' | 'confirmed' | 'unsubscribed'
  message: string
  next_step: string
}

export interface SubmissionAgreementCatalog {
  agreement_id: string
  version: string
  title: string
  summary: string
  effective_at: string
}

export interface SubmissionMediaReference {
  upload_ref: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string | null
}

export interface ContributorSubmissionReceipt {
  submission_id: string
  receipt_token: string
  state: string
  status_url: string
}

export interface PublicSubmissionStatus {
  submission_id: string
  title: string
  state: string
  producer_name: string
  updated_at: string
  status_message: string
  decline_reason: string | null
}

// S25: one published agenda item exposed by GET /api/public/agendas/{asset_id}.
// Mirrors the FastAPI PublicAgendaItem model.
export interface PublicAgendaItem {
  item_id: string
  order: number
  number: string | null
  title: string
  video_timecode_s: number | null
  doc_anchor: string | null
}

// S25: a published meeting agenda. Only ever returned for status="published";
// drafts surface as 404 on the public endpoint.
export interface PublicMeetingAgenda {
  agenda_id: string
  meeting_asset_id: string
  source_doc_url: string | null
  items: PublicAgendaItem[]
}
