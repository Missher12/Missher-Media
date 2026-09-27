#!/usr/bin/env node
// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { createHash, randomUUID } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { lstat, mkdir, mkdtemp, open, readFile, realpath, rename, rm, unlink, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, isAbsolute, join, parse, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { pathToFileURL } from 'node:url'
import { inspectArchive } from './archive.mjs'
import { checkStorage } from '../src/platform.mjs'

const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const missing = error => error?.code === 'ENOENT'
const identity = { schema: 1, product: '@missher/media-missher' }
const maxArchive = 16 * 1024 * 1024

async function pathSafe(path) {
  if (!isAbsolute(path) || path.includes('\0') || resolve(path) === parse(path).root) throw new Error('install_path_invalid')
  for (let cursor = resolve(path); cursor !== dirname(cursor); cursor = dirname(cursor)) {
    try { if ((await lstat(cursor)).isSymbolicLink()) throw new Error('install_path_symlink') }
    catch (error) { if (!missing(error)) throw error }
  }
}
async function directory(path, privateMode = true) {
  await pathSafe(path)
  await mkdir(path, { recursive: true, mode: 0o700 })
  const stat = await lstat(path)
  if (!stat.isDirectory() || stat.uid !== process.getuid() || (stat.mode & (privateMode ? 0o077 : 0o022))) throw new Error('install_directory_untrusted')
}
async function regular(path, max = 8192) {
  await pathSafe(path)
  const stat = await lstat(path)
  if (!stat.isFile() || stat.nlink !== 1 || stat.size > max) throw new Error('install_file_invalid')
  return readFile(path)
}
async function owned(path) {
  const bytes = await regular(path)
  const stat = await lstat(path)
  if (stat.uid !== process.getuid() || stat.mode & 0o077) throw new Error('install_file_untrusted')
  return bytes
}
async function optional(path) {
  try { return await owned(path) }
  catch (error) { if (missing(error)) return undefined; throw error }
}
async function atomic(path, bytes) {
  const temporary = join(dirname(path), `.media-install-${randomUUID()}`)
  try {
    await writeFile(temporary, bytes, { flag: 'wx', mode: 0o700 })
    await rename(temporary, path)
  } finally { await unlink(temporary).catch(error => { if (!missing(error)) throw error }) }
}

async function acquireLock(path) {
  let handle
  try { handle = await open(path, 'wx', 0o600) }
  catch (error) { if (error.code === 'EEXIST') throw new Error('install_busy'); throw error }
  const stat = await handle.stat()
  return async () => {
    await handle.close()
    try {
      const current = await lstat(path)
      if (current.dev === stat.dev && current.ino === stat.ino) await unlink(path)
    } catch (error) { if (!missing(error)) throw error }
  }
}

function liveGroup(pid) {
  if (!pid) return false
  try { process.kill(-pid, 0) }
  catch (error) {
    if (error.code === 'ESRCH') return false
    // macOS can report EPERM for a group containing only adopted zombies.
    if (error.code !== 'EPERM') throw error
  }
  // Only process metadata is inspected; signals remain bound to our original child PGID.
  const observed = spawnSync('/bin/ps', ['-A', '-o', 'pgid=,stat='], { encoding: 'utf8', timeout: 2000, maxBuffer: 512 * 1024, shell: false })
  if (observed.error || observed.status !== 0) throw new Error('install_cleanup_unverified')
  return observed.stdout.split('\n').some(line => {
    const match = /^\s*(\d+)\s+(\S+)/.exec(line)
    return match && Number(match[1]) === pid && !match[2].startsWith('Z')
  })
}

async function finishGroup(pid) {
  if (!pid) return
  try { process.kill(-pid, 'SIGKILL') }
  catch (error) {
    if (error.code === 'ESRCH') return
    if (error.code !== 'EPERM' || liveGroup(pid)) throw error
    return
  }
  const deadline = Date.now() + 2000
  while (liveGroup(pid)) {
    if (Date.now() >= deadline) throw new Error('install_cleanup_unverified')
    await new Promise(resolve => setTimeout(resolve, 25))
  }
}

