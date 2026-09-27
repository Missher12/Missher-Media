import { mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import { normalizePluginConfig } from '../src/config.js'
import type { RunEvidence } from '../src/runtime.js'
import {
  createMediaTool,
  name,
  registerMediaTool,
} from '../src/index.js'

const temporaryRoots: string[] = []

function completedEvidence(runDirectory: string): RunEvidence {
  return {
    runDirectory,
    manifestPath: join(runDirectory, 'engine', 'manifest.json'),
    runStatus: 'complete',
    records: {
      bilibili: [{ platform: 'bilibili' }],
      xhs: [{ platform: 'xhs' }],
      douyin: [{ platform: 'douyin' }],
      weibo: [{ platform: 'weibo' }],
    },
    platformStatuses: {
      bilibili: 'complete', xhs: 'complete', douyin: 'complete', weibo: 'complete',
    },
    diagnostics: {
      bilibili: { kind: 'ok', code: 'ok' },
      xhs: { kind: 'ok', code: 'ok' },
      douyin: { kind: 'ok', code: 'ok' },
      weibo: { kind: 'ok', code: 'ok' },
    },
    totalCollected: 4,
  }
}

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('Media Agent tool', () => {
  it('downgrades a claimed success when verified rows fall short of the request', async () => {
    const root = await realpath(await mkdtemp(join(tmpdir(), 'media-plugin-test-')))
    temporaryRoots.push(root)
    await writeFile(join(root, 'profile.json'), '{"platform_uids":{"bilibili":"12345","xhs":"abcdef0123456789abcdef01","douyin":"MS4wLjAB_fixture","weibo":"12345"}}', { mode: 0o600 })
    const config = normalizePluginConfig({
      profilePath: join(root, 'profile.json'),
      runtimeHome: join(root, 'runtime'),
      outputRoot: join(root, 'runs'),
    }, join(root, 'dsh'), root)
    const signal = new AbortController().signal
    const runDirectory = join(root, 'runs', 'run-fixture')
    const evidence = completedEvidence(runDirectory)
    const processRunner = vi.fn(async (_executable, _args, options) => {
      expect(options?.signal).toBe(signal)
      return {
        code: 0,
        signal: null,
        stdout: JSON.stringify({
          status: 'success',
          run_dir: runDirectory,
          evidence: [evidence.manifestPath],
        }),
        stderr: '',
      }
    })
    await mkdir(config.outputRoot, { recursive: true })
    const tool = createMediaTool(config, {
      ensureRuntime: vi.fn(async (_config, dependencies) => {
        expect(dependencies.signal).toBe(signal)
        return { python: '/runtime/python', payloadRoot: '/payload' }
      }),
      processRunner,
      loadRunEvidence: vi.fn(async () => evidence),
      writeWorkbook: vi.fn(async () => join(runDirectory, 'inspection.xlsx')),
    })

    const value = await tool.execute({}, { signal } as never) as Record<string, unknown>

    expect(value).toEqual({
      status: 'partial',
      platforms: 'bilibili,xhs,douyin,weibo',
      requestedPerPlatform: 10,
      totalCollected: 4,
      runDirectory,
      manifestPath: evidence.manifestPath,
      workbookPath: '',
      summary: 'bilibili 1/10 count-shortfall; xhs 1/10 count-shortfall; douyin 1/10 count-shortfall; weibo 1/10 count-shortfall',
    })
    expect(processRunner.mock.calls[0]?.[1]).toContain('bilibili,xhs,douyin,weibo')
    expect(tool.output.render({}, value)[0]).toMatchObject({
      type: 'text',
      text: expect.not.stringContaining('inspection.xlsx'),
    })
  })

  it('projects partial records when the manifest is declared by validation diagnostics', async () => {
    const root = await realpath(await mkdtemp(join(tmpdir(), 'media-plugin-test-')))
    temporaryRoots.push(root)
    await writeFile(join(root, 'profile.json'), '{"platform_uids":{"bilibili":"12345","xhs":"abcdef0123456789abcdef01","douyin":"MS4wLjAB_fixture","weibo":"12345"}}', { mode: 0o600 })
    const config = normalizePluginConfig({
      profilePath: join(root, 'profile.json'),
      runtimeHome: join(root, 'runtime'),
      outputRoot: join(root, 'runs'),
    }, join(root, 'dsh'), root)
    const runDirectory = join(root, 'runs', 'run-partial')
    const evidence = completedEvidence(runDirectory)
    evidence.records.bilibili = []
    evidence.platformStatuses.bilibili = 'failed'
    evidence.diagnostics.bilibili = { kind: 'timeout', code: 'creator-capture-timeout' }
    evidence.totalCollected = 3
    const load = vi.fn(async () => evidence)
    const write = vi.fn(async () => join(runDirectory, 'partial.xlsx'))
    await mkdir(config.outputRoot, { recursive: true })
    const tool = createMediaTool(config, {
      ensureRuntime: async () => ({ python: '/runtime/python', payloadRoot: '/payload' }),
      processRunner: async () => ({
        code: 1,
        signal: null,
        stdout: JSON.stringify({
          status: 'partial',
          run_dir: runDirectory,
          evidence: ['/private/xhs.json'],
          validation: {
            diagnostics: [{ path: evidence.manifestPath, status: 'failed', platforms: {} }],
          },
        }),
        stderr: '',
      }),
      loadRunEvidence: load,
      writeWorkbook: write,
    })

    const value = await tool.execute({}, { signal: new AbortController().signal }) as Record<string, unknown>

    expect(load).toHaveBeenCalledOnce()
    expect(write).not.toHaveBeenCalled()
    expect(value).toMatchObject({ status: 'partial', totalCollected: 3, workbookPath: '' })
  })

  it('registers one disposable model-visible tool', () => {
    const root = '/Users/test'
    let definition: ReturnType<typeof createMediaTool> | undefined
    let disposed = false
    const ctx = {
      dshHomePath: (...segments: string[]) => join(root, '.dsh', ...segments),
      tools: {
        register: (value: ReturnType<typeof createMediaTool>) => {
          definition = value
          return () => { disposed = true }
        },
      },
    } as unknown as Context

    const dispose = registerMediaTool(ctx, {
      profilePath: join(root, 'profile.json'),
      runtimeHome: join(root, 'runtime'),
      outputRoot: join(root, '.dsh', 'media-missher', 'runs'),
    })

    expect(name).toBe('media-missher')
    expect(definition?.name).toBe('media_missher_collect')
    expect(definition?.parameters.properties).toMatchObject({
      platforms: { type: 'string' },
      count: { type: 'integer' },
      xhs_comments: { type: 'integer' },
      allow_navigation: { type: 'boolean' },
    })
    dispose()
    expect(disposed).toBe(true)
  })
})

it('accepts explicit search targets without asking for an unrelated saved account', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-direct-target-')))
  temporaryRoots.push(root)
  const config = normalizePluginConfig({ profilePath: join(root, 'missing-profile.json'), runtimeHome: join(root, 'runtime'), outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  const ensure = vi.fn(async () => ({ python: '/runtime/python', payloadRoot: '/payload' }))
  const runner = vi.fn(async () => ({ code: 1, signal: null, stdout: JSON.stringify({ status: 'failed', run_dir: null, evidence: [] }), stderr: '' }))
  const tool = createMediaTool(config, { ensureRuntime: ensure, processRunner: runner })
  const value = await tool.execute({ targets: [{ platform: 'x', mode: 'search', keyword: 'fixture' }], count: 1 }, { signal: new AbortController().signal } as never) as Record<string, unknown>
  expect(ensure).toHaveBeenCalledOnce()
  expect(runner).toHaveBeenCalledOnce()
  expect(value.status).toBe('failed')
})

it('refuses retired computer use before any runtime or CDP factory', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-cu-refusal-')))
  temporaryRoots.push(root)
  const config = normalizePluginConfig({ profilePath: join(root, 'missing.json'), runtimeHome: join(root, 'runtime'), outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  const ensure = vi.fn(async () => { throw new Error('unexpected-runtime') })
  const runner = vi.fn(async () => { throw new Error('unexpected-CDP') })
  const tool = createMediaTool(config, { ensureRuntime: ensure, processRunner: runner })
  const value = await tool.execute({ targets: [{ platform: 'x', mode: 'search', keyword: 'fixture' }], backend: 'computer_use', count_mode: 'best_effort', run_deadline_seconds: 600 }, { signal: new AbortController().signal } as never) as Record<string, unknown>
  expect(value.summary).toContain('backend-retired-computer-use')
  expect(ensure).not.toHaveBeenCalled()
  expect(runner).not.toHaveBeenCalled()
})
