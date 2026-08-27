#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import ExcelJS from 'exceljs'
import { verifyPackage } from './verify-package.mjs'

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const defaultArchive = join(pluginRoot, 'dist', 'dsh-media-missher-0.1.0.tgz')
const defaultRuntime = '/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness'
const defaultCli = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js'
const defaultPnpm = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/pnpm/bin/pnpm.cjs'
const platforms = ['bilibili', 'xhs', 'douyin', 'weibo']

function help() {
  process.stdout.write(`Run an isolated native install/tool/workbook/uninstall smoke test.

Usage:
  native-smoke.mjs --archive <bundle.tgz> [--profile smoke]
                   [--runtime <electron>] [--cli <bin.js>] [--pnpm <pnpm.cjs>]
`)
}

function argumentsFrom(argv) {
  const result = {
    archive: defaultArchive,
    profile: 'media-smoke',
    runtime: defaultRuntime,
    cli: defaultCli,
    pnpm: defaultPnpm,
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
    else throw new Error(`argument_unknown:${key}`)
    index += 1
  }
  return result
}

function run(runtime, cli, args, environment, code) {
  const completed = spawnSync(runtime, [cli, ...args], {
    encoding: 'utf8',
    env: environment,
    maxBuffer: 16 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  if (completed.error !== undefined || completed.status !== 0) throw new Error(code)
  return completed.stdout
}

function fixtureEvidence(runDirectory) {
  const records = Object.fromEntries(platforms.map(platform => [
    platform,
    Array.from({ length: 10 }, (_, index) => ({
      native_id: `${platform}-${index + 1}`,
      title: `${platform} smoke ${index + 1}`,
      url: `https://example.invalid/${platform}/${index + 1}`,
    })),
  ]))
  return {
    runDirectory,
    manifestPath: join(runDirectory, 'manifest.json'),
    runStatus: 'complete',
    records,
    platformStatuses: Object.fromEntries(platforms.map(platform => [platform, 'complete'])),
    diagnostics: Object.fromEntries(platforms.map(platform => [platform, { kind: 'ok', code: 'ok' }])),
    totalCollected: 40,
  }
}

export async function nativeSmoke(argv = process.argv.slice(2)) {
  const options = argumentsFrom(argv)
  if ('help' in options) {
    help()
    return null
  }
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/u.test(options.profile)) throw new Error('profile_name_invalid')
  const verified = await verifyPackage(options.archive)
  const dshHome = await mkdtemp(join(tmpdir(), 'dsh-media-native-smoke-'))
  const profileRoot = join(dshHome, 'profiles', options.profile)
  const adjacentPath = join(profileRoot, 'adjacent.keep')
  const statePath = join(dshHome, 'media-missher', 'state.keep')
  const environment = {
    ...process.env,
    DSH_HOME: dshHome,
    DSH_DESKTOP_PNPM_ENTRY: resolve(options.pnpm),
    DSH_TELEMETRY_MODE: 'DISABLED',
    ELECTRON_RUN_AS_NODE: '1',
  }
  let installed = false
  try {
    await mkdir(profileRoot, { recursive: true, mode: 0o700 })
    await mkdir(dirname(statePath), { recursive: true, mode: 0o700 })
    await writeFile(adjacentPath, 'preserve\n', { mode: 0o600 })
    await writeFile(statePath, 'preserve\n', { mode: 0o600 })
    run(
      resolve(options.runtime),
      resolve(options.cli),
      ['plugin', '--profile', options.profile, 'add', verified.archive],
      environment,
      'native_smoke_install_failed',
    )
    installed = true
    const configuration = run(
      resolve(options.runtime),
      resolve(options.cli),
      ['--profile', options.profile, '--dump-config'],
      environment,
      'native_smoke_dump_failed',
    )
    if (!configuration.includes('id: media-missher') || !configuration.includes('name: dsh-media-missher')) {
      throw new Error('native_smoke_plugin_inactive')
    }

    const installedModulePath = join(profileRoot, 'node_modules', 'dsh-media-missher', 'lib', 'index.js')
    const installedModule = await import(pathToFileURL(installedModulePath).href)
    const runDirectory = join(dshHome, 'media-missher', 'runs', 'fixture')
    await mkdir(runDirectory, { recursive: true, mode: 0o700 })
    const evidence = fixtureEvidence(runDirectory)
    const config = {
      defaultPlatforms: platforms,
      defaultCount: 10,
      defaultXhsComments: 0,
      defaultAllowNavigation: true,
      platformTimeoutSeconds: 300,
      executionTimeoutSeconds: 1260,
      maxCount: 50,
      profilePath: join(dshHome, 'media-missher', 'profile.json'),
      runtimeHome: join(dshHome, 'media-missher', 'runtime'),
      outputRoot: join(dshHome, 'media-missher', 'runs'),
    }
    const tool = installedModule.createMediaTool(config, {
      ensureRuntime: async () => ({ python: '/fixture/python', payloadRoot: '/fixture/payload' }),
      processRunner: async () => ({
        code: 0,
        signal: null,
        stdout: JSON.stringify({
          status: 'success',
          run_dir: runDirectory,
          evidence: [evidence.manifestPath],
        }),
        stderr: '',
      }),
      loadRunEvidence: async () => evidence,
    })
    const value = await tool.execute({}, { signal: new AbortController().signal })
    if (value.totalCollected !== 40 || value.requestedPerPlatform !== 10) {
      throw new Error('native_smoke_tool_result_invalid')
    }
    await access(value.workbookPath)
    const workbook = new ExcelJS.Workbook()
    await workbook.xlsx.readFile(value.workbookPath)
    if (
      workbook.worksheets.map(sheet => sheet.name).join(',')
      !== 'Summary,All Platforms,Bilibili,Xiaohongshu,Douyin,Weibo'
      || workbook.getWorksheet('All Platforms')?.rowCount !== 41
    ) throw new Error('native_smoke_workbook_invalid')

    run(
      resolve(options.runtime),
      resolve(options.cli),
      ['plugin', '--profile', options.profile, 'remove', 'dsh-media-missher'],
      environment,
      'native_smoke_remove_failed',
    )
    installed = false
    const afterRemoval = run(
      resolve(options.runtime),
      resolve(options.cli),
      ['--profile', options.profile, '--dump-config'],
      environment,
      'native_smoke_post_remove_dump_failed',
    )
    if (afterRemoval.includes('id: media-missher') || afterRemoval.includes('name: dsh-media-missher')) {
      throw new Error('native_smoke_remove_incomplete')
    }
    if (await readFile(adjacentPath, 'utf8') !== 'preserve\n' || await readFile(statePath, 'utf8') !== 'preserve\n') {
      throw new Error('native_smoke_adjacent_state_changed')
    }
    const result = {
      ok: true,
      profile: options.profile,
      archive: verified.archive,
      sha256: verified.sha256,
      totalCollected: value.totalCollected,
      workbookSheets: workbook.worksheets.length,
      adjacentStatePreserved: true,
    }
    process.stdout.write(`${JSON.stringify(result)}\n`)
    return result
  } finally {
    if (installed) {
      run(
        resolve(options.runtime),
        resolve(options.cli),
        ['plugin', '--profile', options.profile, 'remove', 'dsh-media-missher'],
        environment,
        'native_smoke_cleanup_failed',
      )
    }
    await rm(dshHome, { recursive: true, force: true })
  }
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await nativeSmoke()
}
