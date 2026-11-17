import { test } from 'node:test'
import assert from 'node:assert/strict'
import { productionConfig } from '../build/productionConfig.ts'
const env = {
 VITE_COGNITO_AUTHORITY:'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_OfflineTest',
 VITE_COGNITO_DOMAIN:'https://offline-test.auth.us-east-1.amazoncognito.com',
 VITE_COGNITO_CLIENT_ID:'offlineclient',
 VITE_COGNITO_REDIRECT_URI:'https://powerflow.example.test/auth/callback',
 VITE_COGNITO_POST_LOGOUT_REDIRECT_URI:'https://powerflow.example.test/',
}
test('release config is explicit, same-origin and deterministic; API stays /api',()=>{
 const a=productionConfig(env,'https://powerflow.example.test')
 assert.deepEqual(a,productionConfig(env,'https://powerflow.example.test'))
 assert.equal(a.releaseEligible,true);assert.equal(a.apiBase,'/api')
 assert.equal(a.publicConfigSha256.length,64)
 assert.equal(productionConfig(env).releaseEligible,false)
})
test('release rejects localhost, wrong callbacks, missing identity and sensitive public keys',()=>{
 for(const origin of ['http://localhost:5175','https://localhost','https://127.0.0.1','https://powerflow.example.test/']) assert.throws(()=>productionConfig(env,origin))
 assert.throws(()=>productionConfig({...env,VITE_COGNITO_REDIRECT_URI:'http://localhost:5175/auth/callback'},'https://powerflow.example.test'))
 assert.throws(()=>productionConfig({},'https://powerflow.example.test'))
 assert.throws(()=>productionConfig({...env,VITE_COGNITO_CLIENT_SECRET:'synthetic-test-only'},'https://powerflow.example.test'))
})
