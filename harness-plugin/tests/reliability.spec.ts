import { mkdir, mkdtemp, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import { normalizeCollectArgs, normalizePluginConfig } from '../src/config.js'
import { createMediaTool, apply } from '../src/index.js'
import { createRunsTool } from '../src/runs.js'
import { buildControllerInvocation, parseControllerSummary } from '../src/runtime.js'

const roots: string[] = []
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

it('binds explicit continuation to an exact ID and preserves original count', () => {
  const config = normalizePluginConfig({}, '/tmp/dsh', '/tmp/user')
  const request = normalizeCollectArgs({ platforms: 'xhs', count: 20, resume_run: 'run-fixture', allow_navigation: true }, config)
  const invocation = buildControllerInvocation(config, request, { python: '/tmp/python', payloadRoot: '/tmp/payload' })
  expect(invocation.args).toContain('--resume-run')
  expect(invocation.args).toContain('run-fixture')
  expect(invocation.args[invocation.args.indexOf('--count') + 1]).toBe('20')
  expect(() => normalizeCollectArgs({ resume_run: '../run-fixture' }, config)).toThrow('resume_run_invalid')
})

it('retains only allowlisted precondition diagnostics', () => {
  const base = { status: 'preflight-failed', run_dir: null, evidence: [] }
  expect(parseControllerSummary(JSON.stringify({ ...base, diagnostics: { xhs: { kind: 'precondition', code: 'xhs-cooldown' } } })).preconditions).toEqual({ xhs: 'xhs-cooldown' })
  expect(() => parseControllerSummary(JSON.stringify({ ...base, diagnostics: { xhs: { kind: 'precondition', code: 'private source text' } } }))).toThrow('controller_diagnostics_invalid')
})

it('registers collection and offline runs tools without a reset action', () => {
  const registered: string[] = []
  apply({ dshHomePath: () => '/tmp/dsh', tools: { register: (tool: { name: string }) => { registered.push(tool.name); return () => {} } } } as never)
  expect(registered).toEqual(['media_missher_collect', 'media_missher_runs', 'media_missher_setup'])
  const tool = createRunsTool(normalizePluginConfig({}, '/tmp/dsh', '/tmp/user'))
  expect(tool.parameters.properties?.action).toMatchObject({ enum: ['list', 'export', 'compare', 'xhs-status', 'progress'] })
})

it('reports historical and new counts separately on a completed continuation', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-resume-tool-'))); roots.push(root)
  const config = normalizePluginConfig({ outputRoot: join(root, 'out'), profilePath: join(root, 'profile.json') }, join(root, 'dsh'), root)
  await writeFile(config.profilePath, '{"platform_uids":{"bilibili":"12345","xhs":"abcdef0123456789abcdef01","douyin":"MS4wLjAB_fixture","weibo":"12345"}}', { mode: 0o600 })
  await mkdir(config.outputRoot)
  const runDirectory = join(config.outputRoot, 'run-new')
  const manifestPath = join(runDirectory, 'run-inner', 'manifest.json')
  const tool = createMediaTool(config, {
    ensureRuntime: async () => ({ python: '/synthetic/python', payloadRoot: '/synthetic/payload' }),
    processRunner: vi.fn(async () => ({ code: 0, signal: null, stderr: '', stdout: JSON.stringify({ status: 'success', run_dir: runDirectory, evidence: [manifestPath], continuation: { prior_counts: { xhs: 2 }, requested_counts: { xhs: 3 } } }) })),
    loadRunEvidence: async () => ({ runDirectory, manifestPath, runStatus: 'complete', records: { bilibili: [], xhs: [{ note_id: 'new' }], douyin: [], weibo: [] }, platformStatuses: { bilibili: 'not-selected', xhs: 'complete', douyin: 'not-selected', weibo: 'not-selected' }, diagnostics: { bilibili: { kind: 'not-run', code: 'not-selected' }, xhs: { kind: 'ok', code: 'ok' }, douyin: { kind: 'not-run', code: 'not-selected' }, weibo: { kind: 'not-run', code: 'not-selected' } }, totalCollected: 1 }),
    writeWorkbook: async () => join(runDirectory, 'new-only.xlsx'),
  })
  const result = await tool.execute({ platforms: 'xhs', count: 3, resume_run: 'run-old', allow_navigation: true }, { signal: new AbortController().signal } as never) as { status: string; totalCollected: number; summary: string }
  expect(result.status).toBe('success')
  expect(result.totalCollected).toBe(1)
  expect(result.summary).toBe('xhs historical 2 + new 1/3 ok')
})
