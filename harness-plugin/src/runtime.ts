import { constants } from 'node:fs'
import {
  access,
  chmod,
  lstat,
  mkdir,
  readFile,
  realpath,
} from 'node:fs/promises'
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { CollectArgs, Platform, PluginConfig } from './config.js'
import { PLATFORMS } from './config.js'
import { runProcess, type ProcessOptions, type ProcessResult } from './process.js'
import { readProfileSnapshot } from './private-config.js'
import { parsePhaseTimings } from './progress.js'
import type { ProgressEvent } from './process.js'

export const EMBEDDED_VERSION = '17.0.2'

export interface RuntimeLayout {
  python: string
  payloadRoot: string
}

export interface RuntimeDependencies {
  payloadRoot?: string
  platform?: NodeJS.Platform
  installPython?: string
  signal?: AbortSignal
  processRunner?: (
    executable: string,
    args: readonly string[],
    options?: ProcessOptions,
  ) => Promise<ProcessResult>
}

export interface ControllerInvocation {
  executable: string
  args: string[]
  env: NodeJS.ProcessEnv
  cwd: string
  timeoutMs: number
}

export interface ControllerSummary {
  status: 'success' | 'partial' | 'failed' | 'preflight-failed' | 'risk-stopped'
  runDirectory: string | null
  evidence: string[]
  manifestPath: string | null
  phaseTimings?: ProgressEvent[]
  phaseTimingsPersisted?: boolean
  preflightCode?: string
  runtimeVersion?: { current: string | null; required: string }
  preconditions?: Partial<Record<Platform, string>>
  continuation?: { priorCounts: Partial<Record<Platform, number>>; requestedCounts: Partial<Record<Platform, number>> }
}

export interface RunEvidence {
  runDirectory: string
  manifestPath: string
  runStatus: string
  records: Record<Platform, Record<string, unknown>[]>
  platformStatuses: Record<Platform, string>
  diagnostics: Record<Platform, { kind: string; code: string }>
  totalCollected: number
  /** Backend frozen for this run; absent for results written before backends existed. */
  backend?: string
  /** Real per-kind row counts, including topic relations and user profiles. */
  recordKinds: Record<string, number>
}

/** Read the controller's optional v2 manifest extension without trusting it blindly. */
function readRunIdentity(manifest: Record<string, unknown>): { backend?: string; recordKinds: Record<string, number> } {
  const recordKinds: Record<string, number> = {}
  const raw = manifest.record_kinds
  if (raw !== undefined) {
    const source = object(raw, 'manifest_record_kinds_invalid')
    for (const [kind, value] of Object.entries(source)) {
      if (!RECORD_KINDS.includes(kind as RecordKind)) throw new Error('manifest_record_kinds_invalid')
      if (!Number.isInteger(value) || (value as number) < 0) throw new Error('manifest_record_kinds_invalid')
      recordKinds[kind] = value as number
    }
  }
  let backend: string | undefined
  if (manifest.backend !== undefined) {
    if (typeof manifest.backend !== 'string' || !(manifest.schema_version === 3 ? ['cdp', 'computer_use'] : ['cdp', 'browserskill']).includes(manifest.backend as string)) throw new Error('manifest_backend_invalid')
    backend = manifest.backend
  }
  return { ...(backend === undefined ? {} : { backend }), recordKinds }
}

function payloadRootFromModule(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), '..', 'payload')
}

async function regularFile(path: string, code: string): Promise<void> {
  const metadata = await lstat(path)
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error(code)
}

async function executableFile(path: string, code: string): Promise<void> {
  const metadata = await lstat(path)
  if (!metadata.isFile() && !metadata.isSymbolicLink()) throw new Error(code)
  const target = await realpath(path)
  const targetMetadata = await lstat(target)
  if (!targetMetadata.isFile()) throw new Error(code)
  await access(path, constants.X_OK)
}

async function privateProfile(path: string): Promise<void> {
  await regularFile(path, 'profile_invalid')
  const metadata = await lstat(path)
  if (process.platform !== 'win32' && (metadata.mode & 0o777) !== 0o600) {
    throw new Error('profile_permissions_invalid')
  }
  const profile = await readProfileSnapshot(path)
  if (profile === undefined || profile.available.length === 0) throw new Error('profile_targets_missing')
}

export async function prepareOutputRoot(path: string): Promise<void> {
  let existed = true
  try {
    const metadata = await lstat(path)
    if (metadata.isSymbolicLink() || !metadata.isDirectory()) throw new Error('output_root_invalid')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
    existed = false
    await mkdir(path, { recursive: true, mode: 0o700 })
  }
  if (process.platform !== 'win32' && !existed) await chmod(path, 0o700)
}

