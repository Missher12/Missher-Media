#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { constants as fsConstants } from 'node:fs'
import {
  chmod,
  copyFile,
  lstat,
  mkdir,
  readFile,
  realpath,
} from 'node:fs/promises'
import { homedir } from 'node:os'
import { delimiter, dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { verifyPackage } from './verify-package.mjs'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(scriptDirectory, '..')
const defaultArchive = join(pluginRoot, 'dist', 'dsh-media-missher-17.0.0.tgz')
/** Resolve an installed Desktop without downloading or starting another host. */
export async function resolveHarnessLayout(appRoot, externalPnpmPaths = [
  '/usr/local/bin/pnpm', '/opt/homebrew/bin/pnpm',
]) {
  if (appRoot === undefined) {
    for (const candidate of ['/Applications/DeepSeek Harness.app', join(homedir(), 'Applications/DeepSeek Harness.app')]) {
      try { return await resolveHarnessLayout(candidate, externalPnpmPaths) }
      catch (error) { if (error.message !== 'harness_layout_unsupported') throw error }
    }
    throw new Error('harness_layout_unsupported')
  }
  const legacy = {
    runtime: join(appRoot, 'Contents/MacOS/DeepSeek Harness'),
    cli: join(appRoot, 'Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js'),
    pnpm: join(appRoot, 'Contents/Resources/app.asar.unpacked/node_modules/pnpm/bin/pnpm.cjs'),
  }
  const modern = {
    runtime: join(appRoot, 'Contents/Resources/runtime/node/bin/node'),
    cli: join(appRoot, 'Contents/Resources/runtime/app/lib/bin.js'),
  }
  async function exists(path) {
    try { return (await lstat(path)).isFile() } catch (error) {
      if (error.code === 'ENOENT') return false
      throw error
    }
  }
  if (await exists(modern.runtime) && await exists(modern.cli)) {
    for (const candidate of externalPnpmPaths) {
      try {
        const pnpm = await realpath(candidate)
        if (await exists(pnpm)) return { ...modern, pnpm, pnpmBin: dirname(candidate) }
      } catch (error) { if (error.code !== 'ENOENT') throw error }
    }
    throw new Error('harness_external_pnpm_required')
  }
  if (await exists(legacy.runtime) && await exists(legacy.cli) && await exists(legacy.pnpm)) return legacy
  const desktop = {
    runtime: legacy.runtime,
    cli: join(appRoot, 'Contents/Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js'),
    pnpm: join(appRoot, 'Contents/Resources/runtime/pnpm/bin/pnpm.cjs'),
    pnpmBin: join(appRoot, 'Contents/Resources/runtime/bin'),
  }
  // Node cannot stat virtual ASAR members. The selected Electron validates the
  // exact CLI entry in regularFile before any profile or staging write.
  if (await exists(desktop.runtime) && await exists(join(appRoot, 'Contents/Resources/app.asar')) && await exists(desktop.pnpm)) return desktop
  throw new Error('harness_layout_unsupported')
}

export function harnessEnvironmentPath(runtime, pnpmBin) {
  return [dirname(runtime), pnpmBin, process.env.PATH].filter(Boolean).join(delimiter)
}

function help() {
  process.stdout.write(`Install Media@Missher into one DeepSeek Harness profile.

Usage:
  install-current-profile.mjs --archive <bundle.tgz> [--profile web]
                              [--runtime <electron>] [--cli <bin.js>]
                              [--pnpm <pnpm.cjs>] [--dsh-home <path>]

The archive is verified before the profile is changed. The existing profile
package.json is copied to a private timestamped backup first.
`)
}

function argumentsFrom(argv) {
  const result = {
    archive: defaultArchive,
    profile: 'web',
    runtime: undefined,
    cli: undefined,
    pnpm: undefined,
    dshHome: process.env.DSH_HOME ?? join(homedir(), '.dsh'),
  }
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index]
    if (key === '--') continue
    if (key === '--help' || key === '-h') return { help: true }
    const value = argv[index + 1]
    if (value === undefined || value.startsWith('--')) throw new Error(`argument_value_missing:${key}`)
    if (key === '--archive') result.archive = value
    else if (key === '--profile') result.profile = value
    else if (key === '--runtime') result.runtime = value
    else if (key === '--cli') result.cli = value
    else if (key === '--pnpm') result.pnpm = value
    else if (key === '--dsh-home') result.dshHome = value
    else throw new Error(`argument_unknown:${key}`)
    index += 1
  }
  return result
}

async function regularFile(path, code, runtime) {
  let metadata
  try { metadata = await lstat(path) }
  catch (error) {
    if (!runtime || !path.includes('/app.asar/') || !['ENOENT', 'ENOTDIR'].includes(error.code)) throw error
    const checked = spawnSync(runtime, ['-e', "try { const s = require('node:fs').lstatSync(process.argv[1]); process.exit(s.isFile() && !s.isSymbolicLink() ? 0 : 1) } catch { process.exit(1) }", path], {
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' }, shell: false, stdio: 'ignore', timeout: 5000,
    })
    if (checked.error || checked.status !== 0) throw new Error(code)
    return
  }
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error(code)
}