export function runInstallerProcess(command, args, options = {}) {
  return new Promise((resolveResult, reject) => {
    options.signal?.throwIfAborted()
    const child = spawn(command, args, { cwd: options.cwd, env: { ...process.env, npm_config_ignore_scripts: 'true' }, shell: false, detached: true, stdio: ['ignore', 'pipe', 'pipe'] })
    let bytes = 0, stdout = '', error, escalation
    const stop = () => {
      if (child.pid) try { process.kill(-child.pid, 'SIGTERM') } catch (caught) { if (caught.code !== 'ESRCH') error ??= new Error('install_stop_failed') }
      escalation ??= setTimeout(() => { if (child.pid) try { process.kill(-child.pid, 'SIGKILL') } catch {} }, 2000)
    }
    const abort = () => { error ??= new Error('install_cancelled'); stop() }
    const timeout = setTimeout(() => { error ??= new Error('install_process_timeout'); stop() }, 180000)
    const consume = (chunk, keep) => {
      bytes += chunk.length
      if (bytes > 4 * 1024 * 1024) { error ??= new Error('install_output_limit'); stop() }
      else if (keep) stdout += chunk.toString('utf8')
    }
    child.stdout.on('data', chunk => consume(chunk, true))
    child.stderr.on('data', chunk => consume(chunk, false))
    child.once('error', () => { error = new Error('install_process_unavailable') })
    options.signal?.addEventListener('abort', abort, { once: true })
    child.once('close', async code => {
      clearTimeout(timeout); clearTimeout(escalation)
      options.signal?.removeEventListener('abort', abort)
      if (error || code !== 0) {
        try { await finishGroup(child.pid) }
        catch (cause) {
          const failure = new Error('install_cleanup_unverified', { cause })
          failure.preserveRelease = true
          reject(failure); return
        }
        reject(error ?? new Error('install_process_failed'))
      } else resolveResult(stdout)
    })
    if (options.signal?.aborted) abort()
  })
}

async function download(urlText, signal) {
  let url = new URL(urlText), response
  const boundedSignal = AbortSignal.any([signal, AbortSignal.timeout(60000)])
  for (let hops = 0; hops <= 4; hops++) {
    if (url.protocol !== 'https:' || url.username || url.password || url.hash) throw new Error('install_url_invalid')
    response = await fetch(url, { redirect: 'manual', signal: boundedSignal })
    if (![301, 302, 303, 307, 308].includes(response.status)) break
    const location = response.headers.get('location')
    await response.body?.cancel()
    if (!location || hops === 4) throw new Error('install_download_redirect_invalid')
    url = new URL(location, url)
  }
  if (!response.ok || !response.body) throw new Error('install_download_failed')
  const chunks = []; let size = 0
  for await (const chunk of response.body) {
    size += chunk.length
    if (size > maxArchive) throw new Error('archive_too_large')
    chunks.push(chunk)
  }
  return Buffer.concat(chunks)
}