async function exactRuntimePython(runtimeHome: string): Promise<string | undefined> {
  const versionPath = resolve(runtimeHome, 'current', 'VERSION')
  const python = resolve(runtimeHome, 'venv', 'bin', 'python')
  try {
    await regularFile(versionPath, 'runtime_version_invalid')
    await executableFile(python, 'runtime_python_invalid')
    if (await readFile(versionPath, 'utf8') !== `${EMBEDDED_VERSION}\n`) return undefined
    return python
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined
    if ((error as Error).message === 'runtime_version_invalid') throw error
    if ((error as Error).message === 'runtime_python_invalid') throw error
    if ((error as NodeJS.ErrnoException).code === 'EACCES') return undefined
    throw error
  }
}

/** Reuse or atomically provision the exact embedded Media runtime. */
export async function ensureRuntime(
  config: PluginConfig,
  dependencies: RuntimeDependencies = {},
): Promise<RuntimeLayout> {
  if (!['darwin', 'linux'].includes(dependencies.platform ?? process.platform)) throw new Error('platform_unsupported')
  const payloadRoot = resolve(dependencies.payloadRoot ?? payloadRootFromModule())
  await regularFile(resolve(payloadRoot, 'VERSION'), 'payload_version_invalid')
  if (await readFile(resolve(payloadRoot, 'VERSION'), 'utf8') !== `${EMBEDDED_VERSION}\n`) {
    throw new Error('payload_version_invalid')
  }
  await regularFile(
    resolve(payloadRoot, 'tools', 'install_media_missher.py'),
    'payload_installer_invalid',
  )
  await regularFile(
    resolve(payloadRoot, 'media-missher', 'scripts', 'run_collection.py'),
    'payload_controller_invalid',
  )
  await privateProfile(config.profilePath)
  await prepareOutputRoot(config.outputRoot)

  const existingPython = await exactRuntimePython(config.runtimeHome)
  if (existingPython !== undefined) return { python: existingPython, payloadRoot }

  const processRunner = dependencies.processRunner ?? runProcess
  const result = await processRunner(
    dependencies.installPython ?? process.env.MEDIA_MISSHER_INSTALL_PYTHON ?? 'python3',
    [
      resolve(payloadRoot, 'tools', 'install_media_missher.py'),
      '--source', payloadRoot,
      '--home', config.runtimeHome,
      '--runtime-only',
    ],
    {
      ...(dependencies.signal === undefined ? {} : { signal: dependencies.signal }),
      timeoutMs: 15 * 60 * 1000,
      maxOutputBytes: 1024 * 1024,
      env: { PYTHONDONTWRITEBYTECODE: '1' },
    },
  )
  if (result.code !== 0) throw new Error('runtime_install_failed')
  const installedPython = await exactRuntimePython(config.runtimeHome)
  if (installedPython === undefined) throw new Error('runtime_install_incomplete')
  return { python: installedPython, payloadRoot }
}

/** Build the exact existing-controller command for one bounded request. */
export function buildControllerInvocation(
  config: PluginConfig,
  request: CollectArgs,
  runtime: RuntimeLayout,
  planPath?: string,
): ControllerInvocation {
  const args = [
    resolve(runtime.payloadRoot, 'media-missher', 'scripts', 'run_collection.py'),
    '--profile', config.profilePath,
    '--data-root', config.outputRoot,
    '--platform', request.platformText,
    '--count', String(request.count),
    '--xhs-comments', String(request.xhsComments),
    '--platform-timeout', String(config.platformTimeoutSeconds),
    '--execution-timeout', String(config.executionTimeoutSeconds),
  ]
  if (request.allowNavigation) args.push('--allow-navigation')
  if (request.resumeRun !== undefined) args.push('--resume-run', request.resumeRun)
  // The frozen backend and the versioned multi-target plan are passed only when
  // they carry information the legacy four-platform request cannot express, so a
  // plain per-platform request keeps its original exact command.
  if (request.backend !== 'cdp') args.push('--backend', request.backend)
  if (request.countMode === 'best_effort') {
    args.push('--count-mode', 'best_effort', '--run-deadline', String(request.runDeadlineSeconds))
  }
  if (planPath !== undefined) args.push('--targets-json', planPath)
  args.push('--no-feishu', '--json-summary')
  return {
    executable: runtime.python,
    args,
    env: {
      MEDIA_MISSHER_HOME: config.runtimeHome,
      PYTHONDONTWRITEBYTECODE: '1',
      PYTHONUNBUFFERED: '1',
    },
    cwd: resolve(runtime.payloadRoot, 'media-missher'),
    timeoutMs: Math.ceil((config.executionTimeoutSeconds + 30) * 1000),
  }
}

