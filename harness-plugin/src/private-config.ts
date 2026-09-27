import { constants, type Stats } from 'node:fs'
import { lstat, mkdir, open, realpath } from 'node:fs/promises'
import { dirname, isAbsolute, parse, resolve } from 'node:path'
import { PLATFORMS, type CollectTarget, type Platform } from './config.js'

const PROFILE_LIMIT = 256 * 1024
export const isMissing = (error: unknown): boolean => (error as NodeJS.ErrnoException).code === 'ENOENT'
const owned = (stat: Stats): boolean => process.getuid === undefined || stat.uid === process.getuid()

/** Reject link traversal before using paths supplied by a caller or a saved profile. */
export async function checkPath(path: string): Promise<void> {
  if (!isAbsolute(path) || path.includes('\0') || path !== resolve(path)) throw new Error('setup_path_invalid')
  let current = path
  while (true) {
    try {
      const stat = await lstat(current)
      if (stat.isSymbolicLink()) throw new Error('setup_symlink_forbidden')
      if (current !== path && !stat.isDirectory()) throw new Error('setup_path_invalid')
    } catch (error) {
      if (!isMissing(error)) throw error
    }
    const parent = dirname(current)
    if (parent === current) break
    current = parent
  }
}

/** Creates only missing directories; never repairs permissions on an existing location. */
export async function privateDirectory(path: string): Promise<void> {
  await checkPath(path)
  try { await mkdir(path, { mode: 0o700 }) } catch (error) {
    if (isMissing(error)) {
      const parent = dirname(path)
      if (parent === parse(path).root) throw new Error('setup_directory_invalid')
      await privateDirectory(parent)
      await mkdir(path, { mode: 0o700 })
    } else if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
  }
  const stat = await lstat(path)
  if (!stat.isDirectory() || !owned(stat) || (stat.mode & 0o777) !== 0o700 || await realpath(path) !== path) throw new Error('setup_directory_invalid')
}

export async function readBoundedFile(path: string, maxBytes: number, privateOnly = true): Promise<Buffer> {
  await checkPath(path)
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
  try {
    const before = await file.stat()
    const valid = (stat: Stats) => stat.isFile() && owned(stat) && stat.nlink === 1
      && (privateOnly ? (stat.mode & 0o777) === 0o600 : (stat.mode & 0o022) === 0)
    if (!valid(before)) throw new Error('setup_file_invalid')
    if (before.size > maxBytes) throw new Error('setup_file_too_large')
    const buffer = Buffer.alloc(maxBytes + 1)
    let length = 0
    while (length < buffer.length) {
      const { bytesRead } = await file.read(buffer, length, buffer.length - length, null)
      if (bytesRead === 0) break
      length += bytesRead
    }
    const after = await file.stat()
    const current = await lstat(path)
    await checkPath(path)
    if (length > maxBytes) throw new Error('setup_file_too_large')
    if (!valid(after) || !valid(current) || before.dev !== current.dev || before.ino !== current.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) throw new Error('setup_file_changed')
    return buffer.subarray(0, length)
  } finally { await file.close() }
}

export async function writePrivateFile(path: string, bytes: Buffer | string): Promise<void> {
  await checkPath(path)
  const file = await open(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600)
  try { await file.writeFile(bytes); await file.sync() } finally { await file.close() }
}

export function jsonObject(bytes: Buffer): Record<string, unknown> {
  let value: unknown
  try { value = JSON.parse(bytes.toString('utf8')) } catch { throw new Error('setup_json_invalid') }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('setup_json_invalid')
  return value as Record<string, unknown>
}

export function validNativeId(platform: Platform, value: unknown): value is string {
  if (typeof value !== 'string') return false
  if (platform === 'xhs') return /^[a-fA-F0-9]{24}$/.test(value)
  if (platform === 'douyin') return /^[A-Za-z0-9._-]{1,256}$/.test(value) && value !== '.' && value !== '..'
  return /^[0-9]{1,32}$/.test(value)
}

const SAFE_HANDLE = /^@?[A-Za-z0-9_]{1,15}$/
const SAFE_TEXT = /^[^\u0000-\u001f\u007f]{1,200}$/

/**
 * Parse the v2 `targets` array. Unlike the legacy `platform_uids` map this keeps
 * a stable identity per target and allows several targets on one platform.
 */
