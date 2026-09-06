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
    expect(Date.now() - started).toBeLessThan(4000)
  }, 5000)

})
