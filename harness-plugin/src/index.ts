import { mkdtemp, lstat, rmdir, unlink } from 'node:fs/promises'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import {
  normalizeCollectArgs,
  normalizePluginConfig,
  PLATFORMS,
  type PluginConfig,
  type PluginConfigInput,
} from './config.js'
import {
  buildControllerInvocation,
  ensureRuntime,
  loadRunEvidence,
  parseControllerSummary,
  prepareOutputRoot,
  type RunEvidence,
  type RuntimeDependencies,
} from './runtime.js'
import { runProcess, parseProgressEvent, type ProcessOptions, type ProcessResult, type ProgressEvent } from './process.js'
import { writeWorkbook } from './workbook.js'
import { createRunsTool } from './runs.js'
import { createLocalProgress, formatPhaseTimings } from './progress.js'
import { createSetupTool } from './setup.js'
import { readProfileSnapshot, parseProfileSnapshot, writePrivateFile } from './private-config.js'
import { buildCollectionPlan, resolveTargets, type CollectionPlan } from './plan.js'
import { MEDIA_AGENT_GUIDANCE } from './agent-guidance.js'
import { checkBrowser, isWsl } from './browser-setup.js'

declare module '@deepseek-ai/cordis' {
  interface Context {
    dshHomePath(...segments: string[]): string
  }
}

export const name = 'media-missher'
export const inject = ['tools', 'dshHomePath']

export interface MediaToolDependencies {
  onProgress?: (event: ProgressEvent) => void
  wsl?: boolean
  checkBrowser?: typeof checkBrowser
  ensureRuntime?: (
    config: PluginConfig,
    dependencies: RuntimeDependencies,
  ) => ReturnType<typeof ensureRuntime>
  processRunner?: (
    executable: string,
    args: readonly string[],
    options?: ProcessOptions,
  ) => Promise<ProcessResult>
  loadRunEvidence?: typeof loadRunEvidence
  writeWorkbook?: typeof writeWorkbook
}

interface ToolValue {
  status: string
  platforms: string
  requestedPerPlatform: number
  totalCollected: number
  runDirectory: string
  manifestPath: string
  workbookPath: string
  summary: string
  missingFields?: string[]
}

/** A pre-execution failure that still reports the resolved request shape. */
function failureValue(
  request: { platformText?: string; count?: number } | ReturnType<typeof normalizeCollectArgs>,
  code: string,
): ToolValue {
  const platformText = (request as { platformText?: string }).platformText ?? ''
  const count = (request as { count?: number }).count ?? 0
  const needsInput = /^(?:profile_targets_missing|plan_targets_missing|target_identity_missing|target_keyword_missing|target_topic_missing)(?::|$)/.test(code)
  const missingFields = code === 'target_keyword_missing' ? ['keyword'] : code === 'target_topic_missing' ? ['topic'] : platformText ? ['targets'] : ['platforms', 'targets']
  return {
    status: needsInput ? 'needs-input' : 'preflight-failed',
    ...(needsInput ? { missingFields } : {}),
    platforms: platformText,
    requestedPerPlatform: count,
    totalCollected: 0,
    runDirectory: '',
    manifestPath: '',
    workbookPath: '',
    summary: needsInput ? `${code}; 请补充尚未提供的平台和精确帐号主页、UID、关键词或微博话题；已有明确目标无需重新导入名单。` : code,
  }
}

function resultSummary(
  request: ReturnType<typeof normalizeCollectArgs>,
  evidence: RunEvidence | undefined,
  fallbackStatus: string,
  controller?: ReturnType<typeof parseControllerSummary>,
): string {
  const counts = request.platforms.map((platform) => {
    const collected = evidence?.records[platform].length ?? 0
    const code = controller?.preconditions?.[platform] ?? controller?.preflightCode ?? evidence?.diagnostics[platform].code ?? fallbackStatus
    const prior = controller?.continuation?.priorCounts[platform]
    return prior === undefined
      ? `${platform} ${collected}/${request.count} ${code}`
      : `${platform} historical ${prior} + new ${collected}/${request.count} ${code}`
  }).join('; ')
  const version = controller?.runtimeVersion
  const preflight = version === undefined ? '' : `runtime current ${version.current ?? 'unrecognized'}; required ${version.required}`
  const timings = controller?.phaseTimings === undefined ? '' : `Controller/runtime timings: ${formatPhaseTimings(controller.phaseTimings)}`
  const storage = controller?.phaseTimingsPersisted === false ? 'Timing values returned; timing file unavailable.' : ''
  return [counts, preflight, timings, storage].filter(Boolean).join('\n')
}

