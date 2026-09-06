import { mkdtemp, lstat, rmdir } from 'node:fs/promises'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import {
  normalizeCollectArgs,
  normalizePluginConfig,
  type PluginConfig,
  type PluginConfigInput,
} from './config.js'
import {
  buildControllerInvocation,
  ensureRuntime,
  loadRunEvidence,
  parseControllerSummary,
  type RunEvidence,
  type RuntimeDependencies,
} from './runtime.js'
import { runProcess, type ProcessOptions, type ProcessResult } from './process.js'
import { writeWorkbook } from './workbook.js'

declare module '@deepseek-ai/cordis' {
  interface Context {
    dshHomePath(...segments: string[]): string
  }
}

export const name = 'media-missher'
export const inject = ['tools', 'dshHomePath']

export interface MediaToolDependencies {
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
}

function resultSummary(
  request: ReturnType<typeof normalizeCollectArgs>,
  evidence: RunEvidence | undefined,
  fallbackStatus: string,
): string {
  return request.platforms.map((platform) => {
    const collected = evidence?.records[platform].length ?? 0
    const code = evidence?.diagnostics[platform].code ?? fallbackStatus
    return `${platform} ${collected}/${request.count} ${code}`
  }).join('; ')
}

/** Create the model-facing tool with replaceable infrastructure for native smoke tests. */
export function createMediaTool(
  config: PluginConfig,
  dependencies: MediaToolDependencies = {},
): ToolDefinition {
  return {
    name: 'media_missher_collect',
    description: 'Collect authorized creator records with Media@Missher. With no arguments, collect 10 records from each of Bilibili, Xiaohongshu, Douyin, and Weibo sequentially and create a private Excel workbook.',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        platforms: {
          type: 'string',
          description: 'Optional comma-separated subset of bilibili,xhs,douyin,weibo. Default: all four.',
          default: 'bilibili,xhs,douyin,weibo',
        },
        count: {
          type: 'integer',
          description: `Records per selected platform, from 1 through ${config.maxCount}. Default: ${config.defaultCount}.`,
          default: config.defaultCount,
        },
        xhs_comments: {
          type: 'integer',
          description: 'Optional Xiaohongshu comments per record, from 0 through 100. Default: 0.',
          default: config.defaultXhsComments,
        },
        allow_navigation: {
          type: 'boolean',
          description: `Authorize exact-host navigation in the signed-in Media browser. Default: ${config.defaultAllowNavigation}.`,
          default: config.defaultAllowNavigation,
        },
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        required: ['status', 'platforms', 'requestedPerPlatform', 'totalCollected', 'runDirectory', 'manifestPath', 'workbookPath', 'summary'],
        properties: {
          status: { type: 'string' },
          platforms: { type: 'string' },
          requestedPerPlatform: { type: 'integer' },
          totalCollected: { type: 'integer' },
          runDirectory: { type: 'string' },
          manifestPath: { type: 'string' },
          workbookPath: { type: 'string' },
          summary: { type: 'string' },
        },
      },
      render: (_args, rawValue) => {
        const value = rawValue as unknown as ToolValue
        return [{
          type: 'text',
          text: [
            `Media@Missher: ${value.status}`,
            value.summary,
            value.workbookPath ? `Workbook: ${value.workbookPath}` : 'Workbook: not created',
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
      const request = normalizeCollectArgs(rawArgs, config)
      const runtimeProvider = dependencies.ensureRuntime ?? ensureRuntime
      const runtime = await runtimeProvider(config, { signal: exec.signal })
      const invocation = buildControllerInvocation(config, request, runtime)
      const processRunner = dependencies.processRunner ?? runProcess
      // Use the output filesystem clock, matching the Python validator's freshness boundary.
      const marker = await mkdtemp(join(config.outputRoot, '.evidence-start-'))
      let startedAtMs: number
      try {
        startedAtMs = (await lstat(marker)).mtimeMs
      } finally {
        await rmdir(marker)
      }
      const completed = await processRunner(invocation.executable, invocation.args, {
        cwd: invocation.cwd,
        env: invocation.env,
        signal: exec.signal,
        timeoutMs: invocation.timeoutMs,
        maxOutputBytes: 1024 * 1024,
      })
      const controller = parseControllerSummary(completed.stdout)
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
          || request.platforms.some(platform => loaded.platformStatuses[platform] !== 'complete'
            || loaded.records[platform].length < request.count))) {
          controller.status = 'partial'
          evidence.runStatus = 'partial'
          for (const platform of request.platforms) {
            if (evidence.platformStatuses[platform] === 'complete' && evidence.records[platform].length < request.count) {
              evidence.platformStatuses[platform] = 'shortfall'
              evidence.diagnostics[platform] = { kind: 'result', code: 'count-shortfall' }
            }
          }
        }
        if (request.platforms.some(platform => loaded.platformStatuses[platform] === 'risk-stopped')) {
          controller.status = 'risk-stopped'
        }
        if (evidence.totalCollected > 0) {
          workbookPath = await (dependencies.writeWorkbook ?? writeWorkbook)(evidence, request)
        }
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
        summary: resultSummary(request, evidence, controller.status),
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
  registerMediaTool(ctx, input)
}

export default { name, inject, apply }

export type * from './config.js'
export type * from './runtime.js'
