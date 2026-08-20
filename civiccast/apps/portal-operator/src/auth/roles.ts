import type { StaffIdentityResponse } from '../types/api.generated'

export type OperatorRole =
  NonNullable<StaffIdentityResponse['roles']>[number]

export const ROLE_LABELS: Record<OperatorRole, string> = {
  setup_admin: 'Setup admin',
  meeting_operator: 'Meeting operator',
  records_clerk: 'Records clerk',
  publish_operator: 'Publish operator',
  support_admin: 'Support admin',
}

export function hasOperatorRole(
  identity: StaffIdentityResponse | undefined,
  role: OperatorRole,
): boolean {
  return identity?.roles?.includes(role) ?? false
}
