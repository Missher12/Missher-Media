import { spawn } from 'node:child_process'
import { createHash, randomBytes } from 'node:crypto'
import { constants, type Stats } from 'node:fs'
import { access, lstat, readdir, rename, unlink } from 'node:fs/promises'
import { get } from 'node:http'
import { homedir, release } from 'node:os'
import { dirname, join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { pathToFileURL } from 'node:url'
import { PLATFORMS, type Platform, type PluginConfig } from './config.js'
import { checkPath, isMissing, jsonObject, privateDirectory, readBoundedFile, writePrivateFile } from './private-config.js'

const AI_ENDPOINT = 'http://127.0.0.1:9223'
const MARKER = 'managed-browser.json'
const GUIDE = 'welcome-v2.html'
const HOSTS: Record<Platform, string[]> = {
  bilibili: ['www.bilibili.com', 'space.bilibili.com'],
  xhs: ['www.xiaohongshu.com', 'xiaohongshu.com'],
  douyin: ['www.douyin.com', 'douyin.com'],
  weibo: ['weibo.com', 'www.weibo.com', 'm.weibo.cn'],
  x: ['x.com', 'www.x.com', 'twitter.com'],
}
export type BrowserProbe = { status: 'closed' | 'busy' } | { status: 'ready'; session: string }
export interface BrowserSetupDependencies {
  probe?: (endpoint: string, signal: AbortSignal) => Promise<BrowserProbe>
  pages?: (endpoint: string, signal: AbortSignal) => Promise<string[]>
  findChrome?: () => Promise<string | undefined>
  launch?: (executable: string, args: string[]) => Promise<void>
  platform?: NodeJS.Platform
  environmentCdp?: string
  graphicalSession?: boolean
  wsl?: boolean
}
export interface BrowserSetupValue {
  status: 'ok' | 'needs-setup' | 'failed'
  summary: string
  browserStatus: 'ready' | 'not-running' | 'missing-chrome' | 'busy' | 'starting'
  browserIdentity: 'ai-dedicated' | 'configured-external' | 'not-checked'
  openPlatforms: string
  missingPlatforms: string
  loginStatus: 'not-checked'
  artifactPath: string
}
const base = (): BrowserSetupValue => ({ status: 'ok', summary: '', browserStatus: 'ready', browserIdentity: 'not-checked', openPlatforms: '', missingPlatforms: '', loginStatus: 'not-checked', artifactPath: '' })

export function isWsl(): boolean {
  return process.platform === 'linux' && (Boolean(process.env.WSL_DISTRO_NAME) || /microsoft/i.test(release()))
}

export function localBrowserEndpoint(value: unknown): string {
  if (typeof value !== 'string' || !/^http:\/\/(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?\/?$/.test(value)) throw new Error('setup_browser_endpoint_unsupported')
  const url = new URL(value)
  if (!url.port || Number(url.port) < 1024) throw new Error('setup_browser_endpoint_unsupported')
  return `http://127.0.0.1:${url.port}`
}

/** Local CDP metadata only. No redirects, page evaluation, cookies or remote requests. */
export async function browserJson(endpoint: string, path: '/json/version' | '/json/list', signal: AbortSignal): Promise<unknown> {
  const origin = localBrowserEndpoint(endpoint)
  signal.throwIfAborted()
  return new Promise((resolve, reject) => {
    const request = get(`${origin}${path}`, { agent: false, maxHeaderSize: 8192 }, response => {
      if (response.statusCode !== 200) { finish(new Error('setup_browser_response_invalid')); return }
      const chunks: Buffer[] = []
      let length = 0
      response.on('data', (chunk: Buffer) => {
        length += chunk.length
        if (length > 64 * 1024) { finish(new Error('setup_browser_response_invalid')); return }
        chunks.push(chunk)
      })
      response.once('error', error => finish(error))
      response.once('end', () => {
        try { finish(undefined, JSON.parse(Buffer.concat(chunks).toString('utf8'))) }
        catch { finish(new Error('setup_browser_response_invalid')) }
      })
    })
    let finished = false
    const abort = () => finish(new Error('setup_cancelled'))
    const timer = setTimeout(() => finish(new Error('setup_browser_response_timeout')), 2500)
    function finish(error?: Error, value?: unknown) {
      if (finished) return
      finished = true
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
      request.destroy()
      if (error) reject(error)
      else resolve(value)
    }
    request.once('error', error => finish(error))
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
  })
}

export async function probeBrowser(endpoint: string, signal: AbortSignal): Promise<BrowserProbe> {
  try {
    const value = await browserJson(endpoint, '/json/version', signal) as Record<string, unknown> | null
    if (!value || typeof value.Browser !== 'string' || !/^(?:HeadlessChrome|Chrome|Chromium)\/[0-9.]{1,40}$/.test(value.Browser)
      || value['Protocol-Version'] !== '1.3' || typeof value.webSocketDebuggerUrl !== 'string' || value.webSocketDebuggerUrl.length > 1024) return { status: 'busy' }
    const socket = new URL(value.webSocketDebuggerUrl)
    if (socket.protocol !== 'ws:' || socket.username || socket.password || socket.search || socket.hash
      || !['127.0.0.1', 'localhost'].includes(socket.hostname) || socket.port !== new URL(endpoint).port
      || !/^\/devtools\/browser\/[A-Za-z0-9-]{1,128}$/.test(socket.pathname)) return { status: 'busy' }
    return { status: 'ready', session: createHash('sha256').update(socket.pathname).digest('hex') }
  } catch (error) {
    signal.throwIfAborted()
    return { status: (error as NodeJS.ErrnoException).code === 'ECONNREFUSED' ? 'closed' : 'busy' }
  }
}

export async function browserPages(endpoint: string, signal: AbortSignal): Promise<string[]> {
  const value = await browserJson(endpoint, '/json/list', signal)
  if (!Array.isArray(value) || value.length > 256) throw new Error('setup_browser_response_invalid')
  const present = new Set<Platform>()
  for (const page of value) {
    if (!page || page.type !== 'page' || typeof page.url !== 'string' || page.url.length > 8192) continue
    try {
      const url = new URL(page.url)
      if (url.protocol !== 'https:' || url.username || url.password) continue
      for (const platform of PLATFORMS) if (HOSTS[platform].includes(url.hostname)) present.add(platform)
    } catch { /* Only recognized platform origins contribute to readiness. */ }
  }
  return PLATFORMS.filter(platform => present.has(platform))
}

export function trustedChromeFile(stat: Pick<Stats, 'isFile' | 'mode' | 'uid' | 'gid'>, platform: NodeJS.Platform = process.platform): boolean {
  // Standard macOS app installs may be writable by the local admin group (80).
  // Keep the fixed installation paths, ownership check and world-write rejection.
  return stat.isFile() && (stat.uid === 0 || stat.uid === process.getuid?.())
    && (stat.mode & 0o002) === 0 && ((stat.mode & 0o020) === 0 || (platform === 'darwin' && stat.gid === 80))
}

export function chromeCandidates(platform: NodeJS.Platform): string[] {
  if (platform === 'darwin') return ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', join(homedir(), 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]
  if (platform === 'linux') return ['/opt/google/chrome/chrome', '/usr/lib/chromium/chromium', '/usr/lib64/chromium-browser/chromium-browser']
  return []
}

async function findChrome(platform: NodeJS.Platform): Promise<string | undefined> {
  for (const executable of chromeCandidates(platform)) {
    try {
      await checkPath(executable)
      const stat = await lstat(executable)
      if (!trustedChromeFile(stat, platform)) continue
      await access(executable, constants.X_OK)
      return executable
    } catch (error) { if (!isMissing(error) && (error as NodeJS.ErrnoException).code !== 'EACCES') throw error }
  }
  return undefined
}

async function launchChrome(executable: string, args: string[]): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(executable, args, { detached: true, stdio: 'ignore', shell: false })
    child.once('error', () => reject(new Error('setup_browser_launch_failed')))
    child.once('spawn', () => { child.unref(); resolve() })
  })
}

