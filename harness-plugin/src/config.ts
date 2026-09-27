import { homedir } from 'node:os'
import { isAbsolute, join, parse, resolve } from 'node:path'

export const PLATFORMS = ['bilibili', 'xhs', 'douyin', 'weibo', 'x'] as const
export type Platform = typeof PLATFORMS[number]

/** Chrome CDP is the only active backend; retired requests are never remapped. */
export const BACKENDS = ['cdp'] as const
export type Backend = typeof BACKENDS[number]
export const DEFAULT_BACKEND: Backend = 'cdp'

export const COUNT_MODES = ['fixed', 'best_effort'] as const
export type CountMode = typeof COUNT_MODES[number]

export const TASK_MODES = ['creator', 'search', 'topic'] as const
export type TaskMode = typeof TASK_MODES[number]

export const EXPORT_RECORD_KINDS = ['posts', 'topic_participants', 'user_profiles'] as const
export type ExportRecordKind = typeof EXPORT_RECORD_KINDS[number]

export const EXPORT_FORMATS = ['xlsx', 'csv', 'json', 'jsonl', 'sqlite'] as const
export type ExportFormat = typeof EXPORT_FORMATS[number]

export interface PluginConfigInput {
  defaultPlatforms?: string
  defaultCount?: number
  defaultXhsComments?: number
  defaultAllowNavigation?: boolean
  defaultBackend?: string
  defaultCountMode?: string
  defaultRunDeadlineSeconds?: number
  platformTimeoutSeconds?: number
  executionTimeoutSeconds?: number
  maxCount?: number
  profilePath?: string
  runtimeHome?: string
  outputRoot?: string
}

export interface PluginConfig {
  defaultPlatforms: Platform[]
  defaultCount: number
  defaultXhsComments: number
  defaultAllowNavigation: boolean
  defaultBackend: Backend
  defaultCountMode: CountMode
  defaultRunDeadlineSeconds: number
  platformTimeoutSeconds: number
  executionTimeoutSeconds: number
  maxCount: number
  profilePath: string
  runtimeHome: string
  outputRoot: string
}

/** One explicit collection target as described by the user. */
export interface CollectTarget {
  platform: Platform
  mode: TaskMode
  label?: string
  uid?: string
  handle?: string
  homepage?: string
  keyword?: string
  topic?: string
  topicKind?: 'topic' | 'super'
  sort?: 'latest' | 'top'
}

export interface CollectArgsInput {
  platforms?: string
  count?: number
  count_mode?: string
  backend?: string
  xhs_comments?: number
  allow_navigation?: boolean
  resume_run?: string
  run_deadline_seconds?: number
  targets?: CollectTarget[]
}

export interface CollectArgs {
  platforms: Platform[]
  platformText: string
  count: number
  countMode: CountMode
  backend: Backend
  targets: CollectTarget[]
  xhsComments: number
  allowNavigation: boolean
  runDeadlineSeconds: number
  resumeRun?: string
}

export interface ExportSelectionInput {
  run_id?: string
  record_kinds?: string[]
  platforms?: string[]
  topics?: string[]
  targets?: string[]
  fields?: string[]
  field_groups?: string[]
  format?: string
  file_name?: string
  overwrite?: boolean
}

export interface ExportSelection {
  runId: string
  recordKinds: ExportRecordKind[]
  platforms: Platform[]
  topics: string[]
  targets: string[]
  fields: string[]
  fieldGroups: string[]
  format: ExportFormat
  fileName?: string
  overwrite: boolean
}

function fail(code: string): never {
  throw new Error(code)
}

function finiteInteger(value: number, minimum: number, maximum: number, code: string): number {
  if (!Number.isInteger(value) || value < minimum || value > maximum) fail(code)
  return value
}

function positiveFinite(value: number, code: string): number {
  if (!Number.isFinite(value) || value <= 0) fail(code)
  return value
}

