import { spawn, type SpawnOptions } from 'node:child_process'

export interface ProcessOptions {
  cwd?: string
  env?: NodeJS.ProcessEnv
  signal?: AbortSignal
  timeoutMs?: number
  maxOutputBytes?: number
  onProgress?: (event: ProgressEvent) => void | Promise<void>
}

export interface ProcessResult {
  code: number | null
  signal: NodeJS.Signals | null
  stdout: string
  stderr: string
}

export const PROGRESS_PHASES = ['controller-preflight', 'engine', 'browser-preflight', 'platform-collection', 'validation', 'output', 'run'] as const
export interface ProgressEvent {
  schema: 1
  phase: typeof PROGRESS_PHASES[number]
  state: 'started' | 'updated' | 'completed' | 'failed' | 'cancelled'
  elapsed_ms: number
  duration_ms?: number
  platform?: 'bilibili' | 'xhs' | 'douyin' | 'weibo' | 'x'
  completed?: number
  requested?: number
}

/** The only progress data allowed to leave a subprocess. Never project extra fields. */
export function parseProgressEvent(value: unknown): ProgressEvent | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined
  const event = value as Record<string, unknown>
  const keys = ['schema', 'phase', 'state', 'elapsed_ms']
  if (event.phase === 'platform-collection') keys.push('platform', 'completed', 'requested')
  if (['completed', 'failed', 'cancelled'].includes(event.state as string)) keys.push('duration_ms')
  if (Object.keys(event).sort().join(',') !== keys.sort().join(',') || event.schema !== 1
    || !PROGRESS_PHASES.includes(event.phase as ProgressEvent['phase'])
    || !['started', 'updated', 'completed', 'failed', 'cancelled'].includes(event.state as string)) return undefined
  for (const key of ['elapsed_ms', 'duration_ms', 'completed', 'requested']) {
    if (event[key] !== undefined && (!Number.isSafeInteger(event[key]) || (event[key] as number) < 0
      || (event[key] as number) > (['completed', 'requested'].includes(key) ? 10000 : 604800000))) return undefined
  }
  if (event.duration_ms !== undefined && (event.duration_ms as number) > (event.elapsed_ms as number)) return undefined
  if (event.phase === 'platform-collection' && !['bilibili', 'xhs', 'douyin', 'weibo', 'x'].includes(event.platform as string)) return undefined
  return { ...event } as unknown as ProgressEvent
}

/** Chunk-safe optional stderr parser, capped independently of total subprocess output. */
export function createProgressParser(receive: NonNullable<ProcessOptions['onProgress']>): (chunk: Buffer) => void {
  const prefix = 'media-missher-progress '
  let pending = Buffer.alloc(0)
  let discarding = false
  let delivered = 0
  let lastElapsed = -1
  let lastUpdate = -Infinity
  return (chunk: Buffer): void => {
    let start = 0
    while (start < chunk.length) {
      const newline = chunk.indexOf(10, start)
      const end = newline === -1 ? chunk.length : newline
      const part = chunk.subarray(start, end)
      if (!discarding) {
        if (pending.length + part.length > 512) { pending = Buffer.alloc(0); discarding = true }
        else pending = Buffer.concat([pending, part])
      }
      start = end + 1
      if (newline === -1) return
      if (!discarding && delivered < 128) {
        const line = pending.toString('utf8')
        if (line.startsWith(prefix)) {
          try {
            const event = parseProgressEvent(JSON.parse(line.slice(prefix.length)))
            const now = performance.now()
            if (event !== undefined && event.elapsed_ms >= lastElapsed && (event.state !== 'updated' || now - lastUpdate >= 250)) {
              delivered += 1
              lastElapsed = event.elapsed_ms
              if (event.state === 'updated') lastUpdate = now
              try { Promise.resolve(receive(event)).catch(() => {}) } catch { /* Optional observers cannot fail the run. */ }
            }
          } catch { /* Invalid lines remain ordinary bounded stderr. */ }
        }
      }
      pending = Buffer.alloc(0)
      discarding = false
    }
  }
}

const DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024
// Python first drains its separately owned runtime group (TERM, then KILL,
// bounded process/pipe waits). The outer deadline must outlive that cleanup.
const TERMINATION_GRACE_MS = 8000

function terminateProcessGroup(child: ReturnType<typeof spawn>, signal: NodeJS.Signals): void {
  if (child.pid === undefined) return
  try {
    if (process.platform === 'win32') child.kill(signal)
    else process.kill(-child.pid, signal)
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error
  }
}

/** Run one no-shell child while bounding output, time, and cancellation. */
export function runProcess(
  executable: string,
  args: readonly string[],
  options: ProcessOptions = {},
): Promise<ProcessResult> {
  if (options.signal?.aborted === true) return Promise.reject(new Error('process_aborted'))
  const maxOutputBytes = options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES
  const timeoutMs = options.timeoutMs ?? 0
  if (!Number.isInteger(maxOutputBytes) || maxOutputBytes <= 0) {
    return Promise.reject(new Error('process_output_bound_invalid'))
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs < 0) {
    return Promise.reject(new Error('process_timeout_invalid'))
  }

  return new Promise((accept, reject) => {
    const spawnOptions: SpawnOptions = {
      cwd: options.cwd,
      env: options.env === undefined ? process.env : { ...process.env, ...options.env },
      shell: false,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    }
    const child = spawn(executable, [...args], spawnOptions)
    const stdout: Buffer[] = []
    const stderr: Buffer[] = []
    let stdoutBytes = 0
    let stderrBytes = 0
    let failure: Error | undefined
    const progress = options.onProgress === undefined ? undefined : createProgressParser(event => {
      if (failure === undefined && options.signal?.aborted !== true) return options.onProgress?.(event)
    })
    let forceStop: ReturnType<typeof setTimeout> | undefined

    const stop = (error: Error): void => {
      if (failure !== undefined) return
      failure = error
      terminateProcessGroup(child, 'SIGTERM')
      forceStop = setTimeout(() => terminateProcessGroup(child, 'SIGKILL'), TERMINATION_GRACE_MS)
    }
    const collect = (target: Buffer[], stream: 'stdout' | 'stderr') => (chunk: Buffer) => {
      if (failure !== undefined) return
      if (stream === 'stdout') stdoutBytes += chunk.byteLength
      else stderrBytes += chunk.byteLength
      if (stdoutBytes > maxOutputBytes || stderrBytes > maxOutputBytes) {
        stop(new Error('process_output_too_large'))
        return
      }
      target.push(Buffer.from(chunk))
      if (stream === 'stderr') progress?.(chunk)
    }
    child.stdout?.on('data', collect(stdout, 'stdout'))
    child.stderr?.on('data', collect(stderr, 'stderr'))

    const onAbort = (): void => stop(new Error('process_aborted'))
    options.signal?.addEventListener('abort', onAbort, { once: true })
    if (options.signal?.aborted) onAbort()
    const timeout = timeoutMs > 0
      ? setTimeout(() => stop(new Error('process_timed_out')), timeoutMs)
      : undefined

    child.once('error', (error) => {
      if (failure === undefined) failure = error
    })
    child.once('close', (code, signal) => {
      if (timeout !== undefined) clearTimeout(timeout)
      if (forceStop !== undefined) {
        // The leader may exit before a descendant that closed its inherited pipes.
        if (failure !== undefined) terminateProcessGroup(child, 'SIGKILL')
        clearTimeout(forceStop)
      }
      options.signal?.removeEventListener('abort', onAbort)
      if (failure !== undefined) {
        reject(failure)
        return
      }
      accept({
        code,
        signal,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
      })
    })
  })
}