export function parseProfileTargets(value: unknown): CollectTarget[] {
  if (!Array.isArray(value) || value.length > 200) throw new Error('profile_targets_invalid')
  const targets: CollectTarget[] = []
  for (const raw of value) {
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('profile_targets_invalid')
    const item = raw as Record<string, unknown>
    const allowed = ['platform', 'mode', 'label', 'uid', 'handle', 'homepage', 'keyword', 'topic', 'topicKind', 'sort']
    if (Object.keys(item).some(key => !allowed.includes(key))) throw new Error('profile_targets_invalid')
    const platform = item.platform
    if (typeof platform !== 'string' || !PLATFORMS.includes(platform as Platform)) throw new Error('profile_targets_invalid')
    const mode = item.mode ?? 'creator'
    if (mode !== 'creator' && mode !== 'search' && mode !== 'topic') throw new Error('profile_targets_invalid')
    const optional = (key: string, pattern: RegExp): string | undefined => {
      const candidate = item[key]
      if (candidate === undefined || candidate === null) return undefined
      if (typeof candidate !== 'string' || !pattern.test(candidate)) throw new Error('profile_targets_invalid')
      return candidate
    }
    // A roster name may legitimately contain line breaks; only the characters
    // that could forge a path, a terminal line or a NUL are refused.
    const label = optional('label', /^[^\u0000-\u0009\u000b\u000c\u000e-\u001f\u007f]{1,256}$/)
    // The native identifier shape is per platform: XHS uses a 24-hex note/user
    // id, Douyin a secUid, the rest a decimal id. Delegate to the same check the
    // legacy map uses so a migrated profile is not rejected.
    const rawUid = item.uid
    if (rawUid !== undefined && rawUid !== null && !validNativeId(platform as Platform, rawUid)) throw new Error('profile_targets_invalid')
    const uid = rawUid === undefined || rawUid === null ? undefined : rawUid as string
    const handle = optional('handle', SAFE_HANDLE)
    const homepage = optional('homepage', /^https:\/\/[^\s]{1,2048}$/)
    const keyword = optional('keyword', SAFE_TEXT)
    const topic = optional('topic', SAFE_TEXT)
    const target: CollectTarget = { platform: platform as Platform, mode }
    if (label !== undefined) target.label = label
    if (uid !== undefined) target.uid = uid
    if (handle !== undefined) target.handle = platform === 'x' ? handle.replace(/^@/, '').toLowerCase() : handle.replace(/^@/, '')
    if (homepage !== undefined) target.homepage = homepage
    if (keyword !== undefined) target.keyword = keyword
    if (topic !== undefined) target.topic = topic
    if (item.topicKind !== undefined) {
      if (item.topicKind !== 'topic' && item.topicKind !== 'super') throw new Error('profile_targets_invalid')
      target.topicKind = item.topicKind
    }
    if (item.sort !== undefined) {
      if (item.sort !== 'latest' && item.sort !== 'top') throw new Error('profile_targets_invalid')
      target.sort = item.sort
    }
    if (target.mode === 'creator' && !target.uid && !target.handle && !target.homepage) throw new Error('profile_targets_invalid')
    if (target.mode === 'search' && !target.keyword) throw new Error('profile_targets_invalid')
    if (target.mode === 'topic' && (target.platform !== 'weibo' || !target.topic)) throw new Error('profile_targets_invalid')
    targets.push(target)
  }
  return targets
}

/**
 * Legacy compatibility read.
 *
 * Version 1 stored exactly one native ID per platform in `platform_uids`. That
 * shape cannot express several accounts on one platform, so it is *read* here
 * and only ever *written* back as a compatibility mirror. Unknown extra keys in
 * the saved profile are preserved untouched by the writer.
 */
export function legacyTargetsFromPlatformUids(value: Record<string, unknown>): CollectTarget[] {
  const raw = value.platform_uids ?? {}
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('profile_targets_invalid')
  const uids = raw as Record<string, unknown>
  // v1.1 already allowed a comma-free list per platform in some hand-edited
  // profiles; accept an array there too so a migrated profile is not lost.
  const targets: CollectTarget[] = []
  for (const platform of PLATFORMS) {
    const entry = uids[platform]
    if (entry === undefined || entry === null || entry === '') continue
    const values = Array.isArray(entry) ? entry : [entry]
    for (const candidate of values) {
      if (candidate === undefined || candidate === null || candidate === '') continue
      if (!validNativeId(platform, candidate)) throw new Error('profile_targets_invalid')
      targets.push({ platform, mode: 'creator', uid: candidate })
    }
  }
  return targets
}

