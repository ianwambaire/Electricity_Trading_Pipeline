// Protocol errors can contain callback data. Show only fixed, actionable messages.
export function authErrorMessage(error: unknown): string {
  const generic='Sign-in could not be completed or the session could not be renewed. Start again using the button below.'
  if(!error||typeof error!=='object')return generic
  const value=error as {error?:unknown;error_description?:unknown;message?:unknown}
  if(value.error==='invalid_scope'||(value.error==='invalid_request'&&typeof value.error_description==='string'&&value.error_description.includes('Client is not allowed to request these scopes')))return 'The sign-in provider did not accept the requested account permissions. Contact the application administrator.'
  if(value.error==='access_denied')return 'Sign-in was declined. Try again when you are ready.'
  if(value.error==='login_required'||value.error==='interaction_required')return 'Your session needs a new sign-in. Continue below.'
  const message=typeof value.message==='string'?value.message.toLowerCase():''
  if(message.includes('no matching state'))return 'This sign-in request has expired or was already used. Start a new sign-in below.'
  if(message.includes('nonce'))return 'Sign-in verification could not be completed. Start a new sign-in below.'
  if(message.includes('fetch')||message.includes('network')||message.includes('timeout'))return 'The sign-in service could not be reached. Check your connection and try again.'
  return generic
}
