import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bindApiSession, captureApiSession } from '../src/api/accessToken.ts'
import { authErrorMessage } from '../src/auth/authErrorMessage.ts'

test('late unauthorized response cannot expire a replacement session', () => {
  let old = 0, fresh = 0
  const cleanOld = bindApiSession(() => 'old-fixture', () => old++)
  const pending = captureApiSession()
  const clean = bindApiSession(() => 'new-fixture', () => fresh++)
  cleanOld()
  pending.reject()
  assert.equal(old, 0); assert.equal(fresh, 0)
  const active = captureApiSession()
  active.reject(); active.reject()
  assert.equal(fresh, 1)
  assert.deepEqual(captureApiSession().headers, {})
  clean()
})
test('late 401 cannot invalidate a renewed token in the same binding', () => {
  let token = 'before', expired = 0
  const clean = bindApiSession(() => token, () => expired++)
  const pending = captureApiSession()
  token = 'after'; pending.reject()
  assert.equal(expired, 0)
  clean()
})
test('protocol errors use safe actionable messages without provider descriptions', () => {
  for (const error of ['invalid_grant', 'temporarily_unavailable', 'consent_required']) {
    const message = authErrorMessage({ error, error_description: 'private-fixture' })
    assert.ok(!message.includes('private-fixture'))
    assert.ok(message.includes('sign-in') || message.includes('Sign in'))
  }
})
