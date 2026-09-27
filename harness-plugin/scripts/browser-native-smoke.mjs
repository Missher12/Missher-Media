#!/usr/bin/env node
import assert from 'node:assert/strict'
import { execFile, spawn } from 'node:child_process'
import { mkdtemp, realpath, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { pathToFileURL } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { promisify } from 'node:util'
import { createSetupTool, normalizePluginConfig } from '../lib/index.js'

const args = process.argv.slice(2)
if (args[0] === '--') args.shift()
if (args.length !== 1 || args[0] !== '--confirm-open') {
  throw new Error('usage: browser-native-smoke.mjs --confirm-open (opens a temporary Chrome with a local guide only)')
}

const root = await realpath(await mkdtemp(join(tmpdir(), 'media-ai-native-smoke-')))
const result = {
  kind: 'actual Chrome startup with temporary dedicated profile and local guide only',
  syntheticCreator: true, browserLaunches: 0, platformNavigations: 0,
  loginVerified: false, collectedRecords: 0, cleanupVerified: false,
}
let ownedChild
const executeFile = promisify(execFile)
const alive = async () => {
  if (!ownedChild?.pid) return false
  // macOS can report EPERM for a signal-0 group probe after Chrome exits.
  // Inspect group metadata instead; exited zombies cannot hold profile files.
  const { stdout } = await executeFile('/bin/ps', ['-axo', 'pid=,pgid=,state='], { timeout: 2500, maxBuffer: 1024 * 1024 })
  return stdout.split('\n').some(line => {
    const [, group, state] = line.trim().split(/\s+/)
    return Number(group) === ownedChild.pid && state && !state.startsWith('Z')
  })
}
const controller = new AbortController()
const interrupt = () => controller.abort()
process.on('SIGINT', interrupt)
process.on('SIGTERM', interrupt)
try {
  const config = normalizePluginConfig({ profilePath: join(root, 'config/profile.json'), runtimeHome: join(root, 'runtime'), outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  const tool = createSetupTool(config, {
    environmentCdp: '',
    // Capture only the process we launch so cleanup cannot close a user's Chrome.
    launch: async (executable, args) => {
      assert.ok(executable.endsWith('/Google Chrome.app/Contents/MacOS/Google Chrome'))
      assert.ok(args.includes('--remote-debugging-address=127.0.0.1'))
      assert.ok(args.includes(`--user-data-dir=${join(root, 'config/browser/chrome-profile')}`))
      assert.equal(args.filter(value => /^https?:/.test(value)).length, 0)
      assert.equal(args.at(-1), pathToFileURL(join(root, 'config/browser/welcome-v2.html')).href)
      ownedChild = spawn(executable, args, { detached: true, stdio: 'ignore', shell: false })
      await new Promise((resolve, reject) => { ownedChild.once('error', reject); ownedChild.once('spawn', resolve) })
      result.browserLaunches++
    },
  })
  const execute = args => tool.execute(args, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(25_000)]) })
  for (const action of ['browser-check', 'browser-open']) {
    const blank = await execute({ action, ...(action === 'browser-open' ? { confirm_open: true } : {}) })
    assert.equal(blank.status, 'needs-setup'); assert.equal(blank.browserStatus, 'not-checked')
  }
  assert.deepEqual(await readdir(root), [])
  result.blankDeviceIdle = true
  await mkdir(dirname(config.profilePath), { mode: 0o700 })
  const before = JSON.stringify({ platform_uids: { xhs: 'abcdef0123456789abcdef01' }, active_platforms: ['xhs'], cdp_url: 'http://127.0.0.1:9222', smokeOnly: true }) + '\n'
  await writeFile(config.profilePath, before, { mode: 0o600 })
  const opened = await execute({ action: 'browser-open', confirm_open: true })
  assert.equal(opened.status, 'ok', opened.summary)
  assert.equal(opened.browserIdentity, 'ai-dedicated')
  assert.equal(opened.loginStatus, 'not-checked')
  const metadata = async path => (await fetch(`http://127.0.0.1:9223${path}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(2500)]), redirect: 'error' })).json()
  const version = await metadata('/json/version')
  result.chromeVersion = version.Browser
  let pages = []
  const guideLoaded = page => page.type === 'page' && page.url === pathToFileURL(opened.artifactPath).href && page.title === 'Media@Missher AI 采集专用浏览器'
  for (let attempt = 0; attempt < 20; attempt++) {
    pages = await metadata('/json/list')
    if (pages.some(guideLoaded)) break
    await delay(250, undefined, { signal: controller.signal })
  }
  assert.ok(pages.some(guideLoaded))
  assert.equal(pages.filter(page => page.type === 'page' && /^https?:/.test(page.url)).length, 0)
  result.localWelcomePageVerified = true
  result.pageCount = pages.filter(page => page.type === 'page').length
  assert.ok((await readFile(opened.artifactPath, 'utf8')).includes('© 2026 Missher'))
  result.copyrightInGuideVerified = true
  const checked = await execute({ action: 'browser-check' })
  assert.equal(checked.status, 'ok'); assert.equal(checked.browserIdentity, 'ai-dedicated')
  assert.equal(checked.openPlatforms, ''); assert.equal(checked.missingPlatforms, 'xhs'); assert.equal(checked.loginStatus, 'not-checked')
  result.connectionAndMissingPageVerified = true
  const repeated = await execute({ action: 'browser-open', confirm_open: true })
  assert.equal(repeated.status, 'ok'); assert.equal(result.browserLaunches, 1)
  result.sessionReuseVerified = true
  const backups = join(root, 'config/setup/backups')
  const backupFiles = await readdir(backups)
  assert.equal(backupFiles.length, 1); assert.equal(await readFile(join(backups, backupFiles[0]), 'utf8'), before)
  result.exactProfileBackupVerified = true
  assert.deepEqual(await readdir(root), ['config'])
  assert.equal((await readdir(join(root, 'config/setup'))).includes('activate.lock'), false)
  result.noRuntimeOrCollectionOutput = true
} finally {
  if (await alive()) {
    process.kill(-ownedChild.pid, 'SIGTERM')
    for (let attempt = 0; attempt < 32 && await alive(); attempt++) await delay(250)
    if (await alive()) {
      process.kill(-ownedChild.pid, 'SIGKILL')
      for (let attempt = 0; attempt < 20 && await alive(); attempt++) await delay(100)
    }
  }
  assert.equal(await alive(), false, 'Owned Chrome process group still running; temporary profile preserved')
  await rm(root, { recursive: true, force: true })
  result.cleanupVerified = true
  process.off('SIGINT', interrupt)
  process.off('SIGTERM', interrupt)
}
process.stdout.write(JSON.stringify(result, null, 2) + '\n')
