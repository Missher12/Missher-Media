import { mkdir, mkdtemp, readFile, realpath, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { afterEach, expect, it, vi } from 'vitest'
import { normalizePluginConfig } from '../src/config.js'
import { browserPages, chromeCandidates, localBrowserEndpoint, probeBrowser, trustedChromeFile } from '../src/browser-setup.js'
import { createSetupTool } from '../src/setup.js'

const roots: string[] = []
async function fixture() {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-ai-browser-')))
  roots.push(root)
  const config = normalizePluginConfig({ profilePath: join(root, 'config/profile.json'), runtimeHome: join(root, 'runtime'), outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  const probe = vi.fn(async () => ({ status: 'closed' as const }))
  const pages = vi.fn(async () => ['xhs'])
  const launch = vi.fn(async () => { probe.mockResolvedValue({ status: 'ready', session: 'a'.repeat(64) } as never) })
  const findChrome = vi.fn(async () => '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
  const tool = createSetupTool(config, { probe, pages, launch, findChrome, platform: 'darwin', environmentCdp: '' })
  const execute = (args: unknown, signal = new AbortController().signal) => tool.execute(args as never, { signal } as never) as Promise<Record<string, unknown>>
  const readyProfile = async (extra = {}) => {
    await mkdir(dirname(config.profilePath), { mode: 0o700 })
    await writeFile(config.profilePath, JSON.stringify({ platform_uids: { xhs: 'abcdef0123456789abcdef01' }, active_platforms: ['xhs'], ...extra }) + '\n', { mode: 0o600 })
  }
  return { root, config, execute, probe, pages, launch, findChrome, readyProfile }
}
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

it('accepts standard admin-managed macOS Chrome permissions while rejecting untrusted files', () => {
  const stat = { isFile: () => true, uid: process.getuid!(), gid: 80, mode: 0o775 }
  expect(trustedChromeFile(stat, 'darwin')).toBe(true)
  expect(trustedChromeFile({ ...stat, uid: 0 }, 'darwin')).toBe(true)
  expect(trustedChromeFile({ ...stat, gid: 20, mode: 0o755 }, 'darwin')).toBe(true)
  expect(trustedChromeFile({ ...stat, gid: 20 }, 'darwin')).toBe(false)
  expect(trustedChromeFile({ ...stat, mode: 0o777 }, 'darwin')).toBe(false)
  expect(trustedChromeFile({ ...stat, uid: 65534 }, 'darwin')).toBe(false)
  expect(trustedChromeFile({ ...stat, isFile: () => false }, 'darwin')).toBe(false)
})

it('keeps blank devices idle for both browser actions', async () => {
  const f = await fixture()
  for (const action of ['browser-check', 'browser-open']) {
    expect(await f.execute({ action, ...(action === 'browser-open' ? { confirm_open: true } : {}) })).toMatchObject({ status: 'needs-setup', browserStatus: 'not-checked' })
  }
  expect(f.probe).not.toHaveBeenCalled()
  expect(f.launch).not.toHaveBeenCalled()
  expect(await readdir(f.root)).toEqual([])
})

it('requires an explicit opening request and keeps status passive', async () => {
  const f = await fixture(); await f.readyProfile()
  for (const args of [{ action: 'browser-open' }, { action: 'browser-open', confirm_open: false }, { action: 'status', confirm_open: true }]) {
    expect((await f.execute(args)).status).toBe('failed')
  }
  expect((await f.execute({ action: 'status' })).browserStatus).toBe('not-checked')
  expect(f.probe).not.toHaveBeenCalled(); expect(f.launch).not.toHaveBeenCalled()
})

it('opens only the AI profile and local welcome page, preserving and backing up existing settings', async () => {
  const f = await fixture(); await f.readyProfile({ cdp_url: 'http://127.0.0.1:9222', custom: 'preserve' })
  const before = await readFile(f.config.profilePath)
  const result = await f.execute({ action: 'browser-open', confirm_open: true })
  expect(result).toMatchObject({ status: 'ok', browserStatus: 'ready', browserIdentity: 'ai-dedicated', loginStatus: 'not-checked' })
  expect(f.launch).toHaveBeenCalledTimes(1)
  const [executable, args] = f.launch.mock.calls[0] as unknown as [string, string[]]
  expect(executable).toBe('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
  expect(args).toContain('--remote-debugging-address=127.0.0.1')
  expect(args).toContain('--remote-debugging-port=9223')
  expect(args).toContain(`--user-data-dir=${join(dirname(f.config.profilePath), 'browser', 'chrome-profile')}`)
  expect(args.at(-1)).toMatch(/^file:\/\//)
  expect(args.some(arg => /^https?:/.test(arg))).toBe(false)
  expect(JSON.parse(await readFile(f.config.profilePath, 'utf8'))).toMatchObject({ cdp_url: 'http://127.0.0.1:9223', custom: 'preserve' })
  const backups = join(dirname(f.config.profilePath), 'setup/backups')
  expect(await readFile(join(backups, (await readdir(backups))[0]!))).toEqual(before)
  expect(await readFile(result.artifactPath as string, 'utf8')).toContain('AI 采集专用浏览器')
  expect(await readdir(f.root)).toEqual(['config'])
  expect(f.pages).not.toHaveBeenCalled()
  expect(await f.execute({ action: 'browser-open', confirm_open: true })).toMatchObject({ status: 'ok', browserIdentity: 'ai-dedicated' })
  expect(f.launch).toHaveBeenCalledTimes(1)
  expect(await readdir(backups)).toHaveLength(1)
})

it('checks selected platform pages without claiming login or creating output', async () => {
  const f = await fixture(); await f.readyProfile({ platform_uids: { xhs: 'abcdef0123456789abcdef01', weibo: '42' }, active_platforms: ['xhs', 'weibo'] })
  f.probe.mockResolvedValue({ status: 'ready', session: 'b'.repeat(64) } as never)
  expect(await f.execute({ action: 'browser-check' })).toMatchObject({ status: 'ok', browserStatus: 'ready', openPlatforms: 'xhs', missingPlatforms: 'weibo', loginStatus: 'not-checked', browserIdentity: 'configured-external' })
  expect(f.launch).not.toHaveBeenCalled()
  expect(await readdir(dirname(f.config.profilePath))).toEqual(['profile.json'])
})

it('reports missing Chrome without installing anything or changing the profile', async () => {
  const f = await fixture(); await f.readyProfile()
  f.findChrome.mockResolvedValue(undefined as never)
  const before = await readFile(f.config.profilePath)
  expect(await f.execute({ action: 'browser-open', confirm_open: true })).toMatchObject({ status: 'needs-setup', browserStatus: 'missing-chrome' })
  expect(await readFile(f.config.profilePath)).toEqual(before)
  expect(f.launch).not.toHaveBeenCalled()
})

it.each(['ready', 'busy'])('leaves an unowned %s endpoint alone', async status => {
  const f = await fixture(); await f.readyProfile()
  f.probe.mockResolvedValue({ status, session: 'c'.repeat(64) } as never)
  expect((await f.execute({ action: 'browser-open', confirm_open: true })).status).toBe('failed')
  expect(f.launch).not.toHaveBeenCalled()
})

it('leaves an unknown browser folder untouched', async () => {
  const f = await fixture(); await f.readyProfile()
  const browserRoot = join(dirname(f.config.profilePath), 'browser')
  await mkdir(browserRoot, { mode: 0o700 }); await writeFile(join(browserRoot, 'keep'), 'keep', { mode: 0o600 })
  expect((await f.execute({ action: 'browser-open', confirm_open: true })).status).toBe('failed')
  expect(await readFile(join(browserRoot, 'keep'), 'utf8')).toBe('keep')
  expect(f.launch).not.toHaveBeenCalled()
})

it('honors cancellation before any browser action', async () => {
  const f = await fixture(); await f.readyProfile()
  const controller = new AbortController(); controller.abort()
  expect((await f.execute({ action: 'browser-open', confirm_open: true }, controller.signal)).status).toBe('failed')
  expect(f.probe).not.toHaveBeenCalled(); expect(f.launch).not.toHaveBeenCalled()
})

it('cleans the profile lock when cancellation arrives during browser startup', async () => {
  const f = await fixture(); await f.readyProfile()
  const before = await readFile(f.config.profilePath)
  const controller = new AbortController()
  f.launch.mockImplementation(async () => { controller.abort() })
  expect(await f.execute({ action: 'browser-open', confirm_open: true }, controller.signal)).toMatchObject({ status: 'failed', summary: 'setup_cancelled' })
  expect(await readFile(f.config.profilePath)).toEqual(before)
  expect(await readdir(join(dirname(f.config.profilePath), 'setup'))).not.toContain('activate.lock')
})

it('shares the profile mutation lock with selection and concurrent browser opens', async () => {
  const f = await fixture(); await f.readyProfile()
  const results = await Promise.all([1, 2].map(() => f.execute({ action: 'browser-open', confirm_open: true })))
  expect(results.filter(result => result.status === 'ok')).toHaveLength(1)
  expect(results.some(result => result.summary === 'setup_busy')).toBe(true)
  expect(f.launch).toHaveBeenCalledTimes(1)
  expect(await readdir(join(dirname(f.config.profilePath), 'setup'))).not.toContain('activate.lock')
})

it('does not replace a different browser session after its own session exits', async () => {
  const f = await fixture(); await f.readyProfile()
  expect((await f.execute({ action: 'browser-open', confirm_open: true })).status).toBe('ok')
  f.probe.mockResolvedValue({ status: 'ready', session: 'd'.repeat(64) } as never)
  expect((await f.execute({ action: 'browser-open', confirm_open: true })).summary).toBe('setup_browser_port_busy')
  expect(f.launch).toHaveBeenCalledTimes(1)
})

it('preserves configuration and releases the lock if starting Chrome fails', async () => {
  const f = await fixture(); await f.readyProfile({ cdp_url: 'http://127.0.0.1:9444' })
  const before = await readFile(f.config.profilePath)
  f.launch.mockRejectedValue(new Error('setup_browser_launch_failed'))
  expect((await f.execute({ action: 'browser-open', confirm_open: true })).summary).toBe('setup_browser_launch_failed')
  expect(await readFile(f.config.profilePath)).toEqual(before)
  expect(await readdir(join(dirname(f.config.profilePath), 'setup'))).not.toContain('activate.lock')
})

it('rejects a conflicting environment endpoint or unsupported OS before launching', async () => {
  const f = await fixture(); await f.readyProfile()
  for (const extra of [{ environmentCdp: 'http://127.0.0.1:9333', platform: 'darwin' as const }, { environmentCdp: '', platform: 'win32' as const }]) {
    const tool = createSetupTool(f.config, { ...extra, probe: f.probe, launch: f.launch })
    expect((await tool.execute({ action: 'browser-open', confirm_open: true } as never, { signal: new AbortController().signal } as never) as Record<string, unknown>).status).toBe('failed')
  }
  expect(f.probe).not.toHaveBeenCalled(); expect(f.launch).not.toHaveBeenCalled()
})

it.each(['https://127.0.0.1:9223', 'http://example.invalid:9223', 'http://127.0.0.1:9223/private', 'http://127.0.0.1:9223?secret=1', 'http://user:password@127.0.0.1:9223', 'http://127.0.0.1:80'])('keeps browser setup local for %s', endpoint => {
  expect(() => localBrowserEndpoint(endpoint)).toThrow()
})

it('reads only local CDP metadata and discards all page titles, paths and session addresses', async () => {
  const paths: string[] = []
  let endpoint = ''
  const server = createServer((request, response) => {
    paths.push(request.url!)
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify(request.url === '/json/version'
      ? { Browser: 'Chrome/136.0.0.0', 'Protocol-Version': '1.3', webSocketDebuggerUrl: endpoint.replace('http:', 'ws:') + '/devtools/browser/local-fixture' }
      : [{ type: 'page', title: 'private title', url: 'https://www.xiaohongshu.com/explore?private=value' }, { type: 'page', url: 'https://www.xiaohongshu.com.example.invalid/' }, { type: 'service_worker', url: 'https://weibo.com/' }] ))
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  endpoint = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  try {
    const signal = new AbortController().signal
    const probe = await probeBrowser(endpoint, signal)
    expect(probe.status).toBe('ready')
    expect(JSON.stringify(probe)).not.toContain('local-fixture')
    expect(await browserPages(endpoint, signal)).toEqual(['xhs'])
    expect(paths).toEqual(['/json/version', '/json/list'])
  } finally { await new Promise<void>(resolve => server.close(() => resolve())) }
})

it.each(['redirect', 'oversize', 'invalid'])('stops on a %s local endpoint without following it', async kind => {
  let requests = 0
  const server = createServer((_request, response) => {
    requests++
    if (kind === 'redirect') { response.writeHead(302, { Location: 'http://example.invalid/' }); response.end() }
    else response.end(kind === 'oversize' ? ' '.repeat(65537) : 'not JSON')
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    expect(await probeBrowser(`http://127.0.0.1:${(server.address() as AddressInfo).port}`, new AbortController().signal)).toEqual({ status: 'busy' })
    expect(requests).toBe(1)
  } finally { await new Promise<void>(resolve => server.close(() => resolve())) }
})


it('uses fixed Linux browser paths and never inherits macOS admin-group permission trust', () => {
  expect(chromeCandidates('linux')).toContain('/opt/google/chrome/chrome')
  expect(chromeCandidates('win32')).toEqual([])
  expect(chromeCandidates('linux').every(path => path.startsWith('/'))).toBe(true)
  const stat = { isFile: () => true, uid: 0, gid: 80, mode: 0o775 }
  expect(trustedChromeFile(stat, 'linux')).toBe(false)
  expect(trustedChromeFile({ ...stat, mode: 0o755 }, 'linux')).toBe(true)
})

it('requires a visible Linux session before browser creation without weakening blank-device gating', async () => {
  const f = await fixture()
  const tool = createSetupTool(f.config, { platform: 'linux', graphicalSession: false, probe: f.probe, launch: f.launch, findChrome: f.findChrome })
  const execute = () => tool.execute({ action: 'browser-open', confirm_open: true } as never, { signal: new AbortController().signal } as never)
  expect(await execute()).toMatchObject({ status: 'needs-setup' })
  expect(f.probe).not.toHaveBeenCalled()
  await f.readyProfile()
  expect(await execute()).toMatchObject({ status: 'failed', summary: 'setup_browser_graphical_session_required' })
  expect(f.findChrome).not.toHaveBeenCalled()
  expect(f.launch).not.toHaveBeenCalled()
})

it('launches a Linux browser with the same local endpoint and profile constraints', async () => {
  const f = await fixture(); await f.readyProfile()
  const tool = createSetupTool(f.config, { platform: 'linux', graphicalSession: true, probe: f.probe, launch: f.launch, findChrome: f.findChrome })
  const value = await tool.execute({ action: 'browser-open', confirm_open: true } as never, { signal: new AbortController().signal } as never)
  if (process.getuid?.() === 0) { expect(value).toMatchObject({ status: 'failed', summary: 'setup_browser_root_unsupported' }); return }
  expect(value).toMatchObject({ status: 'ok', browserIdentity: 'ai-dedicated', loginStatus: 'not-checked' })
  expect(f.launch).toHaveBeenCalledTimes(1)
  const args = (f.launch.mock.calls[0] as unknown as [string, string[]])[1]
  expect(args).toContain('--remote-debugging-address=127.0.0.1')
  expect(args).not.toContain('--no-sandbox')
  expect(args).not.toContain('--headless')
  expect(args.at(-1)).toMatch(/^file:/)
})
