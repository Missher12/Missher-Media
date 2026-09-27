import { describe, expect, it } from 'vitest'
import { runProcess } from '../src/process.js'

describe('bounded child process execution', () => {
  it('preserves argv literally without a shell', async () => {
    const marker = '; echo must-not-run'
    const result = await runProcess(process.execPath, [
      '-e',
      'process.stdout.write(JSON.stringify(process.argv.slice(1)))',
      marker,
    ])

    expect(result.code).toBe(0)
    expect(JSON.parse(result.stdout)).toEqual([marker])
    expect(result.stderr).toBe('')
  })

  it('returns a non-zero exit without rewriting it', async () => {
    const result = await runProcess(process.execPath, ['-e', 'process.exit(7)'])
    expect(result.code).toBe(7)
    expect(result.signal).toBeNull()
  })

  it('stops output above the configured bound', async () => {
    await expect(runProcess(
      process.execPath,
      ['-e', 'process.stdout.write("12345678901")'],
      { maxOutputBytes: 10 },
    )).rejects.toThrow('process_output_too_large')
  })

  it('terminates when the caller aborts', async () => {
    const controller = new AbortController()
    const operation = runProcess(
      process.execPath,
      ['-e', 'setInterval(() => {}, 1000)'],
      { signal: controller.signal, timeoutMs: 5_000 },
    )
    setTimeout(() => controller.abort(), 40)

    await expect(operation).rejects.toThrow('process_aborted')
  })

  it('terminates after the configured timeout', async () => {
    await expect(runProcess(
      process.execPath,
      ['-e', 'setInterval(() => {}, 1000)'],
      { timeoutMs: 40 },
    )).rejects.toThrow('process_timed_out')
  })
  it('force-stops a child that ignores SIGTERM within a bounded grace period', async () => {
    const started = Date.now()
    await expect(runProcess(process.execPath, ['-e',
      'process.on("SIGTERM", () => {}); process.stdout.write("ready"); setInterval(() => {}, 1000)',
    ], { timeoutMs: 500 })).rejects.toThrow('process_timed_out')
    expect(Date.now() - started).toBeLessThan(10000)
  }, 11000)

})

describe('private structured progress transport', () => {
  const event = { schema: 1, phase: 'platform-collection', state: 'completed', platform: 'weibo', completed: 1, requested: 1, elapsed_ms: 429, duration_ms: 429 }
  it('streams a chunked safe event while preserving the final stdout JSON', async () => {
    const progress: unknown[] = []
    const text = `media-missher-progress ${JSON.stringify(event)}\n`
    const result = await runProcess(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(text.slice(0, 25))}); setTimeout(() => { process.stderr.write(${JSON.stringify(text.slice(25))}); process.stdout.write('{"status":"success"}'); }, 15)`], { onProgress: value => { progress.push(value) } })
    expect(progress).toEqual([event])
    expect(JSON.parse(result.stdout)).toEqual({ status: 'success' })
  })
  it('discards unknown, oversized and private events, caps delivery, and ignores callback failure', async () => {
    const progress: unknown[] = []
    const lines = [JSON.stringify({ ...event, uid: 'private' }), JSON.stringify({ ...event, phase: 'private' }), 'x'.repeat(3000), ...Array.from({ length: 200 }, (_, i) => JSON.stringify({ ...event, elapsed_ms: i, duration_ms: 0 }))]
    await runProcess(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(lines.map(line => `media-missher-progress ${line}\n`).join(''))})`], { onProgress: value => { progress.push(value); throw new Error('private-callback') } })
    expect(progress.length).toBeGreaterThan(0)
    expect(progress.length).toBeLessThanOrEqual(128)
    expect(JSON.stringify(progress)).not.toContain('private')
  })
})

it('stops callbacks after cancellation requested by a progress observer', async () => {
  const controller = new AbortController()
  const received: unknown[] = []
  const line = 'media-missher-progress {"schema":1,"phase":"run","state":"started","elapsed_ms":0}\n'
  await expect(runProcess(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(line.repeat(3))}); setInterval(() => process.stderr.write(${JSON.stringify(line)}), 5)`], {
    signal: controller.signal,
    onProgress: event => { received.push(event); controller.abort() },
  })).rejects.toThrow('process_aborted')
  expect(received).toHaveLength(1)
})
