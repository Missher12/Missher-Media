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

export const EMBEDDED_VERSION = '15.2.1'

export interface RuntimeLayout {
  python: string
  payloadRoot: string
}

export interface RuntimeDependencies {
  payloadRoot?: string
  platform?: NodeJS.Platform
  installPython?: string
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
}

export interface RunEvidence {
  runDirectory: string
  manifestPath: string
  runStatus: string
  records: Record<Platform, Record<string, unknown>[]>
  platformStatuses: Record<Platform, string>
  diagnostics: Record<Platform, { kind: string; code: string }>
  totalCollected: number
}

function payloadRootFromModule(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), '..', 'payload')
}

async function regularFile(path: string, code: string): Promise<void> {
  const metadata = await lstat(path)
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error(code)
}

async function privateProfile(path: string): Promise<void> {
  await regularFile(path, 'profile_invalid')
  const metadata = await lstat(path)
  if (process.platform !== 'win32' && (metadata.mode & 0o777) !== 0o600) {
    throw new Error('profile_permissions_invalid')
  }
}

async function prepareOutputRoot(path: string): Promise<void> {
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
    await regularFile(python, 'runtime_python_invalid')
    await access(python, constants.X_OK)
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
  if ((dependencies.platform ?? process.platform) !== 'darwin') throw new Error('platform_unsupported')
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
  return {
    status: record.status as ControllerSummary['status'],
    runDirectory: record.run_dir as string | null,
    evidence: [...record.evidence] as string[],
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

/** Load only fresh, manifest-declared platform JSON from the controller run. */
export async function loadRunEvidence(
  summary: ControllerSummary,
  config: PluginConfig,
): Promise<RunEvidence> {
  if (summary.runDirectory === null) throw new Error('run_directory_missing')
  const outputRoot = await realpath(config.outputRoot)
  const runDirectory = await safePath(summary.runDirectory, outputRoot, 'directory')
  const safeEvidence: string[] = []
  for (const path of summary.evidence) safeEvidence.push(await safePath(path, runDirectory, 'file'))
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
  if (typeof manifest.status !== 'string') throw new Error('manifest_invalid')
  const countsValue = object(manifest.counts, 'manifest_invalid')
  const paths = stringMap(manifest.paths, 'manifest_invalid')
  const platformStatusesValue = stringMap(manifest.platforms, 'manifest_invalid')
  const diagnosticsValue = object(manifest.diagnostics, 'manifest_invalid')
  const engineDirectory = dirname(manifestPath)
  const evidenceSet = new Set(safeEvidence)
  const records: RunEvidence['records'] = {
    bilibili: [],
    xhs: [],
    douyin: [],
    weibo: [],
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
  }

  return {
    runDirectory,
    manifestPath,
    runStatus: manifest.status,
    records,
    platformStatuses,
    diagnostics,
    totalCollected: PLATFORMS.reduce((total, platform) => total + records[platform].length, 0),
  }
}