/** Parse the controller's single JSON summary without retaining private fields. */
export function parseControllerSummary(stdout: string): ControllerSummary {
  let value: unknown
  try {
    value = JSON.parse(stdout.trim())
  } catch {
    throw new Error('controller_summary_invalid')
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('controller_summary_invalid')
  }
  const record = value as Record<string, unknown>
  const statuses = new Set(['success', 'partial', 'failed', 'preflight-failed', 'risk-stopped'])
  if (typeof record.status !== 'string' || !statuses.has(record.status)) {
    throw new Error('controller_summary_invalid')
  }
  if (!(record.run_dir === null || typeof record.run_dir === 'string')) {
    throw new Error('controller_summary_invalid')
  }
  if (!Array.isArray(record.evidence) || record.evidence.length > 32 || record.evidence.some(item => typeof item !== 'string')) {
    throw new Error('controller_summary_invalid')
  }
  const manifestCandidates = (record.evidence as string[])
    .filter(path => path.endsWith('/manifest.json'))
  const validation = record.validation
  if (validation !== undefined) {
    if (validation === null || typeof validation !== 'object' || Array.isArray(validation)) {
      throw new Error('controller_summary_invalid')
    }
    const diagnostics = (validation as Record<string, unknown>).diagnostics
    if (diagnostics !== undefined) {
      if (!Array.isArray(diagnostics) || diagnostics.length > 32) {
        throw new Error('controller_summary_invalid')
      }
      for (const candidate of diagnostics) {
        if (candidate === null || typeof candidate !== 'object' || Array.isArray(candidate)) {
          throw new Error('controller_summary_invalid')
        }
        const path = (candidate as Record<string, unknown>).path
        if (typeof path === 'string' && path.endsWith('/manifest.json')) manifestCandidates.push(path)
      }
    }
  }
  const uniqueManifestCandidates = [...new Set(manifestCandidates)]
  if (uniqueManifestCandidates.length > 1) throw new Error('controller_summary_invalid')
  const preconditions: Partial<Record<Platform, string>> = {}
  if (record.diagnostics !== undefined) {
    const source = object(record.diagnostics, 'controller_diagnostics_invalid')
    for (const [platform, raw] of Object.entries(source)) {
      if (!PLATFORMS.includes(platform as Platform)) throw new Error('controller_diagnostics_invalid')
      const diagnostic = object(raw, 'controller_diagnostics_invalid')
      if (Object.keys(diagnostic).length !== 2 || diagnostic.kind !== 'precondition' || typeof diagnostic.code !== 'string' || !DIAGNOSTIC_CODES.precondition?.includes(diagnostic.code)) throw new Error('controller_diagnostics_invalid')
      preconditions[platform as Platform] = diagnostic.code
    }
  }
  let continuation: ControllerSummary['continuation']
  if (record.continuation !== undefined) {
    const value = object(record.continuation, 'controller_continuation_invalid')
    const prior = object(value.prior_counts, 'controller_continuation_invalid')
    const requested = object(value.requested_counts, 'controller_continuation_invalid')
    if (JSON.stringify(Object.keys(prior).sort()) !== JSON.stringify(Object.keys(requested).sort())) throw new Error('controller_continuation_invalid')
    for (const platform of Object.keys(requested)) {
      if (!PLATFORMS.includes(platform as Platform) || !Number.isSafeInteger(prior[platform]) || !Number.isSafeInteger(requested[platform]) || (prior[platform] as number) < 0 || (requested[platform] as number) < (prior[platform] as number)) throw new Error('controller_continuation_invalid')
    }
    continuation = { priorCounts: prior as Partial<Record<Platform, number>>, requestedCounts: requested as Partial<Record<Platform, number>> }
  }
  const phaseTimings = record.phase_timings === undefined ? undefined : parsePhaseTimings(record.phase_timings)
  const phaseTimingsPersisted = record.phase_timings_persisted
  if (phaseTimingsPersisted !== undefined && typeof phaseTimingsPersisted !== 'boolean') throw new Error('controller_progress_invalid')
  let preflightCode: string | undefined
  let runtimeVersion: ControllerSummary['runtimeVersion']
  if (record.preflight !== undefined) {
    const preflight = object(record.preflight, 'controller_preflight_invalid')
    if (preflight.code !== undefined) {
      if (!['runtime-version-mismatch', 'collection-busy', 'shared-state-invalid', 'platform-risk-latched', 'progress-module-invalid'].includes(preflight.code as string)) throw new Error('controller_preflight_invalid')
      preflightCode = preflight.code as string
    }
    if (preflight.runtime_version !== undefined) {
      const version = object(preflight.runtime_version, 'controller_preflight_invalid')
      const validVersion = (value: unknown): value is string => typeof value === 'string' && /^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})$/.test(value)
      if (!validVersion(version.required) || !(version.current === null || version.current === 'unavailable' || validVersion(version.current)) || typeof version.matches !== 'boolean') throw new Error('controller_preflight_invalid')
      runtimeVersion = { current: version.current === 'unavailable' ? null : version.current as string | null, required: version.required }
    }
  }
  return {
    status: record.status as ControllerSummary['status'],
    ...(phaseTimings === undefined ? {} : { phaseTimings }),
    ...(phaseTimingsPersisted === undefined ? {} : { phaseTimingsPersisted }),
    ...(preflightCode === undefined ? {} : { preflightCode }),
    ...(runtimeVersion === undefined ? {} : { runtimeVersion }),
    runDirectory: record.run_dir as string | null,
    evidence: [...record.evidence] as string[],
    manifestPath: uniqueManifestCandidates[0] ?? null,
    ...(Object.keys(preconditions).length ? { preconditions } : {}),
    ...(continuation === undefined ? {} : { continuation }),
  }
}

