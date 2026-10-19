import test from 'node:test'
import assert from 'node:assert/strict'
import { decision, safeAlias, activeCapacity } from './lifecycle.mjs'

test('automatically rebuilds socket after login restartRequested only', () => {
  assert.equal(decision({reason:515,restartRequired:515}), 'restart')
  assert.equal(decision({reason:401,restartRequired:515}), 'stop')
  assert.equal(decision({reason:515,restartRequired:515,wasStopped:true}), 'stop')
  assert.equal(decision({reason:515,restartRequired:515,retries:5}), 'stop')
  assert.equal(decision({reason:428,restartRequired:515}), 'restart')
  assert.equal(decision({reason:408,restartRequired:515,retries:4}), 'restart')
  assert.equal(decision({reason:503,restartRequired:515}), 'restart')
  assert.equal(decision({reason:500,restartRequired:515}), 'stop')
  assert.equal(decision({reason:401,restartRequired:515,retries:0}), 'stop')
})
test('validates account aliases', () => {
  assert.equal(safeAlias('wa_01'), true)
  assert.equal(safeAlias('../auth'), false)
  assert.equal(safeAlias('a'.repeat(65)), false)
  assert.equal(safeAlias('wa/one'), false)
})
test('enforces active session cap', () => {
  assert.equal(activeCapacity(6,7), true)
  assert.equal(activeCapacity(7,7), false)
  assert.equal(activeCapacity(0,8), false)
  assert.equal(activeCapacity(0,0), false)
})
