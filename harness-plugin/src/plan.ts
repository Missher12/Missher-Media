import { randomBytes } from 'node:crypto'
import { join } from 'node:path'
import { targetIdentity, type CollectArgs, type CollectTarget, type Platform } from './config.js'

/**
 * Mirror of the controller's `CollectionPlan` schema (DEEPSEEK_V4_PROMPT.md
 * section 7). The Harness plugin writes one frozen plan per run; the controller
 * validates it again, so this file is a request, not an authority.
 */
export interface CollectionPlan {
  schema_version: 2
  backend: string
  count_mode: 'fixed' | 'best_effort'
  count: number
  per_target_counts: Record<string, number>
  per_target_budget: number | null
  batch_pages: number
  batch_records: number | null
  batch_interval_seconds: number
  run_deadline_seconds: number
  stall_limit: number
  field_groups: string[]
  required_fields: string[]
  allow_navigation: boolean
  collect_active_platforms: boolean
  bilibili_complete: boolean
  xhs_comments: number
  screenshot_mode: 'off'
  targets: PlanTarget[]
}

export interface PlanTarget {
  platform: Platform
  mode: 'creator' | 'search' | 'topic'
  label: string
  uid: string | null
  handle: string | null
  homepage: string | null
  keyword: string | null
  topic: string | null
  topic_kind: 'topic' | 'super' | null
  sort: 'latest' | 'top' | null
}

export function planTarget(target: CollectTarget): PlanTarget {
  return {
    platform: target.platform,
    mode: target.mode,
    label: target.label ?? '',
    uid: target.uid ?? null,
    handle: target.handle ?? null,
    homepage: target.homepage ?? null,
    keyword: target.keyword ?? null,
    topic: target.topic ?? null,
    topic_kind: target.topicKind ?? null,
    sort: target.sort ?? null,
  }
}

/**
 * Per-platform batch ceilings the controller also enforces. They are declared
 * here so the request is explicit, never so the controller can be talked out of
 * its own limits: the Xiaohongshu 10-note / 3-page / 600-second policy is fixed.
 */
const BATCH_LIMITS: Record<Platform, { records: number; pages: number; interval: number }> = {
  xhs: { records: 10, pages: 3, interval: 600 },
  x: { records: 20, pages: 3, interval: 120 },
  weibo: { records: 20, pages: 3, interval: 90 },
  bilibili: { records: 20, pages: 3, interval: 60 },
  douyin: { records: 20, pages: 3, interval: 60 },
}

export function buildCollectionPlan(request: CollectArgs): CollectionPlan {
  if (request.targets.length === 0) {
    // A request without explicit targets is refused: the runtime needs a frozen
    // identity per task, and a platform name alone is not a target.
    throw new Error('plan_targets_missing')
  }
  const platforms = request.platforms
  const strictest = platforms.reduce(
    (current, platform) => Math.min(current, BATCH_LIMITS[platform].pages),
    Number.POSITIVE_INFINITY,
  )
  const batchPages = Number.isFinite(strictest) ? strictest : 3
  const batchInterval = platforms.reduce(
    (current, platform) => Math.max(current, BATCH_LIMITS[platform].interval),
    0,
  )
  return {
    schema_version: 2,
    backend: request.backend,
    count_mode: request.countMode,
    count: request.count,
    per_target_counts: {},
    // In best_effort the runtime deadline and the finite batch budget are the
    // real limits; no fixed total is declared.
    per_target_budget: null,
    batch_pages: batchPages,
    batch_records: null,
    batch_interval_seconds: request.countMode === 'best_effort' ? batchInterval : 0,
    run_deadline_seconds: request.runDeadlineSeconds,
    stall_limit: 2,
    field_groups: [],
    required_fields: [],
    allow_navigation: request.allowNavigation,
    collect_active_platforms: true,
    bilibili_complete: false,
    xhs_comments: request.xhsComments,
    screenshot_mode: 'off',
    targets: request.targets.map(planTarget),
  }
}

export function planFileName(): string {
  return `plan-${randomBytes(8).toString('hex')}.json`
}

/**
 * Resolve the targets one run will actually execute.
 *
 * When the request names targets, those are used. When it only names platforms,
 * the saved profile supplies every target for those platforms, so a platform can
 * carry several accounts instead of exactly one.
 */
export function resolveTargets(
  request: Pick<CollectArgs, 'platforms' | 'targets'>,
  profileTargets: CollectTarget[],
): CollectTarget[] {
  if (request.targets.length > 0) return request.targets
  return profileTargets.filter(target => request.platforms.includes(target.platform))
}

export { targetIdentity }
export const planPath = (directory: string): string => join(directory, 'plan.json')
