import { authErrorMessage } from '../src/auth/authErrorMessage.ts'
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { profileDetails } from '../src/auth/profilePresentation.ts'
import { parseProfile, validateProfileField, validatePasswordChange } from '../src/api/profile.ts'
import { api, ApiError } from '../src/api/client.ts'
import { bindApiSession } from '../src/api/accessToken.ts'
const profile={name:'Test User',email:'person@example.test',email_verified:true,preferred_username:'analyst',role:'Analyst',connected_providers:[],name_editable:true,preferred_username_editable:true,email_editable:false,password_configured:true,mfa_management:'not_enabled'}

test('profile retrieval keeps only human-facing identity and server capabilities',()=>{
 const result=parseProfile({...profile,sub:'internal-id',access_token:'never-display',Username:'internal-username'})
 assert.equal(result.name,'Test User');assert.equal(result.email_verified,true)
 assert.ok(!JSON.stringify(result).includes('internal'));assert.ok(!JSON.stringify(result).includes('never-display'))
 assert.throws(()=>parseProfile({...profile,role:'Administrator'}))
 assert.throws(()=>parseProfile({...profile,mfa_management:'enabled'}))
 assert.throws(()=>parseProfile({...profile,email_editable:true}))
 assert.throws(()=>parseProfile({...profile,name:'bad\u0000value'}))
})
test('Google linkage never implies the presence or absence of a native password',()=>{
 for(const password_configured of [true,false,null]) {
  const result=parseProfile({...profile,connected_providers:['Google'],name_editable:false,password_configured})
  assert.equal(result.password_configured,password_configured)
  assert.equal(result.name_editable,false)
 }
 const identity=profileDetails({name:'Test User',email:'person@example.test',identities:'[{"providerName":"Google","userId":"never-display"}]',sub:'internal-id'})
 assert.equal(identity.googleConnected,true);assert.equal(identity.initials,'TU')
 assert.ok(!JSON.stringify(identity).includes('never-display'));assert.ok(!JSON.stringify(identity).includes('internal-id'))
 assert.equal(profileDetails({}).initials,null)
 assert.equal(profileDetails({identities:'invalid JSON'}).googleConnected,false)
 assert.equal(profileDetails({name:'\u0000secret'}).name,null)
})
test('display names and preferred labels validate without changing sign-in aliases',()=>{
 assert.equal(validateProfileField('Valid Name'),null)
 for(const input of ['', '  ', 'x'.repeat(129), 'bad\nvalue'])assert.ok(validateProfileField(input))
 assert.equal(validateProfileField('José Analyst'),null)
 assert.equal(profileDetails({preferred_username:'profile-label'}).preferredUsername,'profile-label')
})
test('password input validation covers required current password, mismatch and audited policy',()=>{
 assert.equal(validatePasswordChange('OldPassword!1','NewPassword!2','NewPassword!2'),null)
 assert.ok(validatePasswordChange('','NewPassword!2','NewPassword!2'))
 assert.equal(validatePasswordChange('OldPassword!1','NewPassword!2','DifferentPassword!3'),'The new passwords do not match.')
 for(const next of ['short','alllowercase!1','ALLUPPERCASE!1','NoNumbers!','NoSymbols123'])assert.ok(validatePasswordChange('old',next,next))
})
test('account changes use the central authorized client and never accept a target user',async()=>{
 const original=globalThis.fetch;const cleanup=bindApiSession(()=>'fixture-access-token',()=>undefined)
 const seen:{url:string;method:string;body:unknown}[]=[]
 try {
  globalThis.fetch=async(input,opts)=>{
   assert.equal((opts?.headers as Record<string,string>).Authorization,'Bearer fixture-access-token')
   assert.equal(opts?.credentials,'omit')
   seen.push({url:String(input),method:opts?.method??'GET',body:opts?.body?JSON.parse(String(opts.body)):null})
   return Response.json({status:'updated'})
  }
  await api.updateProfile({name:'Changed Name',preferred_username:'changed_label'})
  assert.deepEqual(seen[0],{url:'/api/account/profile',method:'PATCH',body:{name:'Changed Name',preferred_username:'changed_label'}})
  globalThis.fetch=async()=>Response.json(profile)
  assert.equal((await api.accountProfile()).role,'Analyst')
 } finally {cleanup();globalThis.fetch=original}
})
test('known account failures are clear; raw provider messages and submitted secrets never surface',async()=>{
 const original=globalThis.fetch;const cleanup=bindApiSession(()=>'fixture-access-token',()=>undefined)
 try {
  globalThis.fetch=async()=>Response.json({detail:{code:'INCORRECT_PASSWORD',message:'private provider text with password'}},{status:400})
  await assert.rejects(api.changePassword({current_password:'OldPassword!1',new_password:'NewPassword!2'}),(e:unknown)=>e instanceof ApiError&&e.code==='INCORRECT_PASSWORD'&&e.message==='Your current password was not accepted. Please try again.')
  globalThis.fetch=async()=>Response.json({detail:{code:'<script>private</script>',message:'internal credential'}},{status:422})
  await assert.rejects(api.updateProfile({name:'Name'}),(e:unknown)=>e instanceof ApiError&&!e.message.includes('private')&&!e.message.includes('credential'))
 } finally {cleanup();globalThis.fetch=original}
})
test('old sessions reconnect, fresh-sign-in requirements preserve session, revoked sessions expire',async()=>{
 const original=globalThis.fetch;let expired=0;const cleanup=bindApiSession(()=>'fixture-access-token',()=>expired++)
 try {
  globalThis.fetch=async()=>Response.json({detail:{code:'ACCOUNT_RECONNECT_REQUIRED'}},{status:403})
  await assert.rejects(api.accountProfile(),(e:unknown)=>e instanceof ApiError&&e.code==='ACCOUNT_RECONNECT_REQUIRED')
  assert.equal(expired,0)
  globalThis.fetch=async()=>Response.json({detail:{code:'FRESH_SIGN_IN_REQUIRED'}},{status:403})
  await assert.rejects(api.signOutAll(),(e:unknown)=>e instanceof ApiError&&e.code==='FRESH_SIGN_IN_REQUIRED')
  assert.equal(expired,0)
  globalThis.fetch=async()=>new Response('private diagnostic',{status:401})
  await assert.rejects(api.accountProfile(),(e:unknown)=>e instanceof ApiError&&e.status===401&&!e.message.includes('private'))
  assert.equal(expired,1)
 } finally {cleanup();globalThis.fetch=original}
})


