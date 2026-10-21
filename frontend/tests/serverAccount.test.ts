import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseAccount } from '../src/api/account.ts'
import { api, ApiError } from '../src/api/client.ts'
import { bindApiSession } from '../src/api/accessToken.ts'

const subject='01234567-89ab-4def-8123-0123456789ab'
test('server account roles require explicit Admin/Analyst and discard unknown credentials',()=>{
 const input={subject,role:'Analyst',email:null,display_name:null,access_token:'do-not-expose',internal_path:'private'}
 assert.deepEqual(parseAccount(input),{subject,role:'Analyst',email:null,display_name:null})
 assert.equal(parseAccount({...input,role:'Admin'}).role,'Admin')
 for(const malformed of [{...input,role:'Administrator'},{...input,subject:'bad'}, {...input,email:'bad\u0000value'}, {...input,role:null}])assert.throws(()=>parseAccount(malformed))
 assert.ok(!JSON.stringify(parseAccount(input)).includes('do-not-expose'))
})
test('account call uses protected endpoint and server role; monitoring never falls back to legacy public routes',async()=>{
 const original=globalThis.fetch
 const cleanup=bindApiSession(()=>'test-access',()=>undefined)
 try {
  globalThis.fetch=async(input,options)=>{
   assert.equal(input,'/api/auth/me')
   assert.equal((options?.headers as Record<string,string>).Authorization,'Bearer test-access')
   return Response.json({subject,role:'Analyst',email:null,display_name:null})
  }
  assert.equal((await api.me()).role,'Analyst')
  const calls:string[]=[]
  globalThis.fetch=async(input)=>{calls.push(String(input));return new Response('internal diagnostic text',{status:403})}
  await assert.rejects(api.vintages(),(e:unknown)=>e instanceof ApiError&&e.status===403&&!e.message.includes('internal'))
  await assert.rejects(api.readiness(),(e:unknown)=>e instanceof ApiError&&e.status===403)
  assert.deepEqual(calls,['/api/admin/monitoring/forecast-vintages','/api/admin/monitoring/exogenous-readiness'])
 } finally {cleanup();globalThis.fetch=original}
})