function childPath(path: string, parent: string): boolean {
  const relationship = relative(parent, path)
  return relationship !== '' && relationship !== '..' && !relationship.startsWith(`..${sep}`) && !isAbsolute(relationship)
}

async function safePath(path: string, parent: string, expected: 'file' | 'directory'): Promise<string> {
  const absolute = resolve(path)
  const metadata = await lstat(absolute)
  if (metadata.isSymbolicLink()) throw new Error('evidence_symlink_forbidden')
  if (expected === 'file' ? !metadata.isFile() : !metadata.isDirectory()) {
    throw new Error('evidence_type_invalid')
  }
  const resolved = await realpath(absolute)
  if (!childPath(resolved, parent)) throw new Error('evidence_path_escape')
  return resolved
}

function object(value: unknown, code: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(code)
  return value as Record<string, unknown>
}

function stringMap(value: unknown, code: string): Record<string, string> {
  const source = object(value, code)
  if (Object.values(source).some(item => typeof item !== 'string')) throw new Error(code)
  return source as Record<string, string>
}

// Fixed controller diagnostics only; free-form text must never reach the model.
const DIAGNOSTIC_CODES: Record<string, string[]> = {
  "ok": [
    "ok"
  ],
  "result": [
    "count-shortfall",
    "incomplete-record",
    "screenshot-shortfall",
    "required-fields-missing"
  ],
  "not-run": [
    "preflight-aborted",
    "prior-risk-stop"
  ],
  "dependency": [
    "module-not-found"
  ],
  "precondition": [
    "bsk-busy",
    "bsk-click",
    "bsk-incompatible",
    "bsk-missing",
    "bsk-session-start",
    "bsk-session-stop",
    "bsk-snapshot",
    "bsk-tab-borrow",
    "bsk-tab-list",
    "bsk-tab-return",
    "bsk-target-ambiguous",
    "bsk-timeout",
    "bsk-transport",
    "bsk-unhealthy",
    "precondition-failed",
    "collection-busy",
    "shared-state-invalid",
    "bsk-navigate",
    "bsk-observe",
    "bsk-get-html",
    "bsk-extract",
    "bsk-stale-reference",
    "bsk-risk-signal",
    "bsk-navigation-not-authorized",
    "browser-assist-replaced",
    "platform-collector-missing",
    "topic-collector-unavailable",
    "topic-unsupported-platform",
    "topic-container-unsupported",
    "topic-input-invalid",
    "topic-kind-mismatch",
    "target-identity-missing",
    "target-keyword-missing",
    "target-topic-missing",
    "plan-request-invalid",
    "plan-executor-missing",
    "plan-manifest-invalid",
    "exclude-file-plan-unsupported",
    "platform-cooldown",
    "platform-risk-latched",
    "xhs-cooldown",
    "xhs-risk-latched",
    "xhs-safety-busy",
    "xhs-safety-state-invalid"
  ],
  "source-response": [
    "source-response-failed"
  ],
  "risk-stop": [
    "challenge",
    "http-403",
    "http-429",
    "payload-461",
    "payload-471",
    "payload-999",
    "risk-signal"
  ],
  "timeout": [
    "creator-capture-timeout",
    "detail-capture-timeout",
    "platform-timeout"
  ],
  "collector-contract": [
    "invalid-records"
  ],
  "internal": [
    "unexpected"
  ]
}