/** User-local install. Archive bytes are pinned before npm sees them; no lifecycle scripts run. */
export async function install(options, dependencies = {}) {
  if (!['darwin', 'linux'].includes(process.platform)) throw new Error('install_use_windows_wsl_entry')
  const [major, minor] = process.versions.node.split('.').map(Number)
  if (major < 22 || major === 22 && minor < 19) throw new Error('install_node_22_19_required')
  if (!/^[a-fA-F0-9]{64}$/.test(options.sha256 ?? '') || Boolean(options.archive) === Boolean(options.url)) throw new Error('install_arguments_invalid')
  const signal = options.signal ?? new AbortController().signal
  signal.throwIfAborted()
  const bytes = options.archive ? await regular(resolve(options.archive), maxArchive) : await download(options.url, signal)
  const sha256 = digest(bytes)
  if (sha256 !== options.sha256.toLowerCase()) throw new Error('install_checksum_mismatch')
  const { manifest, files } = inspectArchive(bytes)
  const home = await realpath(homedir())
  const root = resolve(options.home ?? join(home, '.local/share/media-missher-cli'))
  const bin = resolve(options.binDir ?? join(home, '.local/bin'))
  if (options.home && !isAbsolute(options.home) || options.binDir && !isAbsolute(options.binDir)) throw new Error('install_path_invalid')
  await checkStorage(home, [root, bin])
  if (root === bin || bin.startsWith(`${root}/`) || root.startsWith(`${bin}/`)) throw new Error('install_path_overlap')
  await directory(root)
  const ownerPath = join(root, '.owner.json')
  const owner = await optional(ownerPath)
  if (owner) {
    if (owner.toString() !== JSON.stringify(identity) + '\n') throw new Error('install_owner_invalid')
  } else {
    // Never adopt an unknown existing directory.
    const { readdir } = await import('node:fs/promises')
    if ((await readdir(root)).length) throw new Error('install_directory_unknown')
    await writeFile(ownerPath, JSON.stringify(identity) + '\n', { flag: 'wx', mode: 0o600 })
  }
  const lock = join(root, '.install.lock')
  const releaseRootLock = await acquireLock(lock)
  let release, activated = false, oldLauncher, oldState
  let releaseBinLock
  const launcher = join(bin, 'media-missher'), statePath = join(root, '.current.json')
  try {
    await directory(bin, false)
    releaseBinLock = await acquireLock(join(bin, '.media-missher-install.lock'))
    oldLauncher = await optional(launcher)
    oldState = await optional(statePath)
    if (oldLauncher || oldState) {
      let state
      try { state = JSON.parse(oldState?.toString()) } catch { throw new Error('install_launcher_conflict') }
      if (!oldLauncher || state?.launcher !== launcher || state.launcherSha256 !== digest(oldLauncher)) throw new Error('install_launcher_conflict')
    }
    await directory(join(root, 'releases'))
    release = await mkdtemp(join(root, 'releases', `v${manifest.version}-`))
    const archive = join(release, 'verified.tgz')
    await writeFile(archive, bytes, { flag: 'wx', mode: 0o600 })
    const runner = dependencies.run ?? runInstallerProcess
    await runner('npm', ['install', '--prefix', release, '--ignore-scripts', '--no-audit', '--no-fund', '--omit=dev', '--no-package-lock', archive], { signal, cwd: release })
    const packageRoot = join(release, 'node_modules/@missher/media-missher')
    for (const [name, content] of files) {
      const installed = await regular(join(packageRoot, name.slice(8)), maxArchive)
      if (!installed.equals(content)) throw new Error('install_payload_mismatch')
    }
    const executable = join(packageRoot, manifest.bin['media-missher'])
    const version = await runner(process.execPath, [executable, '--version'], { signal, cwd: release })
    if (!version.includes(manifest.version)) throw new Error('install_smoke_failed')
    await runner(process.execPath, [executable, '--help'], { signal, cwd: release })
    signal.throwIfAborted()
    const wrapper = Buffer.from(`#!/usr/bin/env node\n// Media@Missher managed launcher. Copyright (c) 2026 Missher.\nprocess.argv[1] = ${JSON.stringify(executable)};
await import(${JSON.stringify(pathToFileURL(executable).href)});\n`)
    if (oldLauncher) await writeFile(join(release, 'previous-launcher'), oldLauncher, { mode: 0o600 })
    if (oldState) await writeFile(join(release, 'previous-state.json'), oldState, { mode: 0o600 })
    // Recheck ownership immediately before replacing the one public entry point.
    const current = await optional(launcher), stateNow = await optional(statePath)
    if (Boolean(current) !== Boolean(oldLauncher) || current && !current.equals(oldLauncher)
      || Boolean(stateNow) !== Boolean(oldState) || stateNow && !stateNow.equals(oldState)) throw new Error('install_changed_during_setup')
    await atomic(launcher, wrapper)
    activated = true
    await atomic(statePath, JSON.stringify({ ...identity, version: manifest.version, sha256, launcher, launcherSha256: digest(wrapper), release }) + '\n')
    return { status: 'ok', version: manifest.version, sha256, executable: launcher, release, next: 'Run install-skill for your Agent, then doctor. Browser and login have not been checked.' }
  } catch (error) {
    if (activated) {
      if (oldLauncher) await atomic(launcher, oldLauncher); else await unlink(launcher)
      if (oldState) await atomic(statePath, oldState); else await unlink(statePath).catch(caught => { if (!missing(caught)) throw caught })
    }
    if (release && error.preserveRelease !== true) await rm(release, { recursive: true, force: true })
    throw error
  } finally { try { await releaseBinLock?.() } finally { await releaseRootLock() } }
}

async function main() {
  const { values, positionals } = parseArgs({ allowPositionals: true, options: { archive: { type: 'string' }, url: { type: 'string' }, sha256: { type: 'string' }, home: { type: 'string' }, 'bin-dir': { type: 'string' }, help: { type: 'boolean' } } })
  if (positionals.length) throw new Error('install_arguments_invalid')
  if (values.help) { process.stdout.write('Install Media@Missher CLI: --archive /absolute/package.tgz OR --url https://... --sha256 HEX [--home PATH] [--bin-dir PATH]\nRequires Node >=22.19 and npm; Windows uses install.ps1 with WSL2. No browser or collection starts.\n'); return }
  const controller = new AbortController(); let exitCode = 0
  const interrupt = () => { exitCode ||= 130; controller.abort() }
  const terminate = () => { exitCode ||= 143; controller.abort() }
  process.on('SIGINT', interrupt); process.on('SIGTERM', terminate)
  try { process.stdout.write(JSON.stringify(await install({ ...values, binDir: values['bin-dir'], signal: controller.signal }), null, 2) + '\n') }
  finally { process.off('SIGINT', interrupt); process.off('SIGTERM', terminate); if (exitCode) process.exitCode = exitCode }
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try { await main() }
  catch (error) { process.stdout.write(JSON.stringify({ status: 'failed', code: /^(?:install|archive|platform)_[a-z0-9_]+$/.test(error?.message) ? error.message : 'install_failed', next: 'Use a normal Linux user with private files in its native Linux HOME on WSL2. Follow AGENT_INSTALL.md; preserve existing files.' }) + '\n'); process.exitCode ||= 1 }
}
