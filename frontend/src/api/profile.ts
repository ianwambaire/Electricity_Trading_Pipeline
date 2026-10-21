export interface AccountProfile {
  name: string | null
  email: string | null
  email_verified: boolean | null
  preferred_username: string | null
  role: 'Admin' | 'Analyst'
  connected_providers: 'Google'[]
  name_editable: boolean
  preferred_username_editable: true
  email_editable: false
  password_configured: boolean | null
  mfa_management: 'not_enabled'
}
export const accountErrorMessages: Record<string, string> = {
  ACCOUNT_RECONNECT_REQUIRED: 'Sign in again to enable account settings.',
  FRESH_SIGN_IN_REQUIRED: 'Confirm your identity with a fresh sign-in before signing out across devices.',
  ACCOUNT_UNAVAILABLE: 'Account services are temporarily unavailable. Please try again.',
  ACCOUNT_RECOVERY_REQUIRED: 'Open sign-in options to recover or confirm your account.',
  ACCOUNT_RATE_LIMITED: 'Too many attempts. Wait a moment before trying again.',
  INCORRECT_PASSWORD: 'Your current password was not accepted. Please try again.',
  PASSWORD_POLICY: 'Use at least 8 characters, including uppercase and lowercase letters, a number and a symbol. Recent passwords may not be reused.',
  INVALID_ACCOUNT_INPUT: 'Check the form fields and try again.',
  NAME_MANAGED_BY_PROVIDER: 'Your display name is managed by your connected sign-in provider.',
  PASSWORD_UNAVAILABLE: 'A Cognito password is not confirmed for this account. Use your sign-in provider for password management.',
  ATTRIBUTE_NOT_WRITABLE: 'Your sign-in provider does not permit this profile change. Your changes were not saved.',
  ACTION_UNAVAILABLE: 'This account action is not available with the current settings.',
}
export function parseProfile(value: unknown): AccountProfile {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('Invalid account')
  const v=value as Record<string,unknown>
  const text=(v:unknown)=>{
    if(v===null)return null
    if(typeof v!=='string'||v.length>320||[...v].some(c=>c.charCodeAt(0)<32||c.charCodeAt(0)===127))throw Error('Invalid attribute')
    return v
  }
  if((v.role!=='Admin'&&v.role!=='Analyst')||typeof v.name_editable!=='boolean'||v.preferred_username_editable!==true||v.email_editable!==false||v.mfa_management!=='not_enabled'||!Array.isArray(v.connected_providers)||v.connected_providers.length>1||v.connected_providers.some(p=>p!=='Google')||(v.email_verified!==null&&typeof v.email_verified!=='boolean')||(v.password_configured!==null&&typeof v.password_configured!=='boolean'))throw Error('Invalid account capabilities')
  if(v.connected_providers.includes('Google')&&v.name_editable)throw Error('Conflicting provider capability')
  return {name:text(v.name),email:text(v.email),email_verified:v.email_verified as boolean|null,preferred_username:text(v.preferred_username),role:v.role,connected_providers:v.connected_providers as 'Google'[],name_editable:v.name_editable,preferred_username_editable:true,email_editable:false,password_configured:v.password_configured as boolean|null,mfa_management:'not_enabled'}
}
export function parseAccountAction(value: unknown): {status:string} {
  if(!value||typeof value!=='object'||!('status' in value)||!['updated','password_changed','signed_out'].includes(String(value.status)))throw Error('Invalid account result')
  return {status:String(value.status)}
}
export function validateProfileField(value:string):string|null {
  return !value.trim()||value.trim().length>128||[...value].some(c=>c.charCodeAt(0)<32||c.charCodeAt(0)===127)?'Use between 1 and 128 characters, without control characters.':null
}
export function validatePasswordChange(current:string,next:string,confirmation:string):string|null {
  if(!current||current.length>256)return 'Enter your current Cognito password.'
  if(next!==confirmation)return 'The new passwords do not match.'
  if(next.length<8||next.length>256||!/[a-z]/.test(next)||!/[A-Z]/.test(next)||!/[0-9]/.test(next)||!/[\W_]/.test(next))return accountErrorMessages.PASSWORD_POLICY
  return null
}


// ApiError messages are fixed by our central client. Never display arbitrary errors.
export function profileUpdateError(error: unknown): string {
  return error instanceof Error && error.name === 'ApiError' && 'code' in error
    && typeof error.code === 'string' && Object.hasOwn(accountErrorMessages,error.code)
    ? accountErrorMessages[error.code]
    : 'Your changes could not be saved. Please try again.'
}
