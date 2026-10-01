/** Core's `PUT /panel/password` (core/vibedpn/api/models.py: PanelPasswordView). */
export type PanelPasswordView = {
  // the panel takes the new password at once; these once the box recreated them
  later: ('adguard' | 'nodeui')[]
}

// The panel password as core/vibedpn/bootstrap.py takes it: bcrypt hashes at most 72 bytes
export const PASSWORD_MIN = 8
export const PASSWORD_MAX_BYTES = 72

export type PasswordProblem = 'current' | 'length' | 'bytes' | 'mismatch'

/**
 * Why the new panel password cannot be sent yet; `null` when it can. Only a hint before sending: core checks the policy
 * again, and the current password itself.
 *
 * @tags password
 */
export const passwordProblem = (current: string, value: string, repeat: string): PasswordProblem | null => {
  if (!current) {
    return 'current'
  }
  if (value.length < PASSWORD_MIN) {
    return 'length'
  }
  if (new TextEncoder().encode(value).length > PASSWORD_MAX_BYTES) {
    return 'bytes'
  }
  return value === repeat ? null : 'mismatch'
}
