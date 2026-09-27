import assert from 'node:assert/strict'
import test from 'node:test'
import { parseCli, runCli } from '../bin/media-missher.mjs'

test('capability discovery is a host-neutral command without factories', async () => {
  assert.equal(parseCli(['capabilities']).command, 'capabilities')
  const { value, exitCode } = await runCli(['capabilities'], { env: { HOME: '/no-such-media-capability-home', PATH: '' } })
  assert.equal(exitCode, 0)
  assert.deepEqual(Object.keys(value.backends), ['cdp'])
  assert.notEqual(value.backends.cdp.status, 'ready')
  assert.equal(value.coreProtocolVersion, 1)
})

test('removed computer-use command refuses before resolving paths or factories', async () => {
  for (const action of ['prepare', 'ingest', 'status', 'finalize', 'cancel']) {
    const { value, exitCode } = await runCli(['computer-use', action], { env: { HOME: '/no-such-media-capability-home', PATH: '' } })
    assert.equal(exitCode, 2)
    assert.equal(value.error, 'cli_arguments_invalid')
  }
})

test('retired collection backend fails before opening paths or loading a runtime', async () => {
  const { value, exitCode } = await runCli(
    ['collect', '--platforms', 'x', '--backend', 'computer_use'],
    { env: { HOME: '/no-such-media-capability-home', PATH: '' } },
  )
  assert.equal(exitCode, 2)
  assert.equal(value.error, 'backend-retired-computer-use')
})
