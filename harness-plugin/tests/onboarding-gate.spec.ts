import { mkdir, mkdtemp, readFile, realpath, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import { normalizePluginConfig } from '../src/config.js'
import { createMediaTool } from '../src/index.js'

const roots: string[] = []
async function fixture(profile?: unknown, defaultPlatforms = 'bilibili,xhs,douyin,weibo') {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-onboarding-gate-')))
  roots.push(root)
  const config = normalizePluginConfig({ defaultPlatforms, profilePath: join(root, 'profile.json'), runtimeHome: join(root, 'runtime'), outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  if (profile !== undefined) await writeFile(config.profilePath, JSON.stringify(profile), { mode: 0o600 })
  const ensureRuntime = vi.fn(async () => {
    await mkdir(config.outputRoot, { recursive: true })
    return { python: '/fixture/python', payloadRoot: '/fixture/payload' }
  })
  const processRunner = vi.fn(async (_executable: string, args: readonly string[]) => {
    expect(JSON.parse(await readFile(args[args.indexOf('--profile') + 1]!, 'utf8'))).toEqual(profile)
    return { code: 1, signal: null, stdout: JSON.stringify({ status: 'preflight-failed', run_dir: null, evidence: [] }), stderr: '' }
  })
  return { root, config, ensureRuntime, processRunner, tool: createMediaTool(config, { ensureRuntime, processRunner }) }
}
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

it.each([undefined, {}, { platform_uids: {} }, { platform_uids: { xhs: '' } }])('blocks an unconfigured device before any runtime or output work: %j', async profile => {
  const f = await fixture(profile)
  const result = await f.tool.execute({}, { signal: new AbortController().signal } as never)
  expect(result).toMatchObject({ status: 'needs-input', missingFields: ['platforms', 'targets'], totalCollected: 0, runDirectory: '', workbookPath: '' })
  expect(f.ensureRuntime).not.toHaveBeenCalled()
  expect(f.processRunner).not.toHaveBeenCalled()
  expect(await readdir(f.root)).not.toContain('runs')
})

it('requires every explicitly requested platform before installing', async () => {
  const f = await fixture({ platform_uids: { xhs: 'abcdef0123456789abcdef01' } })
  const result = await f.tool.execute({ platforms: 'xhs,weibo' }, { signal: new AbortController().signal } as never)
  expect(result).toMatchObject({ status: 'needs-input', missingFields: ['targets'], summary: expect.stringContaining('weibo') })
  expect(f.ensureRuntime).not.toHaveBeenCalled()
})

it('uses the configured subset on legacy profiles without an explicit selection', async () => {
  const f = await fixture({ platform_uids: { xhs: 'abcdef0123456789abcdef01' } })
  await f.tool.execute({}, { signal: new AbortController().signal } as never)
  const args = f.processRunner.mock.calls[0]![1]
  expect(args[args.indexOf('--platform') + 1]).toBe('xhs')
  expect(args[args.indexOf('--profile') + 1]).not.toBe(f.config.profilePath)
  expect(await readdir(f.config.outputRoot)).toEqual(['.progress'])
})

it('uses only the active selection while preserving other stored targets', async () => {
  const profile = { platform_uids: { xhs: 'abcdef0123456789abcdef01', weibo: '12345' }, active_platforms: ['xhs'] }
  const f = await fixture(profile)
  await f.tool.execute({}, { signal: new AbortController().signal } as never)
  const args = f.processRunner.mock.calls[0]![1]
  expect(args[args.indexOf('--platform') + 1]).toBe('xhs')
  expect(JSON.parse(await readFile(f.config.profilePath, 'utf8'))).toEqual(profile)
})

it('cleans the private profile snapshot even when the controller fails to start', async () => {
  const f = await fixture({ platform_uids: { weibo: '12345' } })
  f.processRunner.mockRejectedValueOnce(new Error('spawn_fixture_failure'))
  await expect(f.tool.execute({}, { signal: new AbortController().signal } as never)).rejects.toThrow('spawn_fixture_failure')
  expect(await readdir(f.config.outputRoot)).toEqual(['.progress'])
})

it.each([['xhs'], ['bilibili', 'xhs']])('honors active selection %j over legacy plugin defaults, including dependent comment arguments', async (...active) => {
  const f = await fixture({ platform_uids: { bilibili: '12345', xhs: 'abcdef0123456789abcdef01' }, active_platforms: active }, 'bilibili')
  await f.tool.execute({ xhs_comments: 1 }, { signal: new AbortController().signal } as never)
  const args = f.processRunner.mock.calls[0]![1]
  expect(args[args.indexOf('--platform') + 1]).toBe(active.join(','))
  expect(args[args.indexOf('--xhs-comments') + 1]).toBe('1')
})

it('preserves a custom legacy default before any explicit activation', async () => {
  const f = await fixture({ platform_uids: { bilibili: '12345', xhs: 'abcdef0123456789abcdef01' } }, 'bilibili')
  await f.tool.execute({}, { signal: new AbortController().signal } as never)
  const args = f.processRunner.mock.calls[0]![1]
  expect(args[args.indexOf('--platform') + 1]).toBe('bilibili')
})

it('lets an explicit per-call platform override active selection', async () => {
  const f = await fixture({ platform_uids: { bilibili: '12345', xhs: 'abcdef0123456789abcdef01' }, active_platforms: ['xhs'] }, 'xhs')
  await f.tool.execute({ platforms: 'bilibili' }, { signal: new AbortController().signal } as never)
  const args = f.processRunner.mock.calls[0]![1]
  expect(args[args.indexOf('--platform') + 1]).toBe('bilibili')
})

it('does not silently widen a malformed null activation to stored targets', async () => {
  const f = await fixture({ platform_uids: { weibo: '12345' }, active_platforms: null })
  const result = await f.tool.execute({}, { signal: new AbortController().signal } as never)
  expect(result).toMatchObject({ status: 'preflight-failed' })
  expect(f.ensureRuntime).not.toHaveBeenCalled()
})

it('blocks an external WSL browser even when runtime exists without starting collection', async () => {
  const f = await fixture({ platform_uids: { xhs: 'abcdef0123456789abcdef01' } })
  const checkBrowser = vi.fn(async () => ({ status: 'failed' as const, summary: 'setup_browser_wsl_owned_required', browserStatus: 'busy' as const, browserIdentity: 'configured-external' as const, openPlatforms: '', missingPlatforms: '', loginStatus: 'not-checked' as const, artifactPath: '' }))
  const tool = createMediaTool(f.config, { ensureRuntime: f.ensureRuntime, processRunner: f.processRunner, wsl: true, checkBrowser })
  const result = await tool.execute({ platforms: 'xhs', count: 1 }, { signal: new AbortController().signal } as never)
  expect(result).toMatchObject({ status: 'preflight-failed', totalCollected: 0, summary: 'setup_browser_wsl_owned_required', runDirectory: '' })
  expect(checkBrowser).toHaveBeenCalledTimes(1)
  expect(f.processRunner).not.toHaveBeenCalled()
  await expect(readdir(f.config.outputRoot)).rejects.toMatchObject({ code: 'ENOENT' })
})

it('projects only validated progress and tolerates an observer error', async () => {
  const f = await fixture({ platform_uids: { weibo: '12345' } })
  const safe = { schema: 1 as const, phase: 'engine' as const, state: 'started' as const, elapsed_ms: 2 }
  const observer = vi.fn(() => { throw new Error('optional_observer_failure') })
  const processRunner = vi.fn(async (executable, args, options) => {
    options.onProgress({ ...safe, secret: 'must_not_escape' })
    options.onProgress(safe)
    return f.processRunner(executable, args)
  })
  const tool = createMediaTool(f.config, { ensureRuntime: f.ensureRuntime, processRunner, onProgress: observer })
  expect(await tool.execute({}, { signal: new AbortController().signal } as never)).toMatchObject({ status: 'preflight-failed' })
  expect(observer).toHaveBeenCalledExactlyOnceWith(safe)
})