function safeAbsolutePath(value: string, code: string): string {
  if (typeof value !== 'string' || !value || value.includes('\0') || !isAbsolute(value)) fail(code)
  const normalized = resolve(value)
  if (normalized === parse(normalized).root) fail(code)
  return normalized
}

export function parsePlatforms(value: string): Platform[] {
  if (typeof value !== 'string') fail('platforms_invalid')
  const requested = value.split(',').map(item => item.trim().toLowerCase())
  if (requested.every(item => item === '')) fail('platforms_empty')
  if (requested.some(item => item === '')) fail('platforms_invalid')
  if (new Set(requested).size !== requested.length) fail('platforms_duplicate')
  if (requested.some(item => !PLATFORMS.includes(item as Platform))) fail('platforms_invalid')
  const selected = new Set(requested)
  return PLATFORMS.filter(platform => selected.has(platform))
}

/**
 * Resolve the backend for one run: this run's explicit choice wins, then the
 * saved profile preference, then the legacy compatible default `cdp`. `auto` is
 * rejected so a failing backend can never be swapped out silently.
 */
export function resolveBackend(
  explicit: string | undefined,
  preference: string | undefined,
): Backend {
  for (const candidate of [explicit, preference]) {
    if (candidate === undefined) continue
    if (typeof candidate !== 'string') fail('backend_invalid')
    const lowered = candidate.trim().toLowerCase()
    if (lowered === '') continue
    if (lowered === 'browserskill') fail('backend-retired-browserskill')
    if (lowered === 'computer_use') fail('backend-retired-computer-use')
    if (lowered === 'auto') fail('backend_auto_unsupported')
    if (!BACKENDS.includes(lowered as Backend)) fail('backend_invalid')
    return lowered as Backend
  }
  return DEFAULT_BACKEND
}

export function parseCountMode(value: string | undefined, fallback: CountMode): CountMode {
  if (value === undefined) return fallback
  if (typeof value !== 'string') fail('count_mode_invalid')
  const lowered = value.trim().toLowerCase()
  if (lowered !== 'fixed' && lowered !== 'best_effort') fail('count_mode_invalid')
  return lowered
}

export function parseExportFormat(value: string | undefined): ExportFormat {
  const candidate = value ?? 'xlsx'
  if (!EXPORT_FORMATS.includes(candidate as ExportFormat)) fail('export_format_invalid')
  return candidate as ExportFormat
}

/** Resolve and validate all deployment-varying plugin settings. */
export function normalizePluginConfig(
  input: PluginConfigInput = {},
  dshHome: string,
  userHome = homedir(),
): PluginConfig {
  const normalizedDshHome = safeAbsolutePath(dshHome, 'dsh_home_invalid')
  const normalizedUserHome = safeAbsolutePath(userHome, 'user_home_invalid')
  const maxCount = finiteInteger(input.maxCount ?? 500, 1, 5000, 'max_count_invalid')
  const defaultCount = finiteInteger(input.defaultCount ?? 10, 1, maxCount, 'default_count_invalid')
  const defaultXhsComments = finiteInteger(
    input.defaultXhsComments ?? 0,
    0,
    100,
    'default_xhs_comments_invalid',
  )
  if (
    input.defaultAllowNavigation !== undefined
    && typeof input.defaultAllowNavigation !== 'boolean'
  ) fail('default_navigation_invalid')
  const platformTimeoutSeconds = positiveFinite(
    input.platformTimeoutSeconds ?? 300,
    'platform_timeout_invalid',
  )
  const executionTimeoutSeconds = positiveFinite(
    input.executionTimeoutSeconds ?? 1260,
    'execution_timeout_invalid',
  )
  const defaultRunDeadlineSeconds = positiveFinite(
    input.defaultRunDeadlineSeconds ?? 900,
    'run_deadline_invalid',
  )
  const profilePath = safeAbsolutePath(
    input.profilePath ?? join(normalizedUserHome, '.config', 'media-missher', 'profile.json'),
    'profile_path_invalid',
  )
  const runtimeHome = safeAbsolutePath(
    input.runtimeHome ?? join(normalizedUserHome, '.local', 'share', 'media-missher'),
    'runtime_home_invalid',
  )
  const outputRoot = safeAbsolutePath(
    input.outputRoot ?? join(normalizedDshHome, 'media-missher', 'runs'),
    'output_root_invalid',
  )
  if (outputRoot === normalizedDshHome) fail('output_root_invalid')

  return {
    // X is selectable but deliberately not a default: adding a platform must
    // never make an existing profile collect it without being asked.
    defaultPlatforms: parsePlatforms(
      input.defaultPlatforms ?? 'bilibili,xhs,douyin,weibo',
    ),
    defaultCount,
    defaultXhsComments,
    defaultAllowNavigation: input.defaultAllowNavigation ?? false,
    defaultBackend: resolveBackend(input.defaultBackend, undefined),
    defaultCountMode: parseCountMode(input.defaultCountMode, 'fixed'),
    defaultRunDeadlineSeconds,
    platformTimeoutSeconds,
    executionTimeoutSeconds,
    maxCount,
    profilePath,
    runtimeHome,
    outputRoot,
  }
}

