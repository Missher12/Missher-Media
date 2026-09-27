import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it } from 'vitest'
import { normalizePluginConfig } from '../src/config.js'
import { createRunsTool } from '../src/runs.js'
import { parseControllerSummary } from '../src/runtime.js'

const roots: string[] = []
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })
const timing = { schema: 1, phase: 'platform-collection', state: 'completed', platform: 'weibo', completed: 1, requested: 1, elapsed_ms: 1200, duration_ms: 1000 }

it('projects only fixed controller timings and preflight codes, preserving old summaries', () => {
  const base = { status: 'preflight-failed', run_dir: null, evidence: [] }
  expect(parseControllerSummary(JSON.stringify(base)).phaseTimings).toBeUndefined()
  expect(parseControllerSummary(JSON.stringify({ ...base, phase_timings: [timing], preflight: { code: 'runtime-version-mismatch', runtime_version: { current: '15.4.0', required: '17.0.0', matches: false }, errors: ['private'] } }))).toMatchObject({ phaseTimings: [timing], preflightCode: 'runtime-version-mismatch', runtimeVersion: { current: '15.4.0', required: '17.0.0' } })
  expect(() => parseControllerSummary(JSON.stringify({ ...base, phase_timings: [{ ...timing, uid: 'private' }] }))).toThrow('controller_progress_invalid')
})

it('lets any Agent inspect the latest private snapshot without launching Python', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-progress-test-'))); roots.push(root)
  const config = normalizePluginConfig({ outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  await mkdir(join(config.outputRoot, '.progress'), { recursive: true, mode: 0o700 })
  const path = join(config.outputRoot, '.progress', 'progress-1788800000000-0123456789abcdef.json')
  await writeFile(path, JSON.stringify({ schema: 1, status: 'completed', observed_at: '2026-09-08T01:00:00.000Z', events: [timing, { schema: 1, phase: 'run', state: 'completed', elapsed_ms: 1300, duration_ms: 1300 }] }), { mode: 0o600 })
  const result = await createRunsTool(config).execute({ action: 'progress' }, { signal: new AbortController().signal } as never) as { summary: string; metadataPath: string }
  expect(result.summary).toContain('weibo 1/1')
  expect(result.summary).toContain('1000ms')
  expect(result.metadataPath).toBe(path)
  expect(await readFile(path, 'utf8')).not.toContain('private')
})

it('connects controller progress to a private snapshot and presents safe result timings', async () => {
  const { createMediaTool } = await import('../src/index.js')
  const { realpath } = await import('node:fs/promises')
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-progress-test-'))); roots.push(root)
  const config = normalizePluginConfig({ outputRoot: join(root, 'runs'), profilePath: join(root, 'profile.json') }, join(root, 'dsh'), root)
  await mkdir(config.outputRoot, { mode: 0o700 })
  await writeFile(config.profilePath, JSON.stringify({ platform_uids: { weibo: '12345' } }), { mode: 0o600 })
  const tool = createMediaTool(config, {
    ensureRuntime: async () => ({ python: 'unused', payloadRoot: root }),
    processRunner: async (_command, _args, options) => {
      expect(options?.onProgress).toBeTypeOf('function')
      await options?.onProgress?.(timing as never)
      return { code: 1, signal: null, stdout: JSON.stringify({ status: 'preflight-failed', run_dir: null, evidence: [], phase_timings: [timing] }), stderr: '' }
    },
  })
  const result = await tool.execute({ platforms: 'weibo', count: 1 }, { signal: new AbortController().signal } as never) as { summary: string }
  expect(result.summary).toContain('1000ms')
  const progress = await createRunsTool(config).execute({ action: 'progress' }, { signal: new AbortController().signal } as never) as { summary: string }
  expect(progress.summary).toContain('weibo')
  expect(progress.summary).toContain('failed')
})

it('accepts the unavailable sentinel produced by Python runtime_version_check', async () => {
  const actualPythonShape = await readFile(new URL('./fixtures/preflight-version-unavailable.json', import.meta.url), 'utf8')
  expect(JSON.parse(actualPythonShape).preflight.runtime_version.current).toBe('unavailable')
  expect(parseControllerSummary(actualPythonShape)).toMatchObject({
    preflightCode: 'runtime-version-mismatch', runtimeVersion: { current: null, required: '17.0.0' },
  })
  expect(() => parseControllerSummary(actualPythonShape.replace('unavailable', 'private-path-or-secret'))).toThrow('controller_preflight_invalid')
})

it('keeps collection usable when only the optional progress directory is unavailable', async () => {
  const { createMediaTool } = await import('../src/index.js')
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-progress-test-'))); roots.push(root)
  const config = normalizePluginConfig({ outputRoot: join(root, 'runs'), profilePath: join(root, 'profile.json') }, join(root, 'dsh'), root)
  await mkdir(config.outputRoot, { mode: 0o700 })
  await writeFile(join(config.outputRoot, '.progress'), 'preserve-existing-file', { mode: 0o600 })
  await writeFile(config.profilePath, JSON.stringify({ platform_uids: { weibo: '12345' } }), { mode: 0o600 })
  let invoked = 0
  const tool = createMediaTool(config, {
    ensureRuntime: async () => ({ python: 'unused', payloadRoot: root }),
    processRunner: async () => { invoked += 1; return { code: 1, signal: null, stdout: JSON.stringify({ status: 'preflight-failed', run_dir: null, evidence: [] }), stderr: '' } },
  })
  const result = await tool.execute({ platforms: 'weibo', count: 1 }, { signal: new AbortController().signal } as never) as { summary: string }
  expect(invoked).toBe(1)
  expect(result.summary).toContain('local-progress-unavailable')
  expect(await readFile(join(config.outputRoot, '.progress'), 'utf8')).toBe('preserve-existing-file')
})
