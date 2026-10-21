import { test } from 'node:test'
import assert from 'node:assert/strict'
import { InMemoryWebStorage, OidcClient, User, UserManager } from 'oidc-client-ts'
import { readAuthConfig, safeDestination, cognitoLogoutUrl } from '../src/auth/config.ts'
import { ACCOUNT_SCOPES, accountSigninRequest, oidcSettings } from '../src/auth/oidcSettings.ts'
import { identityFromProfile, sessionUsable, authGateState } from '../src/auth/identity.ts'
import { logoutSession } from '../src/auth/logout.ts'
import { bindApiSession } from '../src/api/accessToken.ts'
import { request, ApiError } from '../src/api/client.ts'

const env={VITE_COGNITO_AUTHORITY:'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool',VITE_COGNITO_DOMAIN:'https://test.auth.us-east-1.amazoncognito.com',VITE_COGNITO_CLIENT_ID:'testpublicclient',VITE_COGNITO_REDIRECT_URI:'http://localhost:5175/auth/callback',VITE_COGNITO_POST_LOGOUT_REDIRECT_URI:'http://localhost:5175/'}
const config=readAuthConfig(env)!
const now=Date.now()
const profile={sub:'01234567-89ab-4def-8123-0123456789ab',iss:config.authority,aud:config.clientId,exp:Math.floor(now/1000)+3600,iat:Math.floor(now/1000),token_use:'id',email:'analyst@example.invalid',email_verified:true,name:'Test-only identity'}
const user={profile,access_token:'test-access-only',expires_at:profile.exp}

