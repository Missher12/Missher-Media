#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import {
  chmod,
  copyFile,
  lstat,
  mkdir,
} from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { verifyPackage } from './verify-package.mjs'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(scriptDirectory, '..')
const defaultArchive = join(pluginRoot, 'dist', 'dsh-media-missher-0.1.0.tgz')
const defaultRuntime = '/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness'
const defaultCli = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js'
const defaultPnpm = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/pnpm/bin/pnpm.cjs'

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
    runtime: defaultRuntime,
    cli: defaultCli,
    pnpm: defaultPnpm,
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

async function regularFile(path, code) {
  const metadata = await lstat(path)
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error(code)
}

function run(runtime, cli, args, env, code) {
  const completed = spawnSync(runtime, [cli, ...args], {
    encoding: 'utf8',
    env,
    maxBuffer: 16 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  if (completed.error !== undefined || completed.status !== 0) throw new Error(code)
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

export async function installCurrentProfile(argv = process.argv.slice(2)) {
  const options = argumentsFrom(argv)
  if ('help' in options) {
    help()
    return null
  }
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/u.test(options.profile)) throw new Error('profile_name_invalid')
  const runtime = resolve(options.runtime)
  const cli = resolve(options.cli)
  const pnpm = resolve(options.pnpm)
  const dshHome = resolve(options.dshHome)
  await Promise.all([
    regularFile(runtime, 'harness_runtime_missing'),
    regularFile(cli, 'harness_cli_missing'),
    regularFile(pnpm, 'harness_pnpm_missing'),
  ])
  const verified = await verifyPackage(options.archive)
  const backup = await backupProfilePackage(dshHome, options.profile)
  const environment = {
    ...process.env,
    DSH_HOME: dshHome,
    DSH_DESKTOP_PNPM_ENTRY: pnpm,
    DSH_TELEMETRY_MODE: 'DISABLED',
    ELECTRON_RUN_AS_NODE: '1',
  }
  run(
    runtime,
    cli,
    ['plugin', '--profile', options.profile, 'add', verified.archive],
    environment,
    'harness_plugin_add_failed',
  )
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
    backup,
  }
  process.stdout.write(`${JSON.stringify(result)}\n`)
  return result
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await installCurrentProfile()
}