const SAFE_HANDLE = /^[A-Za-z0-9_]{1,15}$/
const SAFE_TEXT = /^[^\u0000-\u001f\u007f]{1,200}$/

/**
 * Native account identity shape, per platform. XHS uses a 24-hex user id, Douyin
 * a secUid, and the remaining platforms a decimal id. One shared pattern would
 * either reject real accounts or accept meaningless ids.
 */
export function validTargetUid(platform: Platform, value: string): boolean {
  if (platform === 'xhs') return /^[a-fA-F0-9]{24}$/.test(value)
  if (platform === 'douyin') return /^[A-Za-z0-9._-]{1,256}$/.test(value) && value !== '.' && value !== '..'
  return /^[0-9]{1,32}$/.test(value)
}

/** Validate one explicit target. A display label is never used as an identity. */
export function normalizeTarget(input: unknown): CollectTarget {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) fail('target_invalid')
  const raw = input as Record<string, unknown>
  const allowed = ['platform', 'mode', 'label', 'uid', 'handle', 'homepage', 'keyword', 'topic', 'topic_kind', 'sort']
  if (Object.keys(raw).some(key => !allowed.includes(key))) fail('target_invalid')
  const platform = raw.platform
  if (typeof platform !== 'string' || !PLATFORMS.includes(platform as Platform)) fail('target_platform_invalid')
  const mode = raw.mode ?? 'creator'
  if (typeof mode !== 'string' || !TASK_MODES.includes(mode as TaskMode)) fail('target_mode_invalid')
  const text = (value: unknown, code: string): string | undefined => {
    if (value === undefined || value === null) return undefined
    if (typeof value !== 'string' || !value.trim()) fail(code)
    return value.trim()
  }
  const label = text(raw.label, 'target_label_invalid')
  if (label !== undefined && label.length > 256) fail('target_label_invalid')
  const uid = text(raw.uid, 'target_uid_invalid')
  const handle = text(raw.handle, 'target_handle_invalid')
  const homepage = text(raw.homepage, 'target_homepage_invalid')
  const keyword = text(raw.keyword, 'target_keyword_invalid')
  const topic = text(raw.topic, 'target_topic_invalid')
  if (uid !== undefined && !validTargetUid(platform as Platform, uid)) fail('target_uid_invalid')
  if (handle !== undefined && !SAFE_HANDLE.test(handle.replace(/^@/, ''))) fail('target_handle_invalid')
  if (homepage !== undefined && !/^https:\/\//.test(homepage)) fail('target_homepage_invalid')
  if (keyword !== undefined && !SAFE_TEXT.test(keyword)) fail('target_keyword_invalid')
  if (topic !== undefined && !SAFE_TEXT.test(topic)) fail('target_topic_invalid')
  const target: CollectTarget = { platform: platform as Platform, mode: mode as TaskMode }
  if (label !== undefined) target.label = label
  if (uid !== undefined) target.uid = uid
  if (handle !== undefined) target.handle = platform === 'x' ? handle.replace(/^@/, '').toLowerCase() : handle.replace(/^@/, '')
  if (homepage !== undefined) target.homepage = homepage
  if (keyword !== undefined) target.keyword = keyword
  if (topic !== undefined) target.topic = topic
  if (raw.topic_kind !== undefined) {
    if (raw.topic_kind !== 'topic' && raw.topic_kind !== 'super') fail('target_topic_kind_invalid')
    target.topicKind = raw.topic_kind
  }
  if (raw.sort !== undefined) {
    if (raw.sort !== 'latest' && raw.sort !== 'top') fail('target_sort_invalid')
    target.sort = raw.sort
  }
  if (target.mode === 'creator' && !target.uid && !target.handle && !target.homepage) fail('target_identity_missing')
  if (target.mode === 'search' && !target.keyword) fail('target_keyword_missing')
  if (target.mode === 'topic') {
    if (target.platform !== 'weibo') fail('target_topic_platform_invalid')
    if (!target.topic) fail('target_topic_missing')
    if (target.topicKind === undefined) target.topicKind = 'topic'
  }
  return target
}

