import type { Context } from '@deepseek-ai/cordis'
import { defineTool, type ToolDefinition } from '@deepseek-ai/dsh-tools'
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
  return defineTool({
    name: 'media_missher_collect',
    description: 'Collect authorized creator records with Media@Missher. With no arguments, collect 10 records from each of Bilibili, Xiaohongshu, Douyin, and Weibo sequentially and create a private Excel workbook.',
    parameters: {
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
        description: 'Authorize exact-host navigation in the signed-in Media browser. Default: true.',
        default: config.defaultAllowNavigation,
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          status: { type: 'string', required: true },
          platforms: { type: 'string', required: true },
          requestedPerPlatform: { type: 'integer', required: true },
          totalCollected: { type: 'integer', required: true },
          runDirectory: { type: 'string', required: true },
          manifestPath: { type: 'string', required: true },
          workbookPath: { type: 'string', required: true },
          summary: { type: 'string', required: true },
        },
      },
      render: (_args, value) => [{
        type: 'text',
        text: [
          `Media@Missher: ${value.status}`,
          value.summary,
          value.workbookPath ? `Workbook: ${value.workbookPath}` : 'Workbook: not created',
          value.runDirectory ? `Run: ${value.runDirectory}` : 'Run: not created',
        ].join('\n'),
      }],
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
        evidence = await (dependencies.loadRunEvidence ?? loadRunEvidence)(controller, config)
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
  })
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