const STATUS_KINDS: Record<string, string[]> = {
  "complete": [
    "ok"
  ],
  "shortfall": [
    "result"
  ],
  "incomplete": [
    "result"
  ],
  "failed": [
    "collector-contract",
    "dependency",
    "internal",
    "precondition",
    "source-response",
    "timeout"
  ],
  "risk-stopped": [
    "risk-stop"
  ],
  "not-run": [
    "not-run"
  ]
}

const NATIVE_ID_KEYS: Record<Platform, string[]> = {
  bilibili: ['dynamic_id', 'bvid'], xhs: ['note_id'], douyin: ['aweme_id'], weibo: ['mblog_id'],
  x: ['tweet_id'],
}

/** Record kinds the controller can emit; a run may not carry every kind. */
export const RECORD_KINDS = ['posts', 'topic_participants', 'user_profiles'] as const
export type RecordKind = typeof RECORD_KINDS[number]

/** Mirror the controller's first-seen native identity projection, never count duplicate rows. */
function uniqueRecords(records: Record<string, unknown>[], platform: Platform, versioned = false): Record<string, unknown>[] {
  const seen = new Set<string>()
  return records.filter(record => {
    const kind = versioned && ['user_profile', 'profile', 'topic_participant', 'topic_participant_relation'].includes(String(record.type)) ? String(record.type) : 'post'
    const keys = kind === 'post' ? NATIVE_ID_KEYS[platform] : ['uid', 'author_id']
    const key = keys.find(key => record[key] !== undefined && record[key] !== null && record[key] !== '')
    if (key === undefined || typeof record.link !== 'string' || !record.link.trim()) {
      throw new Error('record_identity_invalid')
    }
    const value = record[key]
    if (typeof value !== 'string' && (typeof value !== 'number' || !Number.isSafeInteger(value))) {
      throw new Error('record_identity_invalid')
    }
    if (record.platform !== undefined && record.platform !== platform) throw new Error('record_platform_invalid')
    const identity = `${kind}:${key}:${value}:${kind.startsWith("topic_participant") ? String(record.topic ?? record.target_identity ?? "") + ":" + String(record.post_id ?? "") : ""}`
    if (seen.has(identity)) return false
    seen.add(identity)
    return true
  })
}

