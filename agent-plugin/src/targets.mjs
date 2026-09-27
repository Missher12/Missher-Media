// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
/**
 * Pure, I/O-free validation shared by the Agent CLI: collection targets, the
 * backend frozen for one run, the two count modes and the export selection that
 * is applied to already-saved private results after collection.
 *
 * Every failure is a `TargetError` whose message is exactly one fixed code from
 * `TARGET_ERROR_CODES`. A caller-supplied value is never echoed, so no topic,
 * keyword, handle, homepage or file name can leak into logs or Agent output.
 */

export const PLATFORMS = ['bilibili', 'xhs', 'douyin', 'weibo', 'x']
export const TARGET_MODES = ['creator', 'search', 'topic']
export const BACKENDS = ['cdp']
export const DEFAULT_BACKEND = 'cdp'
export const COUNT_MODES = ['fixed', 'best_effort']
export const DEFAULT_COUNT_MODE = 'fixed'
export const TOPIC_KINDS = ['topic', 'super']
export const TARGET_SORTS = ['latest', 'top']
export const EXPORT_RECORD_KINDS = ['posts', 'topic_participants', 'user_profiles']
export const EXPORT_FORMATS = ['xlsx', 'csv', 'json', 'jsonl', 'sqlite']
export const DEFAULT_EXPORT_FORMAT = 'xlsx'
export const MAX_TARGETS = 200
export const MAX_TEXT = 200
export const MAX_LIST_ITEMS = 64
export const MAX_FIELD_ITEMS = 256

/** Fixed error codes; `TARGET_ERROR_CODES` is the sorted, complete set. */
export class TargetError extends Error {
  constructor(code) {
    super(code)
    this.name = 'TargetError'
    this.code = code
  }
}

const SAFE_RUN_ID = /^run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u
const SAFE_UID = /^[0-9]{1,32}$/u
const SAFE_HANDLE = /^[A-Za-z0-9_]{1,15}$/u
const SAFE_TEXT = /^[^\u0000-\u001f\u007f]{1,200}$/u
const CONTROL = /[\u0000-\u001f\u007f]/u
const TARGET_KEYS = ['platform', 'mode', 'label', 'uid', 'handle', 'homepage', 'keyword', 'topic', 'topicKind', 'sort']
const MODE_FIELDS = {
  creator: ['uid', 'handle', 'homepage'],
  search: ['keyword', 'sort'],
  topic: ['topic', 'topicKind'],
}
const FIELD_CODES = {
  uid: 'target_uid_invalid',
  handle: 'target_handle_invalid',
  homepage: 'target_homepage_invalid',
  keyword: 'target_keyword_invalid',
  topic: 'target_topic_invalid',
  topicKind: 'target_topic_kind_invalid',
  sort: 'target_sort_invalid',
}
const EXPORT_KEYS = {
  runId: 'runId', run_id: 'runId',
  recordKinds: 'recordKinds', record_kinds: 'recordKinds',
  platforms: 'platforms', topics: 'topics', targets: 'targets', fields: 'fields',
  fieldGroups: 'fieldGroups', field_groups: 'fieldGroups',
  format: 'format', fileName: 'fileName', file_name: 'fileName', overwrite: 'overwrite',
}

/** Stable identity for one target. A display label is never part of it. */
export function targetIdentity(target) {
  if (target === null || typeof target !== 'object' || Array.isArray(target)) throw new TargetError('target_invalid')
  const platform = target.platform
  if (typeof platform !== 'string' || !PLATFORMS.includes(platform)) throw new TargetError('target_platform_invalid')
  const mode = target.mode ?? 'creator'
  if (typeof mode !== 'string' || !TARGET_MODES.includes(mode)) throw new TargetError('target_mode_invalid')
  if (mode === 'creator') return `${platform}:creator:${target.uid ?? target.handle ?? target.homepage ?? ''}`
  if (mode === 'search') return `${platform}:search:${target.sort ?? 'latest'}:${target.keyword ?? ''}`
  return `${platform}:topic:${target.topicKind ?? 'topic'}:${target.topic ?? ''}`
}

function text(value, code, maximum = MAX_TEXT) {
  if (value === undefined) return undefined
  if (typeof value !== 'string') throw new TargetError(code)
  const trimmed = value.trim()
  if (!trimmed || trimmed.length > maximum || CONTROL.test(trimmed)) throw new TargetError(code)
  return trimmed
}