function run(runtime, cli, args, env, code) {
  const completed = spawnSync(runtime, [cli, ...args], {
    encoding: 'utf8',
    env,
    maxBuffer: 16 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  if (completed.error !== undefined || completed.status !== 0) {
    const missing = completed.stderr?.match(/Cannot find package '([@a-zA-Z0-9_./-]+)'/u)?.[1]
    const errorCode = completed.stderr?.match(/(?:Error \[|code: ')([A-Z][A-Z_]+)(?:\]|')/u)?.[1]
    throw new Error([code, errorCode, missing].filter(Boolean).join(':'))
  }
  return completed.stdout
}

async function backupProfilePackage(dshHome, profile) {
  const source = join(dshHome, 'profiles', profile, 'package.json')
  try {
    await regularFile(source, 'profile_package_invalid')
  } catch (error) {
    if (error?.code === 'ENOENT') return null
    throw error
  }
  const timestamp = new Date().toISOString().replaceAll(/[-:.]/gu, '')
  const directory = join(dshHome, 'backups', `media-missher-plugin-${timestamp}`)
  await mkdir(directory, { recursive: true, mode: 0o700 })
  if (process.platform !== 'win32') await chmod(directory, 0o700)
  const destination = join(directory, 'package.json')
  await copyFile(source, destination)
  if (process.platform !== 'win32') await chmod(destination, 0o600)
  return destination
}

async function stageVerifiedArchive(dshHome, verified) {
  const directory = join(dshHome, 'artifacts', 'media-missher')
  await mkdir(directory, { recursive: true, mode: 0o700 })
  if (process.platform !== 'win32') await chmod(directory, 0o700)
  const destination = join(
    directory,
    `dsh-media-missher-17.0.0-${verified.sha256.slice(0, 16)}.tgz`,
  )
  try {
    await copyFile(verified.archive, destination, fsConstants.COPYFILE_EXCL)
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error
  }
  if (process.platform !== 'win32') await chmod(destination, 0o600)
  const stagedSha256 = createHash('sha256')
    .update(await readFile(destination))
    .digest('hex')
  if (stagedSha256 !== verified.sha256) throw new Error('staged_archive_bytes_mismatch')
  return destination
}

export async function installCurrentProfile(
  argv = process.argv.slice(2),
  { writeOutput = true } = {},
) {
  const options = argumentsFrom(argv)
  if ('help' in options) {
    help()
    return null
  }
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/u.test(options.profile)) throw new Error('profile_name_invalid')
  const layout = options.runtime && options.cli && options.pnpm
    ? options : { ...await resolveHarnessLayout(), ...Object.fromEntries(Object.entries(options).filter(([, value]) => value !== undefined)) }
  const runtime = resolve(layout.runtime)
  const cli = resolve(layout.cli)
  const pnpm = resolve(layout.pnpm)
  const dshHome = resolve(options.dshHome)
  await Promise.all([
    regularFile(runtime, 'harness_runtime_missing'),
    regularFile(cli, 'harness_cli_missing', runtime),
    regularFile(pnpm, 'harness_pnpm_missing'),
  ])
  const verified = await verifyPackage(options.archive)
  const stagedArchive = await stageVerifiedArchive(dshHome, verified)
  const backup = await backupProfilePackage(dshHome, options.profile)
  const environment = {
    ...process.env,
    PATH: harnessEnvironmentPath(runtime, layout.pnpmBin),
    DSH_HOME: dshHome,
    DSH_DESKTOP_PNPM_ENTRY: pnpm,
    DSH_DESKTOP_NODE_EXECUTABLE: runtime,
    DSH_TELEMETRY_MODE: 'DISABLED',
    ELECTRON_RUN_AS_NODE: '1',
  }
  run(
    runtime,
    cli,
    ['plugin', '--profile', options.profile, 'add', '--force', stagedArchive],
    environment,
    'harness_plugin_add_failed',
  )
  const installedEntry = join(
    dshHome,
    'profiles',
    options.profile,
    'node_modules',
    'dsh-media-missher',
    'lib',
    'index.js',
  )
  const installedEntrySha256 = createHash('sha256')
    .update(await readFile(installedEntry))
    .digest('hex')
  if (installedEntrySha256 !== verified.entrySha256) {
    throw new Error('harness_plugin_bytes_mismatch')
  }
  run(runtime, '--input-type=module', [
    '-e', 'await import(process.argv[1])', pathToFileURL(installedEntry).href,
  ], environment, 'harness_plugin_load_failed')
  const configuration = run(
    runtime,
    cli,
    ['--profile', options.profile, '--dump-config'],
    environment,
    'harness_profile_verify_failed',
  )
  if (!configuration.includes('id: media-missher') || !configuration.includes('name: dsh-media-missher')) {
    throw new Error('harness_plugin_not_active')
  }
  const result = {
    ok: true,
    profile: options.profile,
    archive: verified.archive,
    bytes: verified.bytes,
    sha256: verified.sha256,
    stagedArchive,
    backup,
  }
  if (writeOutput) process.stdout.write(`${JSON.stringify(result)}\n`)
  return result
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await installCurrentProfile()
}