test('configuration fails closed; only public SPA settings and exact local callback shape',()=>{
 assert.ok(config)
 assert.equal(readAuthConfig({}),null)
 for(const bad of [{VITE_COGNITO_AUTHORITY:'https://evil.invalid/pool'},{VITE_COGNITO_DOMAIN:'https://example.invalid'},{VITE_COGNITO_REDIRECT_URI:'http://127.0.0.1:5175/auth/callback'},{VITE_COGNITO_REDIRECT_URI:'http://localhost:5175/callback'},{VITE_COGNITO_POST_LOGOUT_REDIRECT_URI:'https://other.invalid/'}])assert.equal(readAuthConfig({...env,...bad}),null)
 assert.ok(!JSON.stringify(config).includes('secret'))
})
test('all seven destinations are preserved, external URLs and callback queries rejected',()=>{
 for(const path of ['/','/analytics','/forecasting','/anomalies','/models','/pipeline','/profile'])assert.equal(safeDestination(path),path)
 for(const path of ['//evil.invalid','https://evil.invalid','/auth/callback?code=sensitive','/profile?token=value',undefined,'/\\evil.invalid'])assert.equal(safeDestination(path),'/')
})
test('protected gate covers restoration, unauthenticated, authenticated, error and expired states',()=>{
 assert.equal(authGateState(true,false,false,false),'loading')
 assert.equal(authGateState(false,false,false,false),'signed-out')
 assert.equal(authGateState(false,false,true,true),'authenticated')
 assert.equal(authGateState(false,false,true,false),'signed-out')
 assert.equal(authGateState(false,true,true,true),'error')
 assert.ok(sessionUsable(user,config,now))
 for(const bad of [null,{...user,expired:true},{...user,expires_at:now/1000-1},{...user,access_token:''},{...user,profile:{...profile,iss:'https://wrong.invalid'}},{...user,profile:{...profile,aud:'wrong-client'}},{...user,profile:{...profile,aud:[config.clientId,'another-client']}},{...user,profile:{...profile,token_use:'access'}},{...user,profile:{...profile,exp:now/1000-1}}])assert.equal(sessionUsable(bad,config,now),false)
})
test('role presentation grants Admin only for exact Cognito group; provider and profile never invented',()=>{
 assert.equal(identityFromProfile(profile).role,'Analyst')
 for(const groups of ['powerflow-admins',['Admin'],['powerflow-admins-evil'],['powerflow-admins',42],null])assert.equal(identityFromProfile({...profile,'cognito:groups':groups}).role,'Analyst')
 assert.equal(identityFromProfile({...profile,'cognito:groups':['powerflow-admins']}).role,'Admin')
 assert.equal(identityFromProfile({...profile,role:'Admin'}).role,'Analyst')
 assert.equal(identityFromProfile({...profile,identities:JSON.stringify([{providerName:'Google'}])}).federatedProvider,'Google identity reported by Cognito')
 assert.equal(identityFromProfile({}).email,null)
 assert.equal(identityFromProfile(profile).accountReference,'01234567…89ab')
 assert.ok(!JSON.stringify(identityFromProfile(profile)).includes('access_token'))
})
test('logout clears local session/transactions before Cognito redirect and never puts tokens in URL',async()=>{
 const order:string[]=[]
 await logoutSession(config,{stopRenew:()=>{order.push('stop')},removeUser:async()=>{order.push('clear-user')},clearTransactions:async()=>{order.push('clear-transactions')},redirect:url=>{order.push('redirect');assert.equal(new URL(url).searchParams.get('logout_uri'),config.logoutUri);assert.equal(new URL(url).searchParams.get('client_id'),config.clientId);assert.ok(!url.includes('token'))}})
 assert.deepEqual(order,['stop','clear-user','clear-transactions','redirect'])
 assert.equal(new URL(cognitoLogoutUrl(config)).pathname,'/logout')
 await assert.rejects(logoutSession(config,{stopRenew:()=>{},removeUser:async()=>{throw Error('storage failure')},clearTransactions:async()=>{},redirect:()=>assert.fail('redirected before clearing')}))
})
test('actual OIDC library creates S256 PKCE + nonce, consumes callback once and rejects unknown state',async()=>{
 const storage=new InMemoryWebStorage()
 const settings=oidcSettings(config,storage)
 assert.equal(settings.response_type,'code');assert.equal(settings.disablePKCE,false)
 assert.equal(settings.scope,'openid email profile');assert.equal(ACCOUNT_SCOPES,'openid email profile aws.cognito.signin.user.admin');assert.equal(settings.client_secret,undefined)
 const metadata={issuer:config.authority,authorization_endpoint:config.domain+'/oauth2/authorize',token_endpoint:config.domain+'/oauth2/token'}
 const client=new OidcClient({...settings,metadata})
 const login=await client.createSigninRequest({nonce:'test-nonce',state:{returnTo:'/anomalies'}})
 const url=new URL(login.url)
 assert.equal(url.searchParams.get('code_challenge_method'),'S256')
 assert.ok(url.searchParams.get('code_challenge'))
 assert.equal(url.searchParams.get('nonce'),'test-nonce')
 const callback=config.redirectUri+'?error=access_denied&state='+url.searchParams.get('state')
 await assert.rejects(client.processSigninResponse(callback))
 await assert.rejects(client.processSigninResponse(callback),/state/i)
 await assert.rejects(client.processSigninResponse(config.redirectUri+'?code=test&state=unknown'),/state/i)
})
test('OIDC session storage restores library User records and removal clears only this app',async()=>{
 const storage=new InMemoryWebStorage();storage.setItem('other-application','keep')
 const manager=new UserManager({...oidcSettings(config,storage),automaticSilentRenew:false})
 const record=new User({...user,id_token:'test-id-never-used-for-api',token_type:'Bearer',scope:'openid email profile'})
 await manager.storeUser(record)
 assert.equal((await manager.getUser())?.profile.sub,profile.sub)
 await manager.removeUser()
 assert.equal(await manager.getUser(),null)
 assert.equal(storage.getItem('other-application'),'keep')
})
test('API receives access token only; 401 ends session, 403 preserves session, errors redact bodies',async()=>{
 const original=globalThis.fetch
 let ended=0;let active=true
 const unbind=bindApiSession(()=>active?user.access_token:null,()=>{ended++;active=false})
 try {
  globalThis.fetch=async(_input,options)=>{assert.equal((options?.headers as Record<string,string>).Authorization,'Bearer test-access-only');return Response.json({ok:true})}
  assert.deepEqual(await request('/health',value=>value),{ok:true})
  globalThis.fetch=async()=>new Response('sensitive operational text',{status:403})
  await assert.rejects(request('/models/summary',value=>value),(error:unknown)=>error instanceof ApiError&&error.status===403&&!error.message.includes('sensitive'))
  assert.equal(ended,0)
  globalThis.fetch=async()=>new Response('private token payload',{status:401})
  await assert.rejects(request('/health',value=>value),/Sign in again/)
  assert.equal(ended,1)
  globalThis.fetch=async(_input,options)=>{assert.equal((options?.headers as Record<string,string>).Authorization,undefined);return Response.json({})}
  await request('/health',value=>value)
 } finally { unbind();globalThis.fetch=original }
})