const welcome = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Media@Missher AI 采集专用浏览器</title><style>body{font:17px/1.8 system-ui,sans-serif;background:#f5f7fa;color:#172536;margin:0}main{max-width:820px;margin:48px auto;padding:36px;background:white;border-radius:20px}h1{font-size:30px;line-height:1.3}nav{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:24px 0}a{color:#0757aa}nav a{display:block;padding:18px;border:1px solid #dce5ee;border-radius:12px;text-decoration:none}small{color:#56697b}li{margin:14px 0}@media(max-width:600px){main{margin:16px;padding:22px}nav{grid-template-columns:1fr}}</style><main><small>Media@Missher · 独立工作身份</small><h1>AI 采集专用浏览器</h1><p>这是独立的浏览器资料目录，与日常 Chrome 分开。平台账号仍由你本人登录；登录状态只保存在本机此目录中。</p><ol><li>已通过 Agent 导入并选择博主名单。这里只按你选择的目标准备采集。</li><li>点击所需平台的官方入口，在新标签页自行登录。保持标签页打开，然后返回 Agent 告诉 Agent“已登录，请检查浏览器”。</li><li>Agent 会检查本地连接和平台页面。连接成功、页面存在都不代表登录已经通过。</li><li>明确本次平台、条数和导航范围后，Agent 才进行首批采集与登录检查，随后展示 Excel 结果。验证码、登录过期或风险提示会停止任务，并说明需要你处理的步骤。</li></ol><nav><a href="https://www.bilibili.com/" target="_blank" rel="noopener noreferrer">登录 B 站 →</a><a href="https://www.xiaohongshu.com/explore" target="_blank" rel="noopener noreferrer">登录小红书 →</a><a href="https://www.douyin.com/" target="_blank" rel="noopener noreferrer">登录抖音 →</a><a href="https://weibo.com/" target="_blank" rel="noopener noreferrer">登录微博 →</a></nav><p>无需把密码、Cookie 或验证码发给 Agent。页面不会自动打开平台、执行登录或开始抓取。</p><p><small>下次仍从 Agent 的“打开 AI 采集浏览器”入口进入，可保留已有登录状态。使用完毕可以自行退出此 Chrome；采集停止不会关闭你的浏览器，也不会设置开机启动。</small></p><p><small>© 2026 Missher · 保留所有权利。原创软件未经许可禁止修改、衍生及二次传播；第三方组件保留原许可。</small></p></main></html>`

async function ensureWelcome(guide: string): Promise<void> {
  try {
    if ((await readBoundedFile(guide, 32 * 1024)).toString('utf8') !== welcome) throw new Error('setup_browser_guide_changed')
  } catch (error) { if (!isMissing(error)) throw error; await writePrivateFile(guide, welcome) }
}

async function ownerAt(root: string): Promise<string | undefined> {
  try {
    const owner = jsonObject(await readBoundedFile(join(root, MARKER), 2048))
    if (Object.keys(owner).sort().join(',') !== 'endpoint,schema,session' || owner.schema !== 1 || owner.endpoint !== AI_ENDPOINT
      || typeof owner.session !== 'string' || !/^(?:[a-f0-9]{64})?$/.test(owner.session)) throw new Error('setup_browser_owner_invalid')
    return owner.session
  } catch (error) { if (isMissing(error)) return undefined; throw error }
}

async function saveOwner(root: string, session: string, replace: boolean): Promise<void> {
  const bytes = `${JSON.stringify({ schema: 1, endpoint: AI_ENDPOINT, session })}\n`
  if (!replace) { await writePrivateFile(join(root, MARKER), bytes); return }
  await ownerAt(root)
  const temporary = join(root, `.owner-${randomBytes(16).toString('hex')}.tmp`)
  await writePrivateFile(temporary, bytes)
  try { await rename(temporary, join(root, MARKER)) }
  finally { await unlink(temporary).catch(error => { if (!isMissing(error)) throw error }) }
}

export async function checkBrowser(config: PluginConfig, value: Record<string, unknown>, active: Platform[], signal: AbortSignal, dependencies: BrowserSetupDependencies): Promise<BrowserSetupValue> {
  const endpoint = localBrowserEndpoint((dependencies.environmentCdp ?? process.env.MEDIA_MISSHER_CDP_URL) || value.cdp_url || 'http://127.0.0.1:9222')
  const probe = await (dependencies.probe ?? probeBrowser)(endpoint, signal)
  if (probe.status !== 'ready') return { ...base(), status: 'needs-setup', browserStatus: probe.status === 'closed' ? 'not-running' : 'busy', summary: probe.status === 'closed' ? '浏览器未连接。可明确打开 AI 采集专用浏览器，再按引导登录。' : '本地端口没有返回可用的 Chrome 连接；请检查现有浏览器，本次不会启动或替换它。' }
  const opened = await (dependencies.pages ?? browserPages)(endpoint, signal)
  const identity = endpoint === AI_ENDPOINT && await ownerAt(join(dirname(config.profilePath), 'browser')) === probe.session ? 'ai-dedicated' : 'configured-external'
  if ((dependencies.wsl ?? isWsl()) && identity !== 'ai-dedicated') return { ...base(), status: 'failed', browserStatus: 'busy', browserIdentity: identity, summary: 'setup_browser_wsl_owned_required; WSL 仅支持同一 Linux 用户创建的 AI 专用浏览器。请保留外部浏览器，使用 browser-open 准备 Linux Chrome。' }
  const present = active.filter(platform => opened.includes(platform))
  const missing = active.filter(platform => !present.includes(platform))
  return { ...base(), browserIdentity: identity, openPlatforms: present.join(','), missingPlatforms: missing.join(','),
    summary: missing.length ? `浏览器已连接；请在专用浏览器打开并登录这些平台：${missing.join(',')}。页面检查不验证登录，也未开始采集。` : '浏览器已连接，所选平台页面已打开。登录状态仍待采集前检查；请明确本次条数和导航范围，再开始首批采集。' }
}

/** Explicit user action only. The collection path never calls this function. */
export async function openAiBrowser(config: PluginConfig, signal: AbortSignal, dependencies: BrowserSetupDependencies): Promise<BrowserSetupValue & { endpoint?: string }> {
  const platform = dependencies.platform ?? process.platform
  if (!['darwin', 'linux'].includes(platform)) throw new Error('setup_browser_platform_unsupported')
  const override = dependencies.environmentCdp ?? process.env.MEDIA_MISSHER_CDP_URL
  if (override && localBrowserEndpoint(override) !== AI_ENDPOINT) throw new Error('setup_browser_environment_override')
  const root = join(dirname(config.profilePath), 'browser')
  const guide = join(root, GUIDE)
  const session = await ownerAt(root)
  const probe = dependencies.probe ?? probeBrowser
  const current = await probe(AI_ENDPOINT, signal)
  if (current.status === 'ready' && session === current.session) {
    await ensureWelcome(guide)
    return { ...base(), browserIdentity: 'ai-dedicated', artifactPath: guide, endpoint: AI_ENDPOINT, summary: 'AI 采集专用浏览器已经打开，已复用同一会话。请在其中完成平台登录，再检查浏览器；尚未采集。' }
  }
  if (current.status !== 'closed') throw new Error('setup_browser_port_busy')
  if (platform === 'linux') {
    if (!(dependencies.graphicalSession ?? Boolean(process.env.DISPLAY || process.env.WAYLAND_DISPLAY))) throw new Error('setup_browser_graphical_session_required')
    if (process.getuid?.() === 0) throw new Error('setup_browser_root_unsupported')
  }
  const executable = await (dependencies.findChrome ?? (() => findChrome(platform)))()
  if (!executable) return { ...base(), status: 'needs-setup', browserStatus: 'missing-chrome', summary: '未找到 Google Chrome。请从 https://www.google.com/chrome/ 安装官方版本后，再打开 AI 采集浏览器；名单会保留。' }
  await privateDirectory(root)
  if (session === undefined) {
    if ((await readdir(root)).length) throw new Error('setup_browser_directory_unrecognized')
    await saveOwner(root, '', false)
  }
  const profile = join(root, 'chrome-profile')
  await privateDirectory(profile)
  try { await lstat(join(profile, 'SingletonLock')); throw new Error('setup_browser_profile_busy') }
  catch (error) { if (!isMissing(error)) throw error }
  await ensureWelcome(guide)
  signal.throwIfAborted()
  await (dependencies.launch ?? launchChrome)(executable, ['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9223', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--new-window', pathToFileURL(guide).href])
  const waitSignal = AbortSignal.any([signal, AbortSignal.timeout(12_000)])
  try {
    while (!waitSignal.aborted) {
      const ready = await probe(AI_ENDPOINT, waitSignal)
      if (ready.status === 'ready') {
        await saveOwner(root, ready.session, true)
        return { ...base(), browserIdentity: 'ai-dedicated', artifactPath: guide, endpoint: AI_ENDPOINT, summary: 'AI 采集专用浏览器已打开。请按欢迎页进入所需平台并自行登录，保持页面打开后返回 Agent 检查浏览器；未开始采集。' }
      }
      if (ready.status === 'busy') throw new Error('setup_browser_port_busy')
      await delay(250, undefined, { signal: waitSignal })
    }
  } catch (error) { if (!waitSignal.aborted) throw error }
  signal.throwIfAborted()
  return { ...base(), status: 'needs-setup', browserStatus: 'starting', artifactPath: guide, summary: 'Chrome 已收到启动请求，但连接未在限定时间内就绪。请处理窗口中的系统提示；若仍无法连接，请自行退出此次专用 Chrome 后重试。本次未修改连接配置或开始采集。' }
}
