export interface MfaSetup { secret: string; setup_ticket: string; expires_in: number }
export function parseMfaSetup(value: unknown): MfaSetup {
  if (!value || typeof value !== 'object') throw Error('Invalid setup response')
  const v=value as Record<string,unknown>
  if(typeof v.secret!=='string'||!/^[A-Z2-7]{16,128}$/.test(v.secret)
    ||typeof v.setup_ticket!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(v.setup_ticket)
    ||typeof v.expires_in!=='number'||!Number.isInteger(v.expires_in)||v.expires_in<1||v.expires_in>300)throw Error('Invalid setup response')
  return {secret:v.secret,setup_ticket:v.setup_ticket,expires_in:v.expires_in}
}
export function parseMfaAction(value: unknown): {status: 'mfa_enabled'|'setup_cancelled'} {
  if(!value||typeof value!=='object'||!('status' in value)||(value.status!=='mfa_enabled'&&value.status!=='setup_cancelled'))throw Error('Invalid MFA response')
  return {status:value.status}
}
export function validMfaCode(value:string) { return /^[0-9]{6}$/.test(value) }