/** Validate one explicit target. A nickname or label alone is never an identity. */
export function normalizeTarget(input) {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new TargetError('target_invalid')
  if (Object.keys(input).some(key => !TARGET_KEYS.includes(key))) throw new TargetError('target_invalid')
  const platform = input.platform
  if (typeof platform !== 'string' || !PLATFORMS.includes(platform)) throw new TargetError('target_platform_invalid')
  const mode = input.mode ?? 'creator'
  if (typeof mode !== 'string' || !TARGET_MODES.includes(mode)) throw new TargetError('target_mode_invalid')
  for (const key of Object.keys(input)) {
    if (key === 'platform' || key === 'mode' || key === 'label') continue
    if (!MODE_FIELDS[mode].includes(key)) throw new TargetError(FIELD_CODES[key])
  }
  const label = text(input.label, 'target_label_invalid', 256)
  const uid = text(input.uid, 'target_uid_invalid')
  const validUid = value => platform === 'xhs' ? /^[a-fA-F0-9]{24}$/u.test(value)
    : platform === 'douyin' ? /^[A-Za-z0-9._-]{1,256}$/u.test(value) && value !== '.' && value !== '..'
      : SAFE_UID.test(value)
  if (uid !== undefined && !validUid(uid)) throw new TargetError('target_uid_invalid')
  const rawHandle = text(input.handle, 'target_handle_invalid')
  const cleanHandle = rawHandle?.replace(/^@/u, '')
  const handle = platform === 'x' ? cleanHandle?.toLowerCase() : cleanHandle
  if (handle !== undefined && !SAFE_HANDLE.test(handle)) throw new TargetError('target_handle_invalid')
  const homepage = text(input.homepage, 'target_homepage_invalid', 2048)
  if (homepage !== undefined && !homepage.startsWith('https://')) throw new TargetError('target_homepage_invalid')
  const keyword = text(input.keyword, 'target_keyword_invalid')
  if (keyword !== undefined && !SAFE_TEXT.test(keyword)) throw new TargetError('target_keyword_invalid')
  const topic = text(input.topic, 'target_topic_invalid')
  if (topic !== undefined && !SAFE_TEXT.test(topic)) throw new TargetError('target_topic_invalid')
  if (input.topicKind !== undefined && !TOPIC_KINDS.includes(input.topicKind)) throw new TargetError('target_topic_kind_invalid')
  if (input.sort !== undefined && !TARGET_SORTS.includes(input.sort)) throw new TargetError('target_sort_invalid')
  const target = { platform, mode }
  if (label !== undefined) target.label = label
  if (uid !== undefined) target.uid = uid
  if (handle !== undefined) target.handle = handle
  if (homepage !== undefined) target.homepage = homepage
  if (keyword !== undefined) target.keyword = keyword
  if (topic !== undefined) target.topic = topic
  if (input.sort !== undefined) target.sort = input.sort
  if (target.mode === 'creator' && !target.uid && !target.handle && !target.homepage) throw new TargetError('target_identity_missing')
  if (target.mode === 'search' && target.keyword === undefined) throw new TargetError('target_keyword_missing')
  if (target.mode === 'topic') {
    if (target.platform !== 'weibo') throw new TargetError('target_topic_platform_invalid')
    if (target.topic === undefined) throw new TargetError('target_topic_missing')
    target.topicKind = input.topicKind ?? 'topic'
  }
  return target
}

/** Validate one non-empty, bounded selection of distinct targets. */
export function normalizeTargets(value) {
  if (!Array.isArray(value) || value.length > MAX_TARGETS) throw new TargetError('targets_invalid')
  const targets = value.map(normalizeTarget)
  const identities = targets.map(targetIdentity)
  if (new Set(identities).size !== identities.length) throw new TargetError('targets_duplicate')
  return targets
}

/** This run's explicit backend wins, then the saved preference, then `cdp`. */
export function resolveBackend(explicit, preference) {
  for (const candidate of [explicit, preference]) {
    if (candidate === undefined) continue
    if (typeof candidate !== 'string') throw new TargetError('backend_invalid')
    const lowered = candidate.trim().toLowerCase()
    if (lowered === '') continue
    if (lowered === 'browserskill') throw new TargetError('backend-retired-browserskill')
    if (lowered === 'computer_use') throw new TargetError('backend-retired-computer-use')
    if (lowered === 'auto') throw new TargetError('backend_auto_unsupported')
    if (!BACKENDS.includes(lowered)) throw new TargetError('backend_invalid')
    return lowered
  }
  return DEFAULT_BACKEND
}