/** Create the model-facing tool with replaceable infrastructure for native smoke tests. */
export function createMediaTool(
  config: PluginConfig,
  dependencies: MediaToolDependencies = {},
): ToolDefinition {
  return {
    name: 'media_missher_collect',
    description: 'Collect authorized records with Media@Missher from an existing signed-in browser and private profile. Targets are explicit: a platform may carry several accounts, and each target has a mode (creator, search, or a Weibo topic). Default: fixed 10 per target, sequential, private evidence; export is a separate user-selected step. count_mode=best_effort collects as much as is actually available inside --run_deadline, bounded by a finite per-platform batch budget and the Xiaohongshu 10-notes/3-pages/600-seconds policy; a budget pause is not "collection finished". Chrome CDP is the only backend and works independently of the Agent host. Retired Computer Use requests return backend-retired-computer-use. BrowserSkill is retired. Never automatically retry, resume, clear a risk pause or switch browser/account after a stop. Selecting a target never switches the logged-in account. Explicit resume_run uses the original request and profile, skips accepted historical IDs, and preserves historical and newly accepted evidence. Use media_missher_runs action=progress for the latest local phase/count/timing snapshot; export afterwards with media_missher_runs action=export. Harness has no native live progress callback. No comment bodies, media download, browser installation, login bypass or credential arguments.',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        platforms: {
          type: 'string',
          description: 'Optional comma-separated subset of bilibili,xhs,douyin,weibo,x. When omitted, use the active configured targets. A blank device must import and activate its creator list first.',
        },
        targets: {
          type: 'array',
          description: 'Explicit collection targets. Omit only when the saved profile already describes every account to collect for the selected platforms.',
          items: {
            type: 'object',
            additionalProperties: false,
            required: ['platform', 'mode'],
            properties: {
              platform: { type: 'string', enum: [...PLATFORMS] },
              mode: { type: 'string', enum: ['creator', 'search', 'topic'] },
              label: { type: 'string', description: 'Display label only. A nickname never identifies an account.' },
              uid: { type: 'string', description: 'Verified native account id (for example a Weibo UID).' },
              handle: { type: 'string', description: 'Native handle, used by X. Not interchangeable with a numeric user id.' },
              homepage: { type: 'string', description: 'Canonical HTTPS official homepage.' },
              keyword: { type: 'string', description: 'Required for mode=search.' },
              topic: { type: 'string', description: 'Required for mode=topic. Weibo only.' },
              topic_kind: { type: 'string', enum: ['topic', 'super'], description: 'A plain #topic# and a 超话 are different pages; a super topic is reported as unsupported instead of being faked as a keyword search.' },
              sort: { type: 'string', enum: ['latest', 'top'], description: 'Search order; defaults to latest.' },
            },
          },
        },
        count: {
          type: 'integer',
          description: `Records per target in fixed mode, from 1 through ${config.maxCount}. Default: ${config.defaultCount}. Ignored as a cap in best_effort mode.`,
          default: config.defaultCount,
        },
        count_mode: {
          type: 'string',
          enum: ['fixed', 'best_effort'],
          description: "fixed collects the requested count per target. best_effort keeps paginating inside the run deadline and the finite per-platform batch budget; it is bounded, cancellable and resumable, and reports each real stop reason.",
          default: config.defaultCountMode,
        },
        backend: {
          type: 'string',
          enum: ['cdp'],
          description: 'Chrome CDP is the only supported backend. Connect to the existing signed-in Chrome endpoint. Retired backend requests are refused before collection.',
          default: config.defaultBackend,
        },
        run_deadline_seconds: {
          type: 'number',
          description: `Total authorized run window for best_effort, in seconds. Default: ${config.defaultRunDeadlineSeconds}. The run keeps its verified prefix and a resumable point when it expires.`,
          default: config.defaultRunDeadlineSeconds,
        },
        xhs_comments: {
          type: 'integer',
          description: 'Optional Xiaohongshu comments per record, from 0 through 100. Default: 0.',
          default: config.defaultXhsComments,
        },
        allow_navigation: {
          type: 'boolean',
          description: `Authorize exact-host navigation in the existing signed-in Media browser for this call. Default: ${config.defaultAllowNavigation}; omit or use false for passive collection.`,
          default: config.defaultAllowNavigation,
        },
        resume_run: {
          type: 'string',
          description: 'Only with explicit user continuation intent: exact prior run ID, using the same original targets/count/profile/backend. Risk-stopped runs cannot be continued. No automatic continuation.',
        },
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        required: ['status', 'platforms', 'requestedPerPlatform', 'totalCollected', 'runDirectory', 'manifestPath', 'workbookPath', 'summary'],
        properties: {
          status: {
            type: 'string',
            enum: ['success', 'partial', 'risk-stopped', 'needs-input', 'preflight-failed', 'failed'],
          },
          platforms: { type: 'string' },
          requestedPerPlatform: { type: 'integer' },
          totalCollected: { type: 'integer' },
          runDirectory: { type: 'string' },
          manifestPath: { type: 'string' },
          workbookPath: { type: 'string' },
          summary: { type: 'string' },
          missingFields: { type: 'array', items: { type: 'string' } },
        },
      },
      render: (_args, rawValue) => {
        const value = rawValue as unknown as ToolValue
        return [{
          type: 'text',
          text: [
            `Media@Missher: ${value.status}`,
            value.summary,
            value.workbookPath ? `Workbook: ${value.workbookPath}` : '选择平台、帐号、记录类别、字段和格式后，可离线导出。',
            value.runDirectory ? `Run: ${value.runDirectory}` : 'Run: not created',
          ].join('\n'),
        }]
      },
    },
    timeoutMs: Math.ceil((config.executionTimeoutSeconds + 60) * 1000),
    presentCall: () => ({
      card: 'generic',
      title: 'Media@Missher collection',
      kind: 'search',
    }),
    async execute(rawArgs, exec): Promise<ToolValue> {
      // Validate input shape/budgets now; platform-dependent options use the resolved selection below.
      const supplied = rawArgs as Record<string, unknown>
      let profile
      try { profile = await readProfileSnapshot(config.profilePath) } catch {
        return failureValue(normalizeCollectArgs({ platforms: config.defaultPlatforms.join(',') }, { ...config, defaultPlatforms: [...PLATFORMS] }), 'profile_invalid')
      }
      if (profile === undefined || profile.available.length === 0) {
        if (!Array.isArray(supplied?.targets) || supplied.targets.length === 0) {
          return failureValue({ platformText: typeof supplied?.platforms === 'string' ? supplied.platforms : '' }, 'profile_targets_missing')
        }
        try {
          const normalized = normalizeCollectArgs(supplied, { ...config, defaultPlatforms: [...PLATFORMS] })
          profile = parseProfileSnapshot(Buffer.from(JSON.stringify({ ...profile?.value, targets: normalized.targets, active_platforms: normalized.platforms })))
        } catch (error) {
          return failureValue({ platformText: '', count: 0 }, (error as Error).message || 'target_invalid')
        }
      }
      // When the call names no platform, the saved activation decides. An
      // explicit per-call platform, or a per-call target list, always wins.
      const effective = { ...supplied }
      if (effective.platforms === undefined && effective.targets === undefined) {
        // An explicitly saved activation is authoritative. A legacy profile with
        // no activation keeps its historical meaning: the plugin's own default
        // platform list, narrowed to what the profile actually has.
        const selected = Object.hasOwn(profile.value, 'active_platforms')
          ? profile.active
          : config.defaultPlatforms.filter(platform => profile.available.includes(platform))
        if (selected.length > 0) effective.platforms = selected.join(',')
      }
      let request: ReturnType<typeof normalizeCollectArgs>
      try {
        request = normalizeCollectArgs(
          effective,
          { ...config, defaultPlatforms: [...PLATFORMS] },
          { ...(profile.backend === undefined ? {} : { backend: profile.backend }), targets: profile.targets },
        )
      } catch (error) {
        return failureValue(
          { platformText: '', count: 0 } as unknown as ReturnType<typeof normalizeCollectArgs>,
          (error as Error).message || 'arguments_invalid',
        )
      }
      const needsSetup = (code: string): ToolValue => failureValue(request, code)
      // A saved target is only usable for a platform the profile actually has,
      // so an explicit request for a platform without a saved account is still
      // reported as missing setup instead of being silently dropped.
      const usable = profile.targets.filter(target => profile.available.includes(target.platform))
      // Several accounts on one platform are a first-class selection: the plan
      // carries one frozen target per account instead of one per platform.
      const resolved = resolveTargets(request, usable)
      if (resolved.length === 0) return needsSetup('plan_targets_missing')
      const resolvedPlatforms = new Set(resolved.map(target => target.platform))
      const missing = request.platforms.filter(platform => !resolvedPlatforms.has(platform))
      if (missing.length > 0) return needsSetup(`profile_targets_missing:${missing.join(',')}`)
      request = { ...request, targets: resolved }
      const plan: CollectionPlan = buildCollectionPlan(request)
      const runtimeProvider = dependencies.ensureRuntime ?? ensureRuntime
      if (request.backend === 'cdp' && (dependencies.wsl ?? isWsl())) {
        const browser = await (dependencies.checkBrowser ?? checkBrowser)(config, profile.value, request.platforms, exec.signal, { wsl: true })
        if (browser.status !== 'ok' || browser.browserIdentity !== 'ai-dedicated') return {
          status: 'preflight-failed', platforms: request.platformText, requestedPerPlatform: request.count,
          totalCollected: 0, runDirectory: '', manifestPath: '', workbookPath: '', summary: browser.summary,
        }
      }
      const processRunner = dependencies.processRunner ?? runProcess
      // Bind this invocation to its reviewed targets even if a later setup call activates another list.
      await prepareOutputRoot(config.outputRoot)
      const localProgress = await createLocalProgress(config.outputRoot)
      const marker = await mkdtemp(join(config.outputRoot, '.evidence-start-'))
      const snapshotPath = join(marker, 'profile.json')
      const planPath = join(marker, 'plan.json')
      let startedAtMs: number
      let completed: ProcessResult
      try {
        startedAtMs = (await lstat(marker)).mtimeMs
        await writePrivateFile(snapshotPath, profile.bytes)
        await writePrivateFile(planPath, `${JSON.stringify(plan, null, 2)}\n`)
        const runtime = await runtimeProvider({ ...config, profilePath: snapshotPath }, { signal: exec.signal })
        const invocation = buildControllerInvocation({ ...config, profilePath: snapshotPath }, request, runtime, planPath)
        completed = await processRunner(invocation.executable, invocation.args, {
          cwd: invocation.cwd,
          env: invocation.env,
          signal: exec.signal,
          timeoutMs: invocation.timeoutMs,
          maxOutputBytes: 1024 * 1024,
          onProgress: event => {
            localProgress.receive(event)
            const safe = parseProgressEvent(event)
            if (safe && !exec.signal.aborted) try { dependencies.onProgress?.(safe) } catch { /* Optional observers never interrupt collection. */ }
          },
        })
        await localProgress.finish(completed.code === 0 ? 'completed' : 'failed')
      } catch (error) {
        await localProgress.finish(exec.signal.aborted ? 'cancelled' : 'failed')
        throw error
      } finally {
        await unlink(planPath).catch(error => { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error })
        await unlink(snapshotPath).catch(error => { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error })
        await rmdir(marker)
      }
      const controller = parseControllerSummary(completed.stdout)
      if (controller.continuation !== undefined && request.resumeRun === undefined) throw new Error('unexpected_continuation')
      const requestedNow = (platform: typeof request.platforms[number]) => Math.max(0, request.count - (controller.continuation?.priorCounts[platform] ?? 0))
      if (controller.continuation !== undefined && (JSON.stringify(Object.keys(controller.continuation.requestedCounts).sort()) !== JSON.stringify([...request.platforms].sort()) || request.platforms.some(platform => controller.continuation?.requestedCounts[platform] !== request.count))) throw new Error('continuation_request_mismatch')
      if (completed.code !== 0 && controller.status === 'success') {
        throw new Error('controller_exit_inconsistent')
      }

      let evidence: RunEvidence | undefined
      let workbookPath = ''
      if (controller.runDirectory !== null && controller.manifestPath !== null) {
        evidence = await (dependencies.loadRunEvidence ?? loadRunEvidence)(controller, config, { startedAtMs })
        for (const platform of Object.keys(evidence.records) as (keyof RunEvidence['records'])[]) {
          if (!request.platforms.includes(platform) && (
            evidence.records[platform].length > 0 || evidence.platformStatuses[platform] !== 'not-selected'
          )) throw new Error('controller_platform_mismatch')
        }
        const loaded = evidence
        // A controller success must also satisfy the independently loaded projection.
        if (controller.status === 'success' && (evidence.runStatus !== 'complete'
          || (evidence.backend === undefined && request.platforms.some(platform => requestedNow(platform) > 0 && (loaded.platformStatuses[platform] !== 'complete'
            || loaded.records[platform].length < requestedNow(platform)))))) {
          controller.status = 'partial'
          evidence.runStatus = 'partial'
          for (const platform of request.platforms) {
            if (evidence.platformStatuses[platform] === 'complete' && evidence.records[platform].length < requestedNow(platform)) {
              evidence.platformStatuses[platform] = 'shortfall'
              evidence.diagnostics[platform] = { kind: 'result', code: 'count-shortfall' }
            }
          }
        }
        if (request.platforms.some(platform => loaded.platformStatuses[platform] === 'risk-stopped')) {
          controller.status = 'risk-stopped'
        }
        // Collection persists private evidence. Export is an explicit offline action.

      } else if (controller.status === 'success') {
        throw new Error('controller_evidence_missing')
      }

      return {
        status: controller.status,
        platforms: request.platformText,
        requestedPerPlatform: request.count,
        totalCollected: evidence?.totalCollected ?? 0,
        runDirectory: controller.runDirectory ?? '',
        manifestPath: evidence?.manifestPath ?? '',
        workbookPath,
        summary: [resultSummary(request, evidence, controller.status, controller), localProgress.available() ? '' : 'local-progress-unavailable'].filter(Boolean).join('\n'),
      }
    },
  }
}

