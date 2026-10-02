#!/usr/bin/env node
import { capabilities } from '../src/capabilities.mjs'
import { constants } from 'node:fs'
import { access, lstat, open, realpath } from 'node:fs/promises'
import { homedir, release as systemRelease } from 'node:os'
import { dirname, isAbsolute, join, parse, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { installSkill, listAgents, SkillInstallError } from '../src/skills.mjs'
import { checkStorage, StorageError, wslEnvironment } from '../src/platform.mjs'
import {
  BACKENDS, COUNT_MODES, EXPORT_FORMATS, EXPORT_RECORD_KINDS, MAX_TARGETS, PLATFORMS, TARGET_ERROR_CODES, TARGET_MODES, TargetError,
  normalizeExportSelection, normalizeTarget, normalizeTargets, parseCountMode, resolveBackend, targetIdentity,
} from '../src/targets.mjs'

const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const RUNTIME_REQUIRED = '17.0.2'
const MAX_COUNT = 500
const MAX_RUN_DEADLINE_SECONDS = 86400
const COMMON = ['profile', 'runtime-home', 'output-root']
const FLAGS = new Set(['allow-navigation', 'confirm-open', 'list', 'overwrite'])
const REPEATABLE = new Set(['target', 'targets'])
const SETUP = { status: [], template: [], import: ['file'], activate: ['import-id', 'rows', 'target'], 'browser-check': [], 'browser-open': ['confirm-open'] }
const RUNS = { list: [], export: ['run-id', 'format', 'record-kinds', 'platforms', 'topics', 'targets', 'fields', 'field-groups', 'file-name', 'overwrite'], compare: ['before', 'after'], 'xhs-status': [], progress: [] }
const COLLECT = [...COMMON, 'platforms', 'count', 'count-mode', 'backend', 'run-deadline', 'xhs-comments', 'allow-navigation', 'resume-run', 'target', 'topic']
const EXPORT_SELECTION = ['record-kinds', 'platforms', 'topics', 'targets', 'fields', 'field-groups', 'file-name', 'overwrite']
const NEXT_SETUP = ['Run media-missher setup template; fill in platform, creator name and complete official homepage.', 'Run media-missher setup import --file /absolute/creators.xlsx, review the returned preview, then setup activate --import-id ID --rows 1.']
const BROWSER_FAILURE_GUIDANCE = {
  setup_browser_graphical_session_required: 'Open a graphical Linux desktop session or WSLg session in the same Linux environment, then run the explicitly requested browser preparation there. DISPLAY or WAYLAND_DISPLAY must come from that working session. Keep the selected creators and let the user log in manually.',
  setup_browser_root_unsupported: 'Run the Agent CLI and Chrome as a non-root Linux user in the same user HOME. Keep the existing creator selection and Chrome sandbox enabled; rerun browser preparation only under that user.',
  setup_browser_platform_unsupported: 'Use supported Chrome on macOS or Linux. On Windows, use the delivered install.ps1 entry with WSL2 and WSLg, keeping the Agent CLI and browser in the same Linux HOME. Native Windows browser preparation is unsupported.',
}

class CliError extends Error {
  constructor(code = 'cli_arguments_invalid') { super(code); this.code = code }
}
const fail = () => { throw new CliError() }

function absolute(value) {
  if (typeof value !== 'string' || !value || /[\u0000-\u001f\u007f]/u.test(value) || !isAbsolute(value) || resolve(value) === parse(value).root) fail()
  return resolve(value)
}

function integer(value, low, high) {
  if (!/^(?:0|[1-9][0-9]*)$/u.test(value ?? '')) fail()
  const number = Number(value)
  if (!Number.isSafeInteger(number) || number < low || number > high) fail()
  return number
}

function runId(value) {
  if (typeof value !== 'string' || !/^run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(value)) fail()
  return value
}

function commaList(value) {
  const items = String(value).split(',').map(item => item.trim())
  if (!items.length || items.some(item => item === '')) fail()
  return items
}

/**
 * Split one `PLATFORM:MODE:VALUE` argument and validate it with normalizeTarget.
 * A malformed shape stays a CLI argument error; a rejected target surfaces its
 * fixed target code. Neither path echoes the supplied text.
 */
function targetFromArgument(value) {
  const parts = String(value).split(':')
  if (parts.length < 3) fail()
  const platform = parts[0].trim().toLowerCase()
  const mode = parts[1].trim().toLowerCase()
  if (!PLATFORMS.includes(platform) || !TARGET_MODES.includes(mode)) fail()
  const rest = parts.slice(2)
  if (!rest.join(':')) fail()
  if (mode === 'creator') {
    const text = rest.join(':')
    if (text.startsWith('https://')) return normalizeTarget({ platform, mode, homepage: text })
    if (platform === 'xhs' || platform === 'douyin') return normalizeTarget({ platform, mode, uid: text })
    if (/^[0-9]{1,32}$/u.test(text)) return normalizeTarget({ platform, mode, uid: text })
    if (/^@?[A-Za-z0-9_]{1,15}$/u.test(text)) return normalizeTarget({ platform, mode, handle: text })
    return fail()
  }
  if (mode === 'search') {
    const sort = ['latest', 'top'].includes(rest[0].toLowerCase()) && rest.length > 1 ? rest.shift().toLowerCase() : undefined
    return normalizeTarget({ platform, mode, keyword: rest.join(':'), ...(sort === undefined ? {} : { sort }) })
  }
  const topicKind = ['topic', 'super'].includes(rest[0].toLowerCase()) && rest.length > 1 ? rest.shift().toLowerCase() : undefined
  return normalizeTarget({ platform, mode, topic: rest.join(':'), ...(topicKind === undefined ? {} : { topicKind }) })
}

/** The shared library consumes snake_case target fields and never a display label as identity. */
function wireTarget(target) {
  return {
    platform: target.platform,
    mode: target.mode,
    ...(target.label === undefined ? {} : { label: target.label }),
    ...(target.uid === undefined ? {} : { uid: target.uid }),
    ...(target.handle === undefined ? {} : { handle: target.handle }),
    ...(target.homepage === undefined ? {} : { homepage: target.homepage }),
    ...(target.keyword === undefined ? {} : { keyword: target.keyword }),
    ...(target.topic === undefined ? {} : { topic: target.topic }),
    ...(target.topicKind === undefined ? {} : { topic_kind: target.topicKind }),
    ...(target.sort === undefined ? {} : { sort: target.sort }),
  }
}

/** The validated export selection as one `args.export` object for the shared library. */
function wireExport(selection) {
  return {
    run_id: selection.runId,
    record_kinds: selection.recordKinds,
    platforms: selection.platforms,
    topics: selection.topics,
    targets: selection.targets,
    fields: selection.fields,
    field_groups: selection.fieldGroups,
    format: selection.format,
    ...(selection.fileName === undefined ? {} : { file_name: selection.fileName }),
    overwrite: selection.overwrite,
  }
}

/** Validate the complete command before importing factories or touching user paths. */
export function parseCli(argv) {
  if (!Array.isArray(argv) || argv.some(value => typeof value !== 'string')) fail()
  if (argv.length === 0 || (argv.length === 1 && argv[0] === '--help')) return { command: 'help', options: {} }
  if (argv.length === 1 && argv[0] === '--version') return { command: 'version', options: {} }
  const command = argv[0]
  let action
  let start = 1
  let allowed
  if (command === 'setup' || command === 'runs') {
    action = argv[1]
    const table = command === 'setup' ? SETUP : RUNS
    if (!Object.hasOwn(table, action ?? '')) fail()
    allowed = [...COMMON, ...table[action]]
    start = 2
  } else if (command === 'capabilities') allowed = []
  else if (command === 'doctor') allowed = COMMON
  else if (command === 'collect') allowed = COLLECT
  else if (command === 'install-skill') allowed = ['list', 'agent', 'skill-root']
  else fail()
  const options = {}
  for (let index = start; index < argv.length; index++) {
    const match = /^--([a-z][a-z-]*)(?:=(.*))?$/u.exec(argv[index])
    if (!match || !allowed.includes(match[1])) fail()
    const [, key, attached] = match
    const repeatable = REPEATABLE.has(key)
    if (!repeatable && Object.hasOwn(options, key)) fail()
    if (FLAGS.has(key)) {
      if (attached !== undefined) fail()
      options[key] = true
    } else {
      const value = attached ?? argv[++index]
      if (value === undefined || value === '' || value.startsWith('--')) fail()
      if (repeatable) {
        if (!Object.hasOwn(options, key)) options[key] = []
        options[key].push(value)
      } else options[key] = value
    }
  }
  for (const key of [...COMMON, 'file', 'skill-root']) if (options[key] !== undefined) options[key] = absolute(options[key])
  const args = action === undefined ? {} : { action }
  if (command === 'setup') {
    if (action === 'import') { if (!options.file || !/\.(?:csv|xlsx)$/iu.test(options.file)) fail(); args.input_path = options.file }
    if (action === 'activate') {
      if (!/^import-[a-f0-9]{32}-[a-f0-9]{64}$/u.test(options['import-id'] ?? '')) fail()
      args.import_id = options['import-id']
      const rows = options.rows === undefined ? [] : options.rows.split(',').map(value => integer(value, 1, MAX_TARGETS))
      if (rows.length > MAX_TARGETS || new Set(rows).size !== rows.length) fail()
      const targets = options.target === undefined ? [] : normalizeTargets(options.target.map(targetFromArgument))
      if (rows.length === 0 && targets.length === 0) fail()
      args.rows = rows
      if (targets.length) args.targets = targets.map(wireTarget)
    }
    if (action === 'browser-open') { if (options['confirm-open'] !== true) fail(); args.confirm_open = true }
  }
  if (command === 'collect') {
    const targets = []
    if (options.target !== undefined) for (const value of options.target) targets.push(targetFromArgument(value))
    if (options.topic !== undefined) targets.push(normalizeTarget({ platform: 'weibo', mode: 'topic', topic: options.topic }))
    if (targets.length) args.targets = normalizeTargets(targets).map(wireTarget)
    if (options.platforms !== undefined) {
      const platforms = options.platforms.split(',').map(value => value.trim().toLowerCase())
      if (!platforms.length || new Set(platforms).size !== platforms.length || platforms.some(value => !PLATFORMS.includes(value))) fail()
      args.platforms = PLATFORMS.filter(value => platforms.includes(value)).join(',')
    }
    if (options['count-mode'] !== undefined) args.count_mode = parseCountMode(options['count-mode'], 'fixed')
    if (options.backend !== undefined) args.backend = resolveBackend(options.backend, undefined)
    if (options.count !== undefined) args.count = integer(options.count, 1, MAX_COUNT)
    if (options['run-deadline'] !== undefined) args.run_deadline_seconds = integer(options['run-deadline'], 1, MAX_RUN_DEADLINE_SECONDS)
    if (options['xhs-comments'] !== undefined) args.xhs_comments = integer(options['xhs-comments'], 0, 100)
    if (options['allow-navigation']) args.allow_navigation = true
    if (options['resume-run'] !== undefined) args.resume_run = runId(options['resume-run'])
    // best_effort keeps the runtime batch policy, so only fixed mode keeps this ceiling.
    const fixedCount = (args.count_mode ?? 'fixed') === 'fixed'
    const xhsSelected = (args.platforms?.split(',') ?? []).includes('xhs') || (args.targets ?? []).some(target => target.platform === 'xhs')
    if (fixedCount && xhsSelected && args.count > 10) fail()
    if (args.xhs_comments > 0 && args.platforms !== undefined && !args.platforms.split(',').includes('xhs')) fail()
  }
  if (command === 'runs') {
    if (action === 'export') {
      args.run_id = runId(options['run-id'])
      const selection = normalizeExportSelection({
        runId: args.run_id,
        recordKinds: options['record-kinds'] === undefined ? ['posts'] : commaList(options['record-kinds']),
        platforms: options.platforms === undefined ? [] : commaList(options.platforms),
        topics: options.topics === undefined ? [] : commaList(options.topics),
        targets: options.targets === undefined ? [] : options.targets.map(value => targetIdentity(targetFromArgument(value))),
        fields: options.fields === undefined ? [] : commaList(options.fields),
        fieldGroups: options['field-groups'] === undefined ? [] : commaList(options['field-groups']),
        format: options.format,
        fileName: options['file-name'],
        overwrite: options.overwrite === true,
      })
      args.format = selection.format
      if (options.format === 'xlsx' || EXPORT_SELECTION.some(key => options[key] !== undefined)) args.export = wireExport(selection)
    }
    if (action === 'compare') { args.before = runId(options.before); args.after = runId(options.after) }
  }
  if (command === 'install-skill') {
    if (Number(options.list === true) + Number(options.agent !== undefined) + Number(options['skill-root'] !== undefined) !== 1) fail()
    if (options.agent !== undefined && !['codex', 'claude', 'cursor', 'openclaw', 'hermes'].includes(options.agent)) fail()
  }
  return { command, action, options, args }
}

export { PLATFORMS }

const HELP = {
  status: 'ok', name: 'media-missher',
  usage: ['media-missher --help | --version', 'media-missher doctor | capabilities', 'media-missher install-skill --list | --agent codex|claude|cursor|openclaw|hermes | --skill-root /absolute/skills', 'media-missher setup status | template | import --file /absolute/creators.xlsx', 'media-missher setup activate --import-id ID [--rows 1,3,5] [--target PLATFORM:MODE:VALUE]...', 'media-missher setup browser-check | browser-open --confirm-open', `media-missher collect [--platforms ${PLATFORMS.join(',')}] [--count 10] [--count-mode ${COUNT_MODES.join('|')}] [--backend ${BACKENDS.join('|')}] [--run-deadline 900] [--target PLATFORM:MODE:VALUE]... [--topic NAME_OR_URL] [--xhs-comments 0] [--allow-navigation] [--resume-run run-ID]`, `media-missher runs list | export --run-id run-ID [--format ${EXPORT_FORMATS.join('|')}] [--record-kinds ${EXPORT_RECORD_KINDS.join(',')}] [--platforms LIST] [--topics LIST] [--targets PLATFORM:MODE:VALUE]... [--fields LIST] [--field-groups LIST] [--file-name NAME] [--overwrite] | compare --before run-ID --after run-ID | xhs-status | progress`],
  targets: `Platforms are ${PLATFORMS.join(', ')}. --target is repeatable and adds explicit targets beside --rows: PLATFORM:creator:UID|@handle|https://homepage, PLATFORM:search:KEYWORD or PLATFORM:search:latest|top:KEYWORD, and weibo:topic:NAME or weibo:topic:super:NAME (topic is Weibo-only). One plan may select several accounts on the same platform: the previous four-row limit is gone and up to ${MAX_TARGETS} rows or targets are accepted. A display name is only a label and is never resolved into an identity; selecting a creator target is not switching the logged-in account, and this tool never switches accounts automatically.`,
  counts: `--count is 1-${MAX_COUNT} per platform and defaults to 10. fixed keeps the requested per-target count. best_effort ignores --count as a total and keeps paging inside a bounded per-batch budget plus --run-deadline 1-${MAX_RUN_DEADLINE_SECONDS} seconds, then reports a stop reason and a resume point; a budget pause is not "collection finished". Exhausting a budget, no new results, a login or permission limit, a risk stop, a timeout and a cancellation are different stop reasons. Risk stops never resume automatically. XHS keeps 10 notes, 3 pages and 600 seconds between batch starts: --count above 10 is rejected for xhs in fixed mode only, because best_effort leaves the 10-note ceiling to the runtime batch policy.`,
  backends: `--backend ${BACKENDS.join('|')} is chosen once per run and frozen in the run manifest, progress, resume identity and export summary; there is no auto value and no silent fallback after a failure. Chrome CDP is the only backend and works independently of the Agent host. Retired Computer Use requests return backend-retired-computer-use. BrowserSkill is retired with backend-retired-browserskill; historical results remain readable. Omitting --backend uses the saved profile preference and then cdp.`,
  exportHelp: `runs export --format ${EXPORT_FORMATS.join('|')} (default xlsx) only reads already-saved private results and never collects, navigates, opens a browser or fills a missing field; an already-saved run can be re-filtered and re-exported as often as needed. --record-kinds ${EXPORT_RECORD_KINDS.join('|')} defaults to posts, --platforms, --topics, --fields and --field-groups take comma-separated lists, and --targets is repeated once per target. --file-name must be a plain file name without a directory part, and an existing file is never replaced unless --overwrite is given. A requested field that was never collected is reported as missing. The validated selection is passed to the shared library as one args.export object with run_id, record_kinds, platforms, topics, targets, fields, field_groups, format, file_name and overwrite.`,
  pathOptions: 'doctor, setup, collect and runs accept --profile, --runtime-home and --output-root with absolute paths. Explicit flags override MEDIA_MISSHER_PROFILE_CONFIG and MEDIA_MISSHER_HOME. DSH_HOME is not used.',
  defaults: { profile: '~/.config/media-missher/profile.json', runtimeHome: '~/.local/share/media-missher', outputRoot: '~/.local/share/media-missher-agent/runs' },
  behavior: 'JSON stdout. doctor is read-only and offline. setup template/import/activate do not install Python, probe CDP or collect. Browser opening and collection require their own user authorization. Login is manual and navigation defaults to false. Collection is sequential under one browser owner. XHS: 10 notes, 3 pages, 600 seconds between starts; persistent risk stops, no automatic retry or reset. Export happens after collection and never collects.',
  runtimeRequired: RUNTIME_REQUIRED,
  exitCodes: { success: 0, failureOrPartial: 1, invalidArguments: 2, needsSetupOrPreflight: 3, riskStopped: 4, SIGINT: 130, SIGTERM: 143 },
}

async function packageMetadata() {
  const value = JSON.parse((await boundedFile(join(PACKAGE_ROOT, 'package.json'), 64 * 1024, false)).toString('utf8'))
  if (value.name !== '@missher/media-missher' || typeof value.version !== 'string' || !/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/u.test(value.version)) throw new CliError('package_invalid')
  return { name: value.name, version: value.version }
}

async function noLinks(path) {
  for (let current = path; ; current = dirname(current)) {
    try {
      const stat = await lstat(current)
      if (stat.isSymbolicLink() || (current !== path && !stat.isDirectory())) throw new Error('path_invalid')
    } catch (error) { if (error.code !== 'ENOENT') throw error }
    if (current === dirname(current)) break
  }
}

async function boundedFile(path, maximum, checkAncestors = true) {
  if (checkAncestors) await noLinks(path)
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
  try {
    const before = await file.stat()
    if (!before.isFile() || before.nlink !== 1 || before.size > maximum || (before.mode & 0o022) !== 0) throw new Error('file_invalid')
    const bytes = Buffer.alloc(maximum + 1)
    let length = 0
    while (length < bytes.length) {
      const { bytesRead } = await file.read(bytes, length, bytes.length - length, null)
      if (bytesRead === 0) break
      length += bytesRead
    }
    const after = await file.stat()
    const current = await lstat(path)
    if (length > maximum || before.dev !== current.dev || before.ino !== current.ino || current.isSymbolicLink() || before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) throw new Error('file_changed')
    return bytes.subarray(0, length)
  } finally { await file.close() }
}

async function inspectRuntime(runtimeHome) {
  const result = { requiredVersion: RUNTIME_REQUIRED, currentVersion: null, status: 'missing', pythonStatus: 'not-checked' }
  try {
    const bytes = await boundedFile(join(runtimeHome, 'current/VERSION'), 32)
    const text = bytes.toString('utf8')
    if (!/^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\n?$/u.test(text)) throw new Error('version_invalid')
    result.currentVersion = text.trim()
    result.status = result.currentVersion === RUNTIME_REQUIRED ? 'version-matched' : 'version-mismatch'
  } catch (error) { result.status = error.code === 'ENOENT' ? 'missing' : 'invalid'; return result }
  try {
    const python = join(runtimeHome, 'venv/bin/python')
    await noLinks(dirname(python))
    if (!(await lstat(await realpath(python))).isFile()) throw new Error('python_invalid')
    await access(python, constants.X_OK)
    result.pythonStatus = 'executable-present-not-executed'
  } catch { result.pythonStatus = 'missing-or-invalid' }
  return result
}

async function doctor(core, config, metadata, signal) {
  const selected = await core.createSetupTool(config).execute({ action: 'status' }, { signal })
  signal.throwIfAborted()
  const runtime = await inspectRuntime(config.runtimeHome)
  const ready = selected.status === 'ok' && runtime.status === 'version-matched' && runtime.pythonStatus === 'executable-present-not-executed'
  const nextSteps = selected.status === 'needs-setup' ? [...NEXT_SETUP] : []
  if (selected.status === 'failed') nextSteps.push('Inspect the selected local profile and its private permissions; setup status preserves an invalid existing profile.')
  if (runtime.status !== 'version-matched' || runtime.pythonStatus !== 'executable-present-not-executed') nextSteps.push(`Runtime ${RUNTIME_REQUIRED} is required separately from Agent package ${metadata.version}. Once targets, manual login and this collection are authorized, collect can provision the embedded runtime using Python 3.11/3.12. doctor installs nothing.`)
  nextSteps.push('Browser connectivity and login were not checked. Use setup browser-check only when needed; opening requires setup browser-open --confirm-open and explicit user intent. A connected browser does not establish login.')
  return { status: selected.status === 'failed' || runtime.status === 'invalid' ? 'failed' : ready ? 'ok' : 'needs-setup', cli: { ...metadata, nodeVersion: process.versions.node }, runtime,
    selected: { status: selected.status, configuredPlatforms: selected.configuredPlatforms ?? '', activePlatforms: selected.activePlatforms ?? '' },
    browser: { status: 'not-checked', loginStatus: 'not-checked' }, paths: { profile: config.profilePath, runtimeHome: config.runtimeHome, outputRoot: config.outputRoot }, nextSteps }
}

/** Keep signal handling installed until the shared process runner has awaited cleanup. */
export async function withCliSignals(operation) {
  const controller = new AbortController()
  let exitCode = 0
  const interrupt = () => { exitCode ||= 130; controller.abort() }
  const terminate = () => { exitCode ||= 143; controller.abort() }
  process.on('SIGINT', interrupt)
  process.on('SIGTERM', terminate)
  try { return { value: await operation(controller.signal), exitCode } }
  catch (error) { return { error, exitCode } }
  finally { process.off('SIGINT', interrupt); process.off('SIGTERM', terminate) }
}

/** Only fixed target codes cross the boundary; a caller-supplied value never does. */
const TARGET_CODES = new Set(TARGET_ERROR_CODES)

function safeError(error) {
  if (error instanceof CliError) return { status: 'failed', error: error.code, nextSteps: ['Run media-missher --help for the command and supported options.'] }
  if (error instanceof TargetError) return { status: 'failed', error: TARGET_CODES.has(error.code) ? error.code : 'target_invalid', nextSteps: ['Run media-missher --help for the supported target, backend, count-mode and export options. The rejected value is not echoed.'] }
  if (error instanceof StorageError) {
    const allowed = ['platform_linux_user_required', 'platform_wsl_home_required', 'platform_wsl_storage_unverified', 'platform_wsl_native_storage_required']
    return { status: 'failed', error: allowed.includes(error.message) ? error.message : 'platform_storage_invalid', nextSteps: ['Use a non-root Linux user. In WSL2, keep the profile, runtime, output and skill destination inside the same Linux HOME beneath /home/<user> on native Linux storage; Windows mounts and aliases are unsupported.'] }
  }
  if (error instanceof SkillInstallError) return { status: 'failed', error: error.code, ...(error.path ? { path: error.path } : {}), nextSteps: ['Preserve the existing path. Inspect its ownership or select a different absolute --skill-root; existing or edited skills are not overwritten.'] }
  return { status: 'failed', error: 'operation_failed', nextSteps: ['Run media-missher doctor to inspect local readiness. No raw exception or private diagnostic text is returned.'] }
}

function resultExit(value) {
  if (['ok', 'success'].includes(value.status)) return 0
  if (['needs-input', 'needs-setup', 'preflight-failed'].includes(value.status)) return 3
  if (value.status === 'risk-stopped') return 4
  return 1
}

function setupNextSteps(parsed, value) {
  if (parsed.command === 'setup' && value.activePlatforms && ['browser-check', 'browser-open'].includes(parsed.action)) {
    const guidance = {
      'missing-chrome': 'The selected creators are retained. Install supported Chrome in this operating-system environment before the requested browser preparation; login remains manual.',
      'not-running': 'The selected creators are retained. When the user requests opening the AI browser, run media-missher setup browser-open --confirm-open and let the user log in manually.',
      starting: 'The AI browser is starting; the selected creators are retained. Let the user inspect the window and log in manually. Use setup browser-check when appropriate; do not launch another instance automatically.',
      busy: 'The selected creators are retained. Inspect the existing browser window or profile before proceeding; do not terminate it or switch browsers automatically.',
    }
    return [guidance[value.browserStatus] ?? 'The selected creators are retained. Inspect the returned browser status and keep login manual; do not automatically collect.']
  }
  return [...NEXT_SETUP]
}

export async function runCli(argv, { env = process.env, platform = process.platform, release = systemRelease(), uid = process.getuid?.(), mountinfo } = {}) {
  let parsed
  try { parsed = parseCli(argv) } catch (error) { return { value: safeError(error), exitCode: 2 } }
  const execution = await withCliSignals(async signal => {
    if (parsed.command === 'help') return HELP
    const metadata = await packageMetadata()
    if (parsed.command === 'version') return { status: 'ok', ...metadata, runtimeRequired: RUNTIME_REQUIRED }
    if (platform === 'win32') throw new CliError('native_windows_unsupported')
    if (!['darwin', 'linux'].includes(platform)) throw new CliError('platform_unsupported')
    const home = absolute(env.HOME || homedir())
    const storageContext = { platform, kernel: release, uid, distribution: env.WSL_DISTRO_NAME, ...(mountinfo === undefined ? {} : { mountinfo }) }
    await checkStorage(home, [], storageContext)
    const wsl = wslEnvironment(storageContext)
    if (wsl) { try { await noLinks(home) } catch { throw new StorageError('platform_wsl_home_required') } }
    if (parsed.command === 'capabilities') return capabilities(metadata.version)
    if (parsed.command === 'install-skill') {
      if (parsed.options.list) return { status: 'ok', agents: listAgents(home, env), generic: 'install-skill --skill-root /absolute/skills', activation: 'Installation does not prove skill activation in the current Agent conversation.' }
      const skillRoot = parsed.options['skill-root'] ?? listAgents(home, env).find(agent => agent.name === parsed.options.agent).skillRoot
      const skillPaths = [join(skillRoot, '.media-missher-install.lock'), join(skillRoot, 'media-missher'), join(home, '.local/share/media-missher-agent/skill-backups')]
      await checkStorage(home, skillPaths, storageContext)
      if (wsl) for (const path of skillPaths) { try { await noLinks(path) } catch { throw new StorageError('platform_wsl_home_required') } }
      return installSkill({ agent: parsed.options.agent, skillRoot, home, env, packageRoot: PACKAGE_ROOT, version: metadata.version, cliPath: await realpath(fileURLToPath(import.meta.url)), nodePath: await realpath(process.execPath), signal })
    }
    const paths = { profilePath: absolute(parsed.options.profile ?? env.MEDIA_MISSHER_PROFILE_CONFIG ?? join(home, '.config/media-missher/profile.json')),
      runtimeHome: absolute(parsed.options['runtime-home'] ?? env.MEDIA_MISSHER_HOME ?? join(home, '.local/share/media-missher')),
      outputRoot: absolute(parsed.options['output-root'] ?? join(home, '.local/share/media-missher-agent/runs')) }
    const browserRoot = join(dirname(paths.profilePath), 'browser')
    const storagePaths = [paths.profilePath, join(dirname(paths.profilePath), 'setup'), browserRoot, join(browserRoot, 'chrome-profile'),
      paths.runtimeHome, join(paths.runtimeHome, 'current'), join(paths.runtimeHome, 'venv'), join(paths.runtimeHome, 'state'), paths.outputRoot, join(home, '.local/share/media-missher-shared')]
    await checkStorage(home, storagePaths, storageContext)
    if (wsl) for (const path of storagePaths) { try { await noLinks(path) } catch { throw new StorageError('platform_wsl_home_required') } }
    const core = await import('../lib/index.js')
    const config = core.normalizePluginConfig(paths, join(home, '.local/share/media-missher-agent'), home)
    signal.throwIfAborted()
    if (parsed.command === 'doctor') return doctor(core, config, metadata, signal)
    const factory = parsed.command === 'setup' ? core.createSetupTool : parsed.command === 'collect' ? core.createMediaTool : core.createRunsTool
    let progressOpen = true
    const onProgress = event => { if (progressOpen && !signal.aborted) process.stderr.write(`media-missher-progress ${JSON.stringify(event)}\n`) }
    let value
    try { value = await factory(config, parsed.command === 'collect' ? { onProgress } : undefined).execute(parsed.args, { signal }) }
    finally { progressOpen = false }
    if (!value || typeof value !== 'object' || Array.isArray(value) || !['ok', 'success', 'needs-input', 'needs-setup', 'preflight-failed', 'risk-stopped', 'partial', 'failed'].includes(value.status)) throw new Error('result_invalid')
    if (value.status === 'needs-input') return { ...value, nextSteps: ['Provide only the missing platform and exact targets; reuse information already supplied. No browser operation was started.'] }
    if (value.status === 'failed' && parsed.command === 'setup' && ['browser-open', 'browser-check'].includes(parsed.action) && Object.hasOwn(BROWSER_FAILURE_GUIDANCE, value.summary ?? '')) {
      return { ...value, nextSteps: [BROWSER_FAILURE_GUIDANCE[value.summary]] }
    }
    if (value.status === 'needs-setup' || (value.status === 'preflight-failed' && /^profile_/u.test(value.summary ?? ''))) return { ...value, nextSteps: setupNextSteps(parsed, value) }
    if (value.status === 'preflight-failed') return { ...value, nextSteps: ['Run media-missher doctor and inspect this run summary; do not automatically retry collection or reset risk state.'] }
    return value
  })
  if (execution.exitCode) return { value: { status: 'failed', error: 'operation_cancelled' }, exitCode: execution.exitCode }
  if (execution.error) {
    const value = safeError(execution.error)
    if (value.error === 'native_windows_unsupported') value.nextSteps = ['Use the delivered install.ps1 PowerShell entry with an existing WSL2 Linux distribution and WSLg. Run the CLI, browser and Agent shell inside the same WSL HOME; native Windows collection is unsupported.']
    return { value, exitCode: execution.error instanceof CliError && execution.error.code === 'cli_arguments_invalid' ? 2 : 1 }
  }
  return { value: execution.value, exitCode: resultExit(execution.value) }
}

const invokedPath = process.argv[1] ? await realpath(resolve(process.argv[1])).catch(() => undefined) : undefined
if (invokedPath && pathToFileURL(invokedPath).href === import.meta.url) {
  const result = await runCli(process.argv.slice(2))
  process.stdout.write(`${JSON.stringify(result.value, null, 2)}\n`)
  process.exitCode = result.exitCode
}
