import { homedir } from 'node:os'
import { isAbsolute, join, parse, resolve } from 'node:path'

export const PLATFORMS = ['bilibili', 'xhs', 'douyin', 'weibo'] as const
export type Platform = typeof PLATFORMS[number]

export interface PluginConfigInput {
  defaultPlatforms?: string
  defaultCount?: number
  defaultXhsComments?: number
  defaultAllowNavigation?: boolean
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
  platformTimeoutSeconds: number
  executionTimeoutSeconds: number
  maxCount: number
  profilePath: string
  runtimeHome: string
  outputRoot: string
}

export interface CollectArgsInput {
  platforms?: string
  count?: number
  xhs_comments?: number
  allow_navigation?: boolean
}

export interface CollectArgs {
  platforms: Platform[]
  platformText: string
  count: number
  xhsComments: number
  allowNavigation: boolean
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
  if (!value || !isAbsolute(value)) fail(code)
  const normalized = resolve(value)
  if (normalized === parse(normalized).root) fail(code)
  return normalized
}

function parsePlatforms(value: string): Platform[] {
  const requested = value.split(',').map(item => item.trim().toLowerCase()).filter(Boolean)
  if (requested.length === 0) fail('platforms_empty')
  if (new Set(requested).size !== requested.length) fail('platforms_duplicate')
  if (requested.some(item => !PLATFORMS.includes(item as Platform))) fail('platforms_invalid')
  const selected = new Set(requested)
  return PLATFORMS.filter(platform => selected.has(platform))
}

/** Resolve and validate all deployment-varying plugin settings. */
export function normalizePluginConfig(
  input: PluginConfigInput = {},
  dshHome: string,
  userHome = homedir(),
): PluginConfig {
  const normalizedDshHome = safeAbsolutePath(dshHome, 'dsh_home_invalid')
  const normalizedUserHome = safeAbsolutePath(userHome, 'user_home_invalid')
  const maxCount = finiteInteger(input.maxCount ?? 50, 1, 100, 'max_count_invalid')
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
    defaultPlatforms: parsePlatforms(
      input.defaultPlatforms ?? 'bilibili,xhs,douyin,weibo',
    ),
    defaultCount,
    defaultXhsComments,
    defaultAllowNavigation: input.defaultAllowNavigation ?? true,
    platformTimeoutSeconds,
    executionTimeoutSeconds,
    maxCount,
    profilePath,
    runtimeHome,
    outputRoot,
  }
}

/** Resolve a model request into one canonical, bounded collection request. */
export function normalizeCollectArgs(
  input: CollectArgsInput,
  config: PluginConfig,
): CollectArgs {
  const platforms = input.platforms === undefined
    ? [...config.defaultPlatforms]
    : parsePlatforms(input.platforms)
  const count = finiteInteger(input.count ?? config.defaultCount, 1, config.maxCount, 'count_invalid')
  const xhsComments = finiteInteger(
    input.xhs_comments ?? config.defaultXhsComments,
    0,
    100,
    'xhs_comments_invalid',
  )
  if (input.allow_navigation !== undefined && typeof input.allow_navigation !== 'boolean') {
    fail('allow_navigation_invalid')
  }
  return {
    platforms,
    platformText: platforms.join(','),
    count,
    xhsComments,
    allowNavigation: input.allow_navigation ?? config.defaultAllowNavigation,
  }
}