export function targetIdentity(target: CollectTarget): string {
  if (target.mode === 'creator') return `${target.platform}:creator:${target.uid ?? target.handle ?? target.homepage ?? ''}`
  if (target.mode === 'search') return `${target.platform}:search:${target.sort ?? 'latest'}:${target.keyword ?? ''}`
  return `${target.platform}:topic:${target.topicKind ?? 'topic'}:${target.topic ?? ''}`
}

/** Resolve a model request into one canonical, bounded collection request. */
export function normalizeCollectArgs(
  input: unknown,
  config: PluginConfig,
  profilePreference?: { backend?: string; targets?: CollectTarget[] },
): CollectArgs {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) fail('arguments_invalid')
  const supplied = input as Record<string, unknown>
  const allowed = ['platforms', 'count', 'count_mode', 'backend', 'xhs_comments', 'allow_navigation', 'resume_run', 'run_deadline_seconds', 'targets']
  if (Object.keys(supplied).some(key => !allowed.includes(key))) fail('arguments_invalid')
  for (const key of allowed) {
    if (supplied[key] === null) fail('arguments_invalid')
  }
  const args = supplied as CollectArgsInput
  const countMode = parseCountMode(args.count_mode, config.defaultCountMode)
  const backend = resolveBackend(args.backend, profilePreference?.backend ?? config.defaultBackend)
  const suppliedTargets = args.targets !== undefined
  const rawTargets = suppliedTargets ? args.targets : profilePreference?.targets ?? []
  if (!Array.isArray(rawTargets) || rawTargets.length > 200) fail('targets_invalid')
  const normalized = rawTargets.map(normalizeTarget)
  const identities = normalized.map(targetIdentity)
  if (new Set(identities).size !== identities.length) fail('targets_duplicate')
  // A caller that names its platforms keeps that exact list, so a platform whose
  // saved target is missing is reported as needing setup instead of silently
  // disappearing from the request. Saved targets for platforms this call did not
  // select are simply not part of this run. A saved platform may legitimately
  // carry several accounts, so two targets on one platform is not a conflict.
  const namedPlatforms = args.platforms === undefined ? undefined : parsePlatforms(args.platforms)
  const targets = namedPlatforms === undefined
    ? normalized
    : suppliedTargets
      ? normalized
      : normalized.filter(target => namedPlatforms.includes(target.platform))
  if (namedPlatforms !== undefined && suppliedTargets) {
    const selected = new Set(namedPlatforms)
    if (targets.some(target => !selected.has(target.platform))) fail('platforms_target_conflict')
  }
  const platforms = namedPlatforms
    ?? (targets.length > 0
      ? PLATFORMS.filter(platform => targets.some(target => target.platform === platform))
      : [...config.defaultPlatforms])
  // best_effort is deliberately not bounded by `count`; the runtime deadline and
  // the per-platform batch budget are the real limits.
  const count = finiteInteger(args.count ?? config.defaultCount, 1, config.maxCount, 'count_invalid')
  const xhsComments = finiteInteger(
    args.xhs_comments ?? config.defaultXhsComments,
    0,
    100,
    'xhs_comments_invalid',
  )
  if (args.allow_navigation !== undefined && typeof args.allow_navigation !== 'boolean') {
    fail('allow_navigation_invalid')
  }
  const runDeadlineSeconds = args.run_deadline_seconds === undefined
    ? config.defaultRunDeadlineSeconds
    : positiveFinite(args.run_deadline_seconds, 'run_deadline_invalid')
  if (xhsComments > 0 && !platforms.includes('xhs')) fail('xhs_comments_platform_invalid')
  if (args.resume_run !== undefined && (typeof args.resume_run !== 'string' || !/^run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(args.resume_run))) fail('resume_run_invalid')
  return {
    platforms,
    platformText: platforms.join(','),
    count,
    countMode,
    backend,
    targets,
    xhsComments,
    allowNavigation: args.allow_navigation ?? config.defaultAllowNavigation,
    runDeadlineSeconds,
    ...(args.resume_run === undefined ? {} : { resumeRun: args.resume_run }),
  }
}

