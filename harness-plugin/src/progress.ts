import { randomBytes } from 'node:crypto'
import { readdir, rename, unlink } from 'node:fs/promises'
import { join } from 'node:path'
import { parseProgressEvent, type ProgressEvent } from './process.js'
import { checkPath, isMissing, privateDirectory, readBoundedFile, writePrivateFile } from './private-config.js'

type InvocationState = 'running' | 'completed' | 'failed' | 'cancelled'

export function parsePhaseTimings(value: unknown): ProgressEvent[] {
  if (!Array.isArray(value) || value.length > 32) throw new Error('controller_progress_invalid')
  let elapsed = -1
  return value.map(raw => {
    const event = parseProgressEvent(raw)
    if (event === undefined || !['completed', 'failed', 'cancelled'].includes(event.state) || event.elapsed_ms < elapsed) throw new Error('controller_progress_invalid')
    elapsed = event.elapsed_ms
    return event
  })
}

export function formatPhaseTimings(events: readonly ProgressEvent[]): string {
  return events.map(event => `${event.phase}${event.platform === undefined ? '' : `:${event.platform}`} ${event.duration_ms ?? event.elapsed_ms}ms ${event.state}`).join('; ')
}

/** One private file per invocation, so competing rejected calls cannot overwrite an active run. */
export async function createLocalProgress(outputRoot: string): Promise<{
  receive: (event: ProgressEvent) => void
  available: () => boolean
  finish: (status: Exclude<InvocationState, 'running'>) => Promise<void>
}> {
  const directory = join(outputRoot, '.progress')
  try { await privateDirectory(directory) } catch {
    return { receive: () => {}, finish: async () => {}, available: () => false }
  }
  let available = true
  const path = join(directory, `progress-${Date.now()}-${randomBytes(8).toString('hex')}.json`)
  const events: ProgressEvent[] = []
  let queue = Promise.resolve()
  let closed = false
  const persist = (status: InvocationState): void => {
    if (!available) return
    const bytes = JSON.stringify({ schema: 1, status, observed_at: new Date().toISOString(), events })
    queue = queue.then(async () => {
      const temporary = `${path}.${randomBytes(6).toString('hex')}.tmp`
      try {
        await checkPath(path)
        await writePrivateFile(temporary, bytes)
        await rename(temporary, path)
      } finally { await unlink(temporary).catch(error => { if (!isMissing(error)) throw error }) }
    }).catch(() => { available = false /* Progress observers cannot cancel collection. */ })
  }
  persist('running')
  await queue
  return {
    available: () => available,
    receive(event): void {
      const safe = parseProgressEvent(event)
      if (closed || safe === undefined || events.length >= 128 || safe.elapsed_ms < (events.at(-1)?.elapsed_ms ?? 0)) return
      events.push(safe)
      persist('running')
    },
    async finish(status): Promise<void> {
      closed = true
      persist(status)
      await queue
    },
  }
}

/** Read only the latest invocation; status is last observed, never a liveness claim. */
export async function inspectLocalProgress(outputRoot: string): Promise<{ status: string; summary: string; artifactPath: string; metadataPath: string }> {
  const directory = join(outputRoot, '.progress')
  await checkPath(directory)
  let names: string[]
  try { names = await readdir(directory) } catch (error) {
    if (isMissing(error)) return { status: 'ok', summary: 'No local progress snapshot is available.', artifactPath: '', metadataPath: '' }
    throw error
  }
  const name = names.filter(name => /^progress-\d{13}-[a-f0-9]{16}\.json$/.test(name)).sort().at(-1)
  if (name === undefined) return { status: 'ok', summary: 'No local progress snapshot is available.', artifactPath: '', metadataPath: '' }
  const path = join(directory, name)
  const value = JSON.parse((await readBoundedFile(path, 64 * 1024)).toString('utf8')) as Record<string, unknown>
  if (value === null || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'events,observed_at,schema,status'
    || value.schema !== 1 || !['running', 'completed', 'failed', 'cancelled'].includes(value.status as string)
    || typeof value.observed_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value.observed_at)
    || !Array.isArray(value.events) || value.events.length > 128) throw new Error('local_progress_invalid')
  const events = value.events.map(parseProgressEvent)
  if (events.some((event, index) => event === undefined || event.elapsed_ms < (events[index - 1]?.elapsed_ms ?? 0))) throw new Error('local_progress_invalid')
  const safe = events as ProgressEvent[]
  const last = safe.at(-1)
  const counts = [...new Map(safe.filter(event => event.platform !== undefined).map(event => [event.platform, event])).values()]
    .map(event => `${event.platform} ${event.completed}/${event.requested}`).join('; ')
  return { status: 'ok', summary: `Latest controller invocation, last observed ${value.status} at ${value.observed_at}. ${counts} ${formatPhaseTimings(safe.filter(event => event.duration_ms !== undefined).slice(-16)) || (last?.phase ?? 'waiting-for-controller')}. Local snapshot; Harness has no native live progress callback.`, artifactPath: '', metadataPath: path }
}