/** Load only fresh, manifest-declared platform JSON from the controller run. */
export async function loadRunEvidence(
  summary: ControllerSummary,
  config: PluginConfig,
  options: { startedAtMs?: number } = {},
): Promise<RunEvidence> {
  if (summary.runDirectory === null) throw new Error('run_directory_missing')
  const outputRoot = await realpath(config.outputRoot)
  const runDirectory = await safePath(summary.runDirectory, outputRoot, 'directory')
  if (options.startedAtMs !== undefined && ((await lstat(runDirectory)).mode & 0o777) !== 0o700) {
    throw new Error('run_permissions_invalid')
  }
  const safeEvidence: string[] = []
  const declaredEvidence = summary.manifestPath === null
    ? summary.evidence
    : [...summary.evidence, summary.manifestPath]
  for (const path of new Set(declaredEvidence)) {
    const safe = await safePath(path, runDirectory, 'file')
    if (options.startedAtMs !== undefined) {
      const metadata = await lstat(safe)
      if (metadata.mtimeMs < options.startedAtMs) throw new Error('evidence_stale')
      if ((metadata.mode & 0o777) !== 0o600) throw new Error('evidence_permissions_invalid')
    }
    safeEvidence.push(safe)
  }
  const manifestCandidates = safeEvidence.filter(path => path.endsWith(`${sep}manifest.json`))
  if (manifestCandidates.length !== 1) throw new Error('manifest_missing')
  const manifestPath = manifestCandidates[0] as string
  let manifestValue: unknown
  try {
    manifestValue = JSON.parse(await readFile(manifestPath, 'utf8'))
  } catch {
    throw new Error('manifest_invalid')
  }
  const manifest = object(manifestValue, 'manifest_invalid')
  if (typeof manifest.status !== 'string' || !([2, 3].includes(manifest.schema_version as number) ? ['complete', 'partial', 'failed', 'risk-stopped'] : ['complete', 'failed', 'risk-stopped']).includes(manifest.status)) throw new Error('manifest_invalid')
  const countsValue = object(manifest.counts, 'manifest_invalid')
  const paths = stringMap(manifest.paths, 'manifest_invalid')
  const platformStatusesValue = stringMap(manifest.platforms, 'manifest_invalid')
  const diagnosticsValue = object(manifest.diagnostics, 'manifest_invalid')
  const selected = Object.keys(platformStatusesValue).sort()
  if (selected.length === 0 || selected.some(platform => !PLATFORMS.includes(platform as Platform))
    || JSON.stringify(Object.keys(countsValue).sort()) !== JSON.stringify(selected)
    || JSON.stringify(Object.keys(diagnosticsValue).sort()) !== JSON.stringify(selected)) {
    throw new Error('manifest_platforms_invalid')
  }
  const engineDirectory = dirname(manifestPath)
  const evidenceSet = new Set(safeEvidence)
  const records: RunEvidence['records'] = {
    bilibili: [],
    xhs: [],
    douyin: [],
    weibo: [],
    x: [],
  }
  const platformStatuses = Object.fromEntries(
    PLATFORMS.map(platform => [platform, platformStatusesValue[platform] ?? 'not-selected']),
  ) as RunEvidence['platformStatuses']
  const diagnostics = Object.fromEntries(PLATFORMS.map((platform) => {
    const candidate = diagnosticsValue[platform]
    if (candidate === undefined) return [platform, { kind: 'not-selected', code: 'not-selected' }]
    const diagnostic = object(candidate, 'manifest_diagnostic_invalid')
    if (typeof diagnostic.kind !== 'string' || typeof diagnostic.code !== 'string') {
      throw new Error('manifest_diagnostic_invalid')
    }
    if (!Object.hasOwn(DIAGNOSTIC_CODES, diagnostic.kind)
      || !DIAGNOSTIC_CODES[diagnostic.kind]?.includes(diagnostic.code)
      || !Object.hasOwn(STATUS_KINDS, platformStatuses[platform])
      || !STATUS_KINDS[platformStatuses[platform]]?.includes(diagnostic.kind)) {
      throw new Error('manifest_diagnostic_invalid')
    }
    if ((platformStatuses[platform] === 'shortfall' && diagnostic.code !== 'count-shortfall')
      || (platformStatuses[platform] === 'incomplete' && !['incomplete-record', 'screenshot-shortfall', 'required-fields-missing'].includes(diagnostic.code))) {
      throw new Error('manifest_diagnostic_invalid')
    }
    return [platform, { kind: diagnostic.kind, code: diagnostic.code }]
  })) as RunEvidence['diagnostics']

  for (const platform of PLATFORMS) {
    const rawName = paths[platform]
    const expectedCount = countsValue[platform]
    if (!Number.isInteger(expectedCount) || (expectedCount as number) < 0) {
      if (rawName === undefined && expectedCount === undefined) continue
      throw new Error('manifest_count_invalid')
    }
    if (rawName === undefined) {
      if (expectedCount !== 0) throw new Error('manifest_count_mismatch')
      continue
    }
    if (rawName !== `${platform}.json`) throw new Error('manifest_path_invalid')
    const path = await safePath(resolve(engineDirectory, rawName), engineDirectory, 'file')
    if (!evidenceSet.has(path)) throw new Error('manifest_evidence_missing')
    let payload: unknown
    try {
      payload = JSON.parse(await readFile(path, 'utf8'))
    } catch {
      throw new Error('platform_json_invalid')
    }
    if (!Array.isArray(payload) || payload.some(item => item === null || typeof item !== 'object' || Array.isArray(item))) {
      throw new Error('platform_json_invalid')
    }
    records[platform] = payload as Record<string, unknown>[]
    if (records[platform].length !== expectedCount) throw new Error('manifest_count_mismatch')
    records[platform] = uniqueRecords(records[platform], platform, [2, 3].includes(manifest.schema_version as number))
  }

  const identity = readRunIdentity(manifest)
  return {
    runDirectory,
    manifestPath,
    runStatus: manifest.status,
    records,
    platformStatuses,
    diagnostics,
    totalCollected: PLATFORMS.reduce((total, platform) => total + records[platform].length, 0),
    ...identity,
  }
}
