import { staffApiRequest } from './client'

export const STAFF_ROLES = [
  'setup_admin',
  'meeting_operator',
  'records_clerk',
  'publish_operator',
  'support_admin',
] as const

export type StaffRole = (typeof STAFF_ROLES)[number]

export interface StaffAccount {
  operator_id: string
  username: string
  display_name: string
  roles: StaffRole[]
  enabled: boolean
  account_type: 'first_admin' | 'staff'
  created_at?: string | null
  updated_at?: string | null
  immutable?: boolean
}

export interface StaffSession {
  session_id: string
  operator_id: string
  operator_display_name: string
  roles: StaffRole[]
  source: string
  issued_at: string
  expires_at: string
  expired: boolean
  current: boolean
}

export interface StaffLoginResult {
  access_token: string
  operator_id: string
  operator_display_name: string
  roles: StaffRole[]
  issued_at: string
  expires_at: string
}

export interface StaffCreatePayload {
  username: string
  display_name: string
  password: string
  roles: StaffRole[]
}

export interface StaffAccountPatch {
  display_name?: string
  roles?: StaffRole[]
  enabled?: boolean
}

export interface StaffAccountsApi {
  listAccounts: () => Promise<StaffAccount[]>
  createAccount: (payload: StaffCreatePayload) => Promise<StaffAccount>
  updateAccount: (operatorId: string, payload: StaffAccountPatch) => Promise<StaffAccount>
  resetPassword: (operatorId: string, newPassword: string) => Promise<void>
  listSessions: () => Promise<StaffSession[]>
  revokeSession: (sessionId: string) => Promise<void>
}

export function loginStaffAccount(username: string, password: string): Promise<StaffLoginResult> {
  return staffApiRequest<StaffLoginResult>('/api/staff/auth/login', {
    method: 'POST',
    body: { username, password },
    includeStaffToken: false,
  })
}

export const staffAccountsApi: StaffAccountsApi = {
  listAccounts: () => staffApiRequest<StaffAccount[]>('/api/staff/auth/accounts'),
  createAccount: (payload) =>
    staffApiRequest<StaffAccount>('/api/staff/auth/accounts', { method: 'POST', body: payload }),
  updateAccount: (operatorId, payload) =>
    staffApiRequest<StaffAccount>(`/api/staff/auth/accounts/${encodeURIComponent(operatorId)}`, {
      method: 'PATCH',
      body: payload,
    }),
  resetPassword: (operatorId, newPassword) =>
    staffApiRequest<void>(`/api/staff/auth/accounts/${encodeURIComponent(operatorId)}/reset-password`, {
      method: 'POST',
      body: { new_password: newPassword },
    }),
  listSessions: () => staffApiRequest<StaffSession[]>('/api/staff/auth/sessions'),
  revokeSession: (sessionId) =>
    staffApiRequest<void>(`/api/staff/auth/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),
}