export function parseCountMode(value, fallback = DEFAULT_COUNT_MODE) {
  const candidate = value === undefined ? fallback : value
  if (typeof candidate !== 'string') throw new TargetError('count_mode_invalid')
  const lowered = candidate.trim().toLowerCase()
  if (!COUNT_MODES.includes(lowered)) throw new TargetError('count_mode_invalid')
  return lowered
}

function stringList(value, code, maximum = MAX_LIST_ITEMS) {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > maximum) throw new TargetError(code)
  const items = value.map(item => {
    if (typeof item !== 'string') throw new TargetError(code)
    const trimmed = item.trim()
    if (!trimmed || trimmed.length > MAX_TEXT || CONTROL.test(trimmed)) throw new TargetError(code)
    return trimmed
  })
  if (new Set(items).size !== items.length) throw new TargetError(code)
  return items
}

function plainBaseName(value) {
  return typeof value === 'string' && value !== '' && value !== '.' && value !== '..'
    && value.length <= 255 && !/[/\\\u0000]/u.test(value) && !CONTROL.test(value)
}

/** Resolve the export selection that is applied to already-saved private results. */
export function normalizeExportSelection(input) {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new TargetError('export_arguments_invalid')
  const supplied = {}
  for (const [key, value] of Object.entries(input)) {
    const name = EXPORT_KEYS[key]
    if (name === undefined || Object.hasOwn(supplied, name)) throw new TargetError('export_arguments_invalid')
    supplied[name] = value
  }
  const runId = supplied.runId
  if (typeof runId !== 'string' || !SAFE_RUN_ID.test(runId)) throw new TargetError('run_id_invalid')
  const recordKinds = stringList(supplied.recordKinds, 'export_record_kinds_invalid')
  if (recordKinds.length === 0 || recordKinds.some(kind => !EXPORT_RECORD_KINDS.includes(kind))) throw new TargetError('export_record_kinds_invalid')
  const platforms = stringList(supplied.platforms, 'export_platforms_invalid')
  if (platforms.some(platform => !PLATFORMS.includes(platform))) throw new TargetError('export_platforms_invalid')
  const topics = stringList(supplied.topics, 'export_topics_invalid')
  const targets = stringList(supplied.targets, 'export_targets_invalid')
  const fields = stringList(supplied.fields, 'export_fields_invalid', MAX_FIELD_ITEMS)
  const fieldGroups = stringList(supplied.fieldGroups, 'export_field_groups_invalid')
  const format = supplied.format ?? DEFAULT_EXPORT_FORMAT
  if (typeof format !== 'string' || !EXPORT_FORMATS.includes(format)) throw new TargetError('export_format_invalid')
  if (supplied.fileName !== undefined && !plainBaseName(supplied.fileName)) throw new TargetError('export_file_name_invalid')
  const overwrite = supplied.overwrite ?? false
  if (typeof overwrite !== 'boolean') throw new TargetError('export_overwrite_invalid')
  return {
    runId,
    recordKinds,
    platforms: PLATFORMS.filter(platform => platforms.includes(platform)),
    topics,
    targets,
    fields,
    fieldGroups,
    format,
    ...(supplied.fileName === undefined ? {} : { fileName: supplied.fileName }),
    overwrite,
  }
}

/** Sorted, complete list of every code this module can throw. */
export const TARGET_ERROR_CODES = Object.freeze([
  'backend-retired-browserskill',
  'backend-retired-computer-use',
  'backend_auto_unsupported',
  'backend_invalid',
  'count_mode_invalid',
  'export_arguments_invalid',
  'export_field_groups_invalid',
  'export_fields_invalid',
  'export_file_name_invalid',
  'export_format_invalid',
  'export_overwrite_invalid',
  'export_platforms_invalid',
  'export_record_kinds_invalid',
  'export_targets_invalid',
  'export_topics_invalid',
  'run_id_invalid',
  'target_handle_invalid',
  'target_homepage_invalid',
  'target_identity_missing',
  'target_invalid',
  'target_keyword_invalid',
  'target_keyword_missing',
  'target_label_invalid',
  'target_mode_invalid',
  'target_platform_invalid',
  'target_sort_invalid',
  'target_topic_invalid',
  'target_topic_kind_invalid',
  'target_topic_missing',
  'target_topic_platform_invalid',
  'target_uid_invalid',
  'targets_duplicate',
  'targets_invalid',
])