test('authentication errors reveal only fixed actionable text',()=>{
 assert.match(authErrorMessage({error:'invalid_scope',message:'private-code'}),/permissions/)
 assert.match(authErrorMessage({error:'access_denied'}),/declined/)
 assert.match(authErrorMessage({message:'No matching state: private-code'}),/expired/)
 assert.match(authErrorMessage({message:'nonce private-code'}),/verification/)
 assert.match(authErrorMessage({message:'network private-code'}),/connection/)
 for(const value of [undefined,{message:'private-code'},{error:'unrecognized',message:'private-code'}]) assert.ok(!authErrorMessage(value).includes('private-code'))
})


test('Cognito authorization scope rejection has a safe specific message',()=>{
 const result=authErrorMessage({error:'invalid_request',error_description:'Client is not allowed to request these scopes private-data'})
 assert.match(result,/permissions/);assert.ok(!result.includes('private-data'))
 assert.ok(!authErrorMessage({error:'invalid_request',error_description:'arbitrary private-data'}).includes('private-data'))
})

test('profile errors preserve safe permission details and reject arbitrary diagnostics',async()=>{
 const {profileUpdateError,accountErrorMessages}=await import('../src/api/profile.ts')
 assert.equal(profileUpdateError(new ApiError('ignored',403,'ATTRIBUTE_NOT_WRITABLE')),accountErrorMessages.ATTRIBUTE_NOT_WRITABLE)
 assert.equal(profileUpdateError(new ApiError('ignored',429,'ACCOUNT_RATE_LIMITED')),accountErrorMessages.ACCOUNT_RATE_LIMITED)
 assert.ok(!profileUpdateError(new Error('private provider diagnostic')).includes('private'))
 assert.ok(!profileUpdateError(new ApiError('private',500,'unknown-code')).includes('private'))
 const original=globalThis.fetch;let expired=0;const cleanup=bindApiSession(()=>'fixture',()=>expired++)
 try {
  globalThis.fetch=async()=>Response.json({detail:{code:'ATTRIBUTE_NOT_WRITABLE',message:'private diagnostic'}},{status:403})
  await assert.rejects(api.updateProfile({name:'Allowed'}),(e:unknown)=>e instanceof ApiError&&e.code==='ATTRIBUTE_NOT_WRITABLE'&&!e.message.includes('private'))
  assert.equal(expired,0)
 }finally{cleanup();globalThis.fetch=original}
})
test('Google-mapped display names cannot be presented as user editable',()=>{
 assert.throws(()=>parseProfile({...profile,connected_providers:['Google'],name_editable:true}))
 assert.equal(parseProfile({...profile,connected_providers:['Google'],name_editable:false}).name_editable,false)
})