test('code exchange sends verifier with no client secret; library checks nonce and rejects callback replay',async()=>{
 const original=globalThis.fetch
 const metadata={issuer:config.authority,authorization_endpoint:config.domain+'/oauth2/authorize',token_endpoint:config.domain+'/oauth2/token'}
 const client=new OidcClient({...oidcSettings(config,new InMemoryWebStorage()),metadata})
 const login=await client.createSigninRequest({nonce:'bound-test-nonce',state:{returnTo:'/profile'}})
 const loginUrl=new URL(login.url)
 const encode=(value:unknown)=>Buffer.from(JSON.stringify(value)).toString('base64url')
 let exchanged=0
 let expectedChallenge=loginUrl.searchParams.get('code_challenge')
 try {
  globalThis.fetch=async(input,options)=>{
   assert.equal(String(input),metadata.token_endpoint)
   const body=new URLSearchParams(String(options?.body))
   assert.equal(body.get('grant_type'),'authorization_code')
   assert.equal(body.get('client_id'),config.clientId)
   assert.equal(body.get('client_secret'),null)
   assert.equal(body.get('redirect_uri'),config.redirectUri)
   assert.ok(body.get('code_verifier'))
   const challenge=Buffer.from(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body.get('code_verifier')!))).toString('base64url')
   assert.equal(challenge,expectedChallenge)
   exchanged++
   // Test-only token response. No test identity or tokens ship in the application.
   return Response.json({token_type:'Bearer',expires_in:3600,access_token:'test-access',id_token:[encode({alg:'RS256'}),encode({...profile,nonce:'bound-test-nonce'}),'test-signature'].join('.')})
  }
  const callback=config.redirectUri+'?code=test-code&state='+loginUrl.searchParams.get('state')
  const response=await client.processSigninResponse(callback)
  assert.equal(response.profile.sub,profile.sub)
  assert.deepEqual(response.userState,{returnTo:'/profile'})
  await assert.rejects(client.processSigninResponse(callback),/state/i)
  assert.equal(exchanged,1)
  const second=await client.createSigninRequest({nonce:'different-nonce'})
  expectedChallenge=new URL(second.url).searchParams.get('code_challenge')
  await assert.rejects(client.processSigninResponse(config.redirectUri+'?code=test-code&state='+new URL(second.url).searchParams.get('state')),/nonce/i)
 } finally { globalThis.fetch=original }
})


test('account reconnection explicitly requests four scopes with a fresh PKCE interaction',async()=>{
 const metadata={issuer:config.authority,authorization_endpoint:config.domain+'/oauth2/authorize',token_endpoint:config.domain+'/oauth2/token'}
 const client=new OidcClient({...oidcSettings(config,new InMemoryWebStorage()),metadata})
 const first=accountSigninRequest(),second=accountSigninRequest()
 assert.notEqual(first.nonce,second.nonce)
 assert.equal(first.prompt,'login');assert.deepEqual(first.state,{returnTo:'/profile'})
 const a=new URL((await client.createSigninRequest(first)).url)
 const b=new URL((await client.createSigninRequest(second)).url)
 assert.equal(a.searchParams.get('scope'),ACCOUNT_SCOPES)
 assert.equal(a.searchParams.get('client_id'),config.clientId)
 assert.equal(a.searchParams.get('redirect_uri'),config.redirectUri)
 assert.equal(a.searchParams.get('response_type'),'code')
 assert.equal(a.searchParams.get('code_challenge_method'),'S256')
 assert.equal(a.searchParams.get('prompt'),'login')
 assert.notEqual(a.searchParams.get('state'),b.searchParams.get('state'))
 assert.notEqual(a.searchParams.get('code_challenge'),b.searchParams.get('code_challenge'))
 assert.equal(oidcSettings(config,new InMemoryWebStorage()).scope,'openid email profile')
})