/** `creator_targets` carries the display label and homepage for a platform. */
export function creatorTargetDecorations(value: Record<string, unknown>): Record<string, { name?: string; homepage?: string }> {
  const raw = value.creator_targets
  if (raw === undefined || raw === null) return {}
  if (typeof raw !== 'object' || Array.isArray(raw)) throw new Error('profile_targets_invalid')
  const result: Record<string, { name?: string; homepage?: string }> = {}
  for (const [platform, entry] of Object.entries(raw as Record<string, unknown>)) {
    if (!PLATFORMS.includes(platform as Platform)) throw new Error('profile_targets_invalid')
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('profile_targets_invalid')
    const item = entry as Record<string, unknown>
    if (Object.keys(item).some(key => key !== 'name' && key !== 'homepage')) throw new Error('profile_targets_invalid')
    const name = item.name
    const homepage = item.homepage
    if (name !== undefined && (typeof name !== 'string' || name.length > 256)) throw new Error('profile_targets_invalid')
    if (homepage !== undefined && (typeof homepage !== 'string' || !/^https:\/\//.test(homepage))) throw new Error('profile_targets_invalid')
    result[platform] = {
      ...(name === undefined ? {} : { name }),
      ...(homepage === undefined ? {} : { homepage }),
    }
  }
  return result
}

export interface ProfileSnapshot {
  bytes: Buffer
  value: Record<string, unknown>
  available: Platform[]
  active: Platform[]
  targets: CollectTarget[]
  /** True when the file only carried the legacy one-account-per-platform shape. */
  legacy: boolean
  backend?: string
}

export async function readProfileSnapshot(path: string): Promise<ProfileSnapshot | undefined> {
  let bytes: Buffer
  try { bytes = await readBoundedFile(path, PROFILE_LIMIT) } catch (error) {
    if (isMissing(error)) return undefined
    throw error
  }
  return parseProfileSnapshot(bytes)
}

export function parseProfileSnapshot(bytes: Buffer): ProfileSnapshot {
  const value = jsonObject(bytes)
  let legacy = false
  let targets: CollectTarget[]
  if (Object.hasOwn(value, 'targets')) {
    // A corrupt v2 list is a hard error: it must not fall back to the legacy
    // single-account map and silently drop accounts.
    targets = parseProfileTargets(value.targets)
  } else {
    legacy = true
    const decorations = creatorTargetDecorations(value)
    targets = legacyTargetsFromPlatformUids(value).map(target => {
      const decoration = target.platform === undefined ? undefined : decorations[target.platform]
      if (decoration === undefined) return target
      return {
        ...target,
        ...(decoration.name === undefined ? {} : { label: decoration.name }),
        ...(decoration.homepage === undefined ? {} : { homepage: decoration.homepage }),
      }
    })
  }
  const backend = value.backend
  if (backend !== undefined && backend !== 'cdp' && backend !== 'computer_use' && backend !== 'browserskill') throw new Error('profile_backend_invalid')
  // Every platform that has at least one saved target is "configured"; only the
  // explicitly activated subset is collected when the request names nothing.
  const configurable = PLATFORMS.filter(platform => targets.some(target => target.platform === platform))
  const available = PLATFORMS.filter(platform => {
    const raw = value.platform_uids
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return false
    const entry = (raw as Record<string, unknown>)[platform]
    if (Array.isArray(entry)) return entry.length > 0
    return validNativeId(platform, entry)
  })
  const configured = PLATFORMS.filter(platform => available.includes(platform) || configurable.includes(platform))
  const activeRaw = Object.hasOwn(value, 'active_platforms') ? value.active_platforms : configured
  if (!Array.isArray(activeRaw) || activeRaw.length > PLATFORMS.length || new Set(activeRaw).size !== activeRaw.length
    || activeRaw.some(platform => !configured.includes(platform as Platform))) throw new Error('profile_selection_invalid')
  return {
    bytes,
    value,
    available: configured,
    active: PLATFORMS.filter(platform => activeRaw.includes(platform)),
    targets,
    legacy,
    ...(backend === undefined ? {} : { backend }),
  }
}
