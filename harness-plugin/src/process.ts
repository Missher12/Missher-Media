import { spawn, type SpawnOptions } from 'node:child_process'

export interface ProcessOptions {
  cwd?: string
  env?: NodeJS.ProcessEnv
  signal?: AbortSignal
  timeoutMs?: number
  maxOutputBytes?: number
}

export interface ProcessResult {
  code: number | null
  signal: NodeJS.Signals | null
  stdout: string
  stderr: string
}

const DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024

function terminateProcessGroup(child: ReturnType<typeof spawn>): void {
  if (child.pid === undefined) return
  try {
    if (process.platform === 'win32') child.kill('SIGTERM')
    else process.kill(-child.pid, 'SIGTERM')
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

    const stop = (error: Error): void => {
      if (failure !== undefined) return
      failure = error
      terminateProcessGroup(child)
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
    }
    child.stdout?.on('data', collect(stdout, 'stdout'))
    child.stderr?.on('data', collect(stderr, 'stderr'))

    const onAbort = (): void => stop(new Error('process_aborted'))
    options.signal?.addEventListener('abort', onAbort, { once: true })
    const timeout = timeoutMs > 0
      ? setTimeout(() => stop(new Error('process_timed_out')), timeoutMs)
      : undefined

    child.once('error', (error) => {
      if (failure === undefined) failure = error
    })
    child.once('close', (code, signal) => {
      if (timeout !== undefined) clearTimeout(timeout)
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