/** Resolve the requested export selection without ever collecting more data. */
export function normalizeExportSelection(input: unknown): ExportSelection {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) fail('export_arguments_invalid')
  const supplied = input as ExportSelectionInput
  const allowed = ['run_id', 'record_kinds', 'platforms', 'topics', 'targets', 'fields', 'field_groups', 'format', 'file_name', 'overwrite']
  if (Object.keys(supplied).some(key => !allowed.includes(key))) fail('export_arguments_invalid')
  const runId = supplied.run_id
  if (typeof runId !== 'string' || !/^run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runId)) fail('run_id_invalid')
  const stringList = (value: unknown, code: string, maximum = 64): string[] => {
    if (value === undefined) return []
    if (!Array.isArray(value) || value.length > maximum) fail(code)
    const items = value.map(item => {
      if (typeof item !== 'string' || !item.trim() || item.length > 200 || /[\u0000-\u001f\u007f]/.test(item)) fail(code)
      return item.trim()
    })
    if (new Set(items).size !== items.length) fail(code)
    return items
  }
  const recordKinds = stringList(supplied.record_kinds, 'export_record_kinds_invalid')
  if (recordKinds.length === 0) fail('export_record_kinds_invalid')
  if (recordKinds.some(kind => !EXPORT_RECORD_KINDS.includes(kind as ExportRecordKind))) fail('export_record_kinds_invalid')
  const platforms = stringList(supplied.platforms, 'export_platforms_invalid')
  if (platforms.some(platform => !PLATFORMS.includes(platform as Platform))) fail('export_platforms_invalid')
  const fileName = supplied.file_name
  if (fileName !== undefined) {
    if (typeof fileName !== 'string' || fileName === '' || fileName === '.' || fileName === '..' || /[\/\\\u0000]/.test(fileName)) fail('export_file_name_invalid')
  }
  if (supplied.overwrite !== undefined && typeof supplied.overwrite !== 'boolean') fail('export_overwrite_invalid')
  return {
    runId,
    recordKinds: recordKinds as ExportRecordKind[],
    platforms: PLATFORMS.filter(platform => platforms.includes(platform)),
    topics: stringList(supplied.topics, 'export_topics_invalid'),
    targets: stringList(supplied.targets, 'export_targets_invalid'),
    fields: stringList(supplied.fields, 'export_fields_invalid', 256),
    fieldGroups: stringList(supplied.field_groups, 'export_field_groups_invalid'),
    format: parseExportFormat(supplied.format),
    ...(fileName === undefined ? {} : { fileName }),
    overwrite: supplied.overwrite ?? false,
  }
}
