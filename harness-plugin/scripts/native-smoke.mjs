#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import ExcelJS from 'exceljs'
import { installCurrentProfile, resolveHarnessLayout, harnessEnvironmentPath } from './install-current-profile.mjs'
import { verifyPackage } from './verify-package.mjs'

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const defaultArchive = join(pluginRoot, 'dist', 'dsh-media-missher-17.0.0.tgz')
const platforms = ['bilibili', 'xhs', 'douyin', 'weibo']

function help() {
  process.stdout.write(`Run an isolated native install/collection/export/uninstall smoke test.

Usage:
  native-smoke.mjs --archive <bundle.tgz> [--profile smoke]
                   [--runtime <electron>] [--cli <bin.js>] [--pnpm <pnpm.cjs>]
`)
}

function argumentsFrom(argv) {
  const result = {
    archive: defaultArchive,
    profile: 'media-smoke',
    runtime: undefined,
    cli: undefined,
    pnpm: undefined,
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
  if (!options.runtime || !options.cli || !options.pnpm) {
    const layout = await resolveHarnessLayout()
    for (const [key, value] of Object.entries(layout)) options[key] ??= value
  }
  const verified = await verifyPackage(options.archive)
  const dshHome = await realpath(await mkdtemp(join(tmpdir(), 'dsh-media-native-smoke-')))
  const isolatedUserHome = join(dshHome, 'user-home')
  const previousUserHome = process.env.HOME
  const profileRoot = join(dshHome, 'profiles', options.profile)
  const adjacentPath = join(profileRoot, 'adjacent.keep')
  const statePath = join(dshHome, 'media-missher', 'state.keep')
  const environment = {
    ...process.env,
    HOME: isolatedUserHome,
    PATH: harnessEnvironmentPath(options.runtime, options.pnpmBin),
    DSH_HOME: dshHome,
    DSH_DESKTOP_PNPM_ENTRY: resolve(options.pnpm),
    DSH_DESKTOP_NODE_EXECUTABLE: resolve(options.runtime),
    DSH_TELEMETRY_MODE: 'DISABLED',
    ELECTRON_RUN_AS_NODE: '1',
  }
  let installed = false
  try {
    await mkdir(isolatedUserHome, { mode: 0o700 })
    // Python shared safety follows the user HOME, independently of DSH_HOME.
    // In-process tool calls must inherit the same isolated home as the CLI.
    process.env.HOME = isolatedUserHome
    await mkdir(profileRoot, { recursive: true, mode: 0o700 })
    await mkdir(dirname(statePath), { recursive: true, mode: 0o700 })
    await writeFile(adjacentPath, 'preserve\n', { mode: 0o600 })
    await writeFile(statePath, 'preserve\n', { mode: 0o600 })
    await installCurrentProfile([
      '--archive', verified.archive,
      '--profile', options.profile,
      '--runtime', resolve(options.runtime),
      '--cli', resolve(options.cli),
      '--pnpm', resolve(options.pnpm),
      '--dsh-home', dshHome,
    ], { writeOutput: false })
    installed = true
    const packageBeforeRefresh = await readFile(join(profileRoot, 'package.json'), 'utf8')
    const refreshed = await installCurrentProfile([
      '--archive', verified.archive, '--profile', options.profile,
      '--runtime', resolve(options.runtime), '--cli', resolve(options.cli),
      '--pnpm', resolve(options.pnpm), '--dsh-home', dshHome,
    ], { writeOutput: false })
    if (!refreshed.backup || await readFile(refreshed.backup, 'utf8') !== packageBeforeRefresh) {
      throw new Error('native_smoke_refresh_backup_invalid')
    }
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
    const evidence = fixtureEvidence(runDirectory)
    const config = installedModule.normalizePluginConfig({
      defaultPlatforms: platforms.join(','),
      defaultCount: 10,
      defaultXhsComments: 0,
      defaultAllowNavigation: true,
      platformTimeoutSeconds: 300,
      executionTimeoutSeconds: 1260,
      maxCount: 50,
      profilePath: join(dshHome, 'media-missher', 'profile.json'),
      runtimeHome: join(dshHome, 'media-missher', 'runtime'),
      outputRoot: join(dshHome, 'media-missher', 'runs'),
    }, dshHome, isolatedUserHome)
    const context = { signal: new AbortController().signal }
    let emptyDeviceRuntimeCalls = 0
    const blankTool = installedModule.createMediaTool(config, {
      ensureRuntime: async () => { emptyDeviceRuntimeCalls += 1; throw new Error('blank_device_must_not_install') },
      processRunner: async () => { throw new Error('blank_device_must_not_spawn') },
    })
    const initial = await blankTool.execute({}, context)
    if (initial.status !== 'needs-input' || initial.totalCollected !== 0
      || JSON.stringify(initial.missingFields) !== JSON.stringify(['platforms', 'targets'])
      || emptyDeviceRuntimeCalls !== 0) throw new Error('native_smoke_blank_device_gate_invalid')
    const setupTool = installedModule.createSetupTool(config)
    for (const action of ['browser-check', 'browser-open']) {
      const blankBrowser = await setupTool.execute({ action, ...(action === 'browser-open' ? { confirm_open: true } : {}) }, context)
      if (blankBrowser.status !== 'needs-setup' || blankBrowser.browserStatus !== 'not-checked') throw new Error('native_smoke_blank_browser_gate_invalid')
    }
    const status = await setupTool.execute({ action: 'status' }, context)
    const templates = await setupTool.execute({ action: 'template' }, context)
    if (status.status !== 'needs-setup' || templates.status !== 'ok') throw new Error('native_smoke_setup_template_invalid')
    const templateBook = new ExcelJS.Workbook()
    await templateBook.xlsx.readFile(templates.artifactPath)
    if (templateBook.worksheets[0]?.rowCount !== 1) throw new Error('native_smoke_template_has_targets')
    const source = join(dshHome, 'creator-fixture.csv')
    await writeFile(source, 'platform,creator_name,homepage_url\nbilibili,Fixture B,https://space.bilibili.com/12345\nxhs,Fixture X,https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef01?xsec_token=do-not-retain\ndouyin,Fixture D,https://www.douyin.com/user/MS4wLjAB_fixture\nweibo,Fixture W,https://weibo.com/u/12345\n', { mode: 0o600 })
    const imported = await setupTool.execute({ action: 'import', input_path: source }, context)
    const xlsxSource = join(dshHome, 'creator-fixture.xlsx')
    const creatorRows = (await readFile(source, 'utf8')).trim().split('\n').slice(1).map(line => line.split(','))
    templateBook.worksheets[0].addRows(creatorRows)
    await writeFile(xlsxSource, Buffer.from(await templateBook.xlsx.writeBuffer()), { mode: 0o600 })
    const importedXlsx = await setupTool.execute({ action: 'import', input_path: xlsxSource }, context)
    if (importedXlsx.status !== 'ok' || importedXlsx.rowCount !== 4
      || await readFile(importedXlsx.metadataPath, 'utf8') !== await readFile(imported.metadataPath, 'utf8')) throw new Error('native_smoke_xlsx_import_invalid')
    const beforeActivation = await blankTool.execute({}, context)
    if (imported.status !== 'ok' || imported.rowCount !== 4 || beforeActivation.status !== 'needs-input' || emptyDeviceRuntimeCalls !== 0) throw new Error('native_smoke_import_gate_invalid')
    if ((await readFile(imported.metadataPath, 'utf8')).includes('do-not-retain')) throw new Error('native_smoke_import_retained_token')
    for (const path of [config.runtimeHome, config.outputRoot]) {
      try { await access(path); throw new Error('native_smoke_setup_created_runtime_or_runs') } catch (error) { if (error.code !== 'ENOENT') throw error }
    }
    const firstSelection = await setupTool.execute({ action: 'activate', import_id: imported.importId, rows: [2] }, context)
    if (firstSelection.status !== 'ok' || firstSelection.activePlatforms !== 'xhs') throw new Error('native_smoke_first_selection_invalid')
    const firstProfile = await readFile(config.profilePath)
    const selectedTool = installedModule.createMediaTool({ ...config, defaultPlatforms: ['bilibili'] }, {
      ensureRuntime: async () => {
        await mkdir(config.outputRoot, { recursive: true, mode: 0o700 })
        return { python: '/fixture/python', payloadRoot: '/fixture/payload' }
      },
      processRunner: async (_executable, args) => {
        if (args[args.indexOf('--platform') + 1] !== 'xhs') throw new Error('native_smoke_active_selection_masked')
        return { code: 1, signal: null, stdout: JSON.stringify({ status: 'preflight-failed', run_dir: null, evidence: [] }), stderr: '' }
      },
    })
    const selectedResult = await selectedTool.execute({ xhs_comments: 1 }, context)
    if (selectedResult.platforms !== 'xhs' || selectedResult.summary.includes('profile_selection_missing')) throw new Error('native_smoke_active_selection_invalid')
    const activated = await setupTool.execute({ action: 'activate', import_id: imported.importId, rows: [1, 2, 3, 4] }, context)
    if (activated.status !== 'ok' || activated.activePlatforms !== platforms.join(',')) throw new Error('native_smoke_activation_invalid')
    const backupRoot = join(dirname(config.profilePath), 'setup', 'backups')
    const backups = await readdir(backupRoot)
    if (backups.length !== 1 || !(await readFile(join(backupRoot, backups[0]))).equals(firstProfile)) throw new Error('native_smoke_creator_backup_invalid')
    const beforeBrowser = await readFile(config.profilePath)
    let aiBrowserLaunchRequests = 0
    const aiBrowserTool = installedModule.createSetupTool(config, {
      platform: 'darwin', environmentCdp: '',
      probe: async () => aiBrowserLaunchRequests === 0 ? { status: 'closed' } : { status: 'ready', session: 'a'.repeat(64) },
      pages: async () => ['xhs'],
      findChrome: async () => '/fixture/Google Chrome',
      launch: async (_executable, args) => {
        if (!args.includes('--remote-debugging-address=127.0.0.1') || !args.includes('--remote-debugging-port=9223')
          || !args.includes(`--user-data-dir=${join(dirname(config.profilePath), 'browser', 'chrome-profile')}`)
          || !args.at(-1).startsWith('file://') || args.some(arg => /^https?:/.test(arg))) throw new Error('native_smoke_ai_browser_arguments_invalid')
        aiBrowserLaunchRequests++
      },
    })
    const aiOpened = await aiBrowserTool.execute({ action: 'browser-open', confirm_open: true }, context)
    const aiReopened = await aiBrowserTool.execute({ action: 'browser-open', confirm_open: true }, context)
    const aiChecked = await aiBrowserTool.execute({ action: 'browser-check' }, context)
    if (aiOpened.status !== 'ok' || aiReopened.status !== 'ok' || aiBrowserLaunchRequests !== 1
      || aiChecked.browserIdentity !== 'ai-dedicated' || aiChecked.loginStatus !== 'not-checked'
      || aiChecked.openPlatforms !== 'xhs' || aiChecked.missingPlatforms !== 'bilibili,douyin,weibo') throw new Error('native_smoke_ai_browser_flow_invalid')
    const browserBackups = await readdir(backupRoot)
    if (!await Promise.all(browserBackups.map(async name => (await readFile(join(backupRoot, name))).equals(beforeBrowser))).then(matches => matches.some(Boolean))) throw new Error('native_smoke_ai_browser_backup_invalid')
    if (!(await readFile(aiOpened.artifactPath, 'utf8')).includes('AI 采集专用浏览器')) throw new Error('native_smoke_ai_browser_guide_invalid')
    await mkdir(runDirectory, { recursive: true, mode: 0o700 })
    const phaseTimings = platforms.map((platform, index) => ({ schema: 1, phase: 'platform-collection', state: 'completed', platform, completed: 10, requested: 10, elapsed_ms: (index + 1) * 100, duration_ms: 100 }))
    const tool = installedModule.createMediaTool(config, {
      ensureRuntime: async () => ({ python: '/fixture/python', payloadRoot: '/fixture/payload' }),
      processRunner: async (_executable, _args, options) => {
        for (const event of phaseTimings) await options.onProgress?.(event)
        return {
        code: 0,
        signal: null,
        stdout: JSON.stringify({
          status: 'success',
          run_dir: runDirectory,
          evidence: [evidence.manifestPath],
          phase_timings: phaseTimings,
          phase_timings_persisted: true,
        }),
        stderr: '',
        }
      },
      loadRunEvidence: async () => evidence,
    })
    const value = await tool.execute({}, { signal: new AbortController().signal })
    if (value.totalCollected !== 40 || value.requestedPerPlatform !== 10) {
      throw new Error('native_smoke_tool_result_invalid')
    }
    if (value.workbookPath !== '' || (await readdir(runDirectory)).some(name => /\.(?:xlsx|csv)$/i.test(name))) {
      throw new Error('native_smoke_collection_exported_without_selection')
    }

    // Exercise the actual installed offline tool and Python payload. Collection
    // above remains synthetic; these operations cannot connect to a browser.
    const pythonProbe = spawnSync('python3', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' })
    if (pythonProbe.status !== 0 || !pythonProbe.stdout.trim().startsWith('/')) throw new Error('native_smoke_python_unavailable')
    const pythonDirectory = join(config.runtimeHome, 'venv', 'bin')
    await mkdir(pythonDirectory, { recursive: true, mode: 0o700 })
    await symlink(pythonProbe.stdout.trim(), join(pythonDirectory, 'python'))
    for (const [suffix, observed, likes] of [['before', '2026-09-07T00:00:00Z', 1], ['after', '2026-09-07T01:00:00Z', 2]]) {
      const inner = join(config.outputRoot, `run-smoke-${suffix}`, 'run-engine')
      await mkdir(inner, { recursive: true, mode: 0o700 })
      await writeFile(join(inner, 'douyin.json'), JSON.stringify([{ platform: 'douyin', aweme_id: 'smoke-1', link: 'https://example.invalid/smoke', observed_at: observed, liked: likes }]), { mode: 0o600 })
      await writeFile(join(inner, 'manifest.json'), JSON.stringify({ counts: { douyin: 1 }, paths: { douyin: 'douyin.json' }, platforms: { douyin: 'complete' }, status: 'complete', diagnostics: { douyin: { kind: 'ok', code: 'ok' } } }), { mode: 0o600 })
    }
    const registered = []
    const guidance = []
    installedModule.apply({ get: name => name === 'systemPrompt' ? { section: value => guidance.push(value) } : undefined, dshHomePath: () => dshHome, tools: { register: tool => { registered.push(tool); return () => {} } } }, { ...config, defaultPlatforms: platforms.join(',') })
    if (guidance.length !== 1 || guidance[0].name !== 'media-missher:agent-guidance' || !guidance[0].text.includes('media_missher_setup')) throw new Error('native_smoke_agent_guidance_missing')
    const runsTool = registered.find(tool => tool.name === 'media_missher_runs')
    if (runsTool === undefined) throw new Error('native_smoke_runs_tool_missing')
    const listing = await runsTool.execute({ action: 'list' }, context)
    const exported = await runsTool.execute({ action: 'export', run_id: 'run-smoke-before', record_kinds: ['posts'], format: 'csv' }, context)
    const comparison = await runsTool.execute({ action: 'compare', before: 'run-smoke-before', after: 'run-smoke-after' }, context)
    const safety = await runsTool.execute({ action: 'xhs-status' }, context)
    const progress = await runsTool.execute({ action: 'progress' }, context)
    const progressSnapshot = JSON.parse(await readFile(progress.metadataPath, 'utf8'))
    if (progress.status !== 'ok' || progressSnapshot.status !== 'completed'
      || JSON.stringify(progressSnapshot.events) !== JSON.stringify(phaseTimings)
      || !value.summary.includes('platform-collection')) throw new Error('native_smoke_progress_invalid')
    await access(join(isolatedUserHome, '.local', 'share', 'media-missher-shared', 'state', 'xhs-safety.json'))
    for (const [action, result] of Object.entries({ list: listing, export: exported, compare: comparison, safety })) {
      if (result.status !== 'ok') throw new Error(`native_smoke_offline_runs_failed:${action}:${result.summary}`)
    }
    if (!listing.summary.includes('run-smoke-before') || !safety.summary.startsWith('ready;')) throw new Error(`native_smoke_offline_runs_invalid:${JSON.stringify({ listing: listing.summary, safety: safety.summary })}`)
    await access(exported.artifactPath)
    await access(exported.metadataPath)
    const exportedCsv = await readFile(exported.artifactPath, 'utf8')
    if (!exportedCsv.includes('smoke-1') || exportedCsv.trim().split(/\r?\n/u).length !== 2) {
      throw new Error('native_smoke_explicit_export_invalid')
    }
    const compared = JSON.parse(await readFile(comparison.artifactPath, 'utf8'))
    if (compared.freshness_claim !== false || compared.records[0]?.before_observed_at === compared.records[0]?.after_observed_at) throw new Error('native_smoke_history_observation_invalid')

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
      collectionAutoExported: false,
      explicitExportRunId: 'run-smoke-before',
      explicitExportFormat: 'csv',
      explicitExportRecords: 1,
      adjacentStatePreserved: true,
      sameVersionRefreshVerified: true,
      offlineRunsActions: ['list', 'export', 'compare', 'xhs-status', 'progress'],
      installedProgressSnapshotVerified: true,
      progressEvidence: 'synthetic phase events through installed tool, private snapshot and final summary',
      offlineSetupActions: ['status', 'template', 'import', 'activate'],
      installedImportFormats: ['csv', 'xlsx'],
      emptyDeviceRuntimeCalls,
      setupRuntimeOrRunDirectories: 0,
      activeSelectionOverridesLegacyDefaults: true,
      setupProfileBackupVerified: true,
      browserLaunches: 0,
      aiBrowserActions: ['browser-open', 'browser-check'],
      aiBrowserLaunchRequests,
      aiBrowserLaunchMode: 'injected process fixture; no real browser',
      aiBrowserGuideVerified: true,
      loginStatusNeverInferred: true,
      livePlatformRequests: 0,
      sharedSafetyScopeIsolated: true,
      installedGuidanceHookVerified: true,
      guidanceHookEvidence: 'installed entry with injected native-section service fixture; not an LLM behavior test',
    }
    process.stdout.write(`${JSON.stringify(result)}\n`)
    return result
  } finally {
    if (previousUserHome === undefined) delete process.env.HOME
    else process.env.HOME = previousUserHome
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