/** Register the Bundle's one Agent tool and return its exact disposer. */
export function registerMediaTool(
  ctx: Context,
  input: PluginConfigInput = {},
  dependencies: MediaToolDependencies = {},
): () => void {
  const config = normalizePluginConfig(input, ctx.dshHomePath())
  return ctx.tools.register(createMediaTool(config, dependencies))
}

/** Mount Media@Missher into the current Harness profile. */
export function apply(ctx: Context, input: PluginConfigInput = {}): void {
  const systemPrompt = ctx.get?.('systemPrompt') as {
    section?: (value: { name: string; order: number; text: string }) => unknown
  } | undefined
  if (typeof systemPrompt?.section === 'function') {
    systemPrompt.section({ name: 'media-missher:agent-guidance', order: 146, text: MEDIA_AGENT_GUIDANCE })
  }
  registerMediaTool(ctx, input)
  ctx.tools.register(createRunsTool(normalizePluginConfig(input, ctx.dshHomePath())))
  ctx.tools.register(createSetupTool(normalizePluginConfig(input, ctx.dshHomePath())))
}

export default { name, inject, apply }

export type * from './config.js'
export type * from './runtime.js'
export { createSetupTool } from './setup.js'
export { createRunsTool } from './runs.js'
export { normalizePluginConfig } from './config.js'
