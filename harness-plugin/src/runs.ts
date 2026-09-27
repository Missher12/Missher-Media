import { join, relative, isAbsolute, sep } from 'node:path'
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import { normalizeExportSelection, type PluginConfig } from './config.js'
import { runProcess } from './process.js'
import { inspectLocalProgress } from './progress.js'

interface RunsValue { status: string; summary: string; artifactPath: string; metadataPath: string }

const EXPORT_ARGUMENTS = ['record_kinds', 'platforms', 'topics', 'targets', 'fields', 'field_groups', 'file_name', 'overwrite'] as const

/** Offline operations intentionally have no collection, navigation or risk-reset action. */
export function createRunsTool(config: PluginConfig): ToolDefinition {
  return {
    name: 'media_missher_runs',
    description: 'List saved private Media@Missher run IDs, export a chosen subset of one saved run, compare metrics at two observation times, inspect the local Xiaohongshu cooldown/risk pause, or use action=progress to read the latest private controller phase/count/timing snapshot during or after collection. Export is always a separate, offline step: it reads only already-saved verified results, can be re-filtered and re-exported as often as needed, and never opens a browser or fills a missing field by collecting again. Choose record kinds (posts, topic_participants, user_profiles), platforms, topics, targets, fields or field groups, and a format (xlsx, csv, json, jsonl, sqlite); a requested field that was never collected is reported back instead of being silently dropped. Progress is last observed state, not guaranteed process liveness; Harness has no native live progress callback. These actions never collect, navigate, retry, or clear a risk pause. Historical export is labelled and does not count as fresh collection. Risk acknowledgement remains an explicit local operator CLI action.',
    parameters: {
      type: 'object', additionalProperties: false, required: ['action'],
      properties: {
        action: { type: 'string', enum: ['list', 'export', 'compare', 'xhs-status', 'progress'] },
        run_id: { type: 'string', description: 'Exact saved run ID for export.' },
        before: { type: 'string', description: 'Exact earlier run ID for comparison.' },
        after: { type: 'string', description: 'Exact later run ID for comparison.' },
        format: { type: 'string', enum: ['xlsx', 'csv', 'json', 'jsonl', 'sqlite'], default: 'xlsx' },
        record_kinds: {
          type: 'array',
          items: { type: 'string', enum: ['posts', 'topic_participants', 'user_profiles'] },
          description: 'Required for a selection export. Posts, topic participation rows, and user homepage rows are different entities and go to different sheets or files.',
        },
        platforms: { type: 'array', items: { type: 'string', enum: ['bilibili', 'xhs', 'douyin', 'weibo', 'x'] }, description: 'Optional platform filter.' },
        topics: { type: 'array', items: { type: 'string' }, description: 'Optional Weibo topic filter.' },
        targets: { type: 'array', items: { type: 'string' }, description: 'Optional exact target identity filter, never a display nickname.' },
        fields: { type: 'array', items: { type: 'string' }, description: 'Optional explicit column list.' },
        field_groups: { type: 'array', items: { type: 'string' }, description: 'Optional named field groups, so the user is not asked about dozens of columns one by one.' },
        file_name: { type: 'string', description: 'Optional plain file name for the export.' },
        overwrite: { type: 'boolean', description: 'Defaults to false: an existing export is never overwritten silently.' },
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: false, required: ['status', 'summary', 'artifactPath', 'metadataPath'], properties: { status: { type: 'string', enum: ['ok', 'failed'] }, summary: { type: 'string' }, artifactPath: { type: 'string' }, metadataPath: { type: 'string' } } },
      render: (_args, value) => [{ type: 'text', text: [(value as unknown as RunsValue).summary, (value as unknown as RunsValue).artifactPath, (value as unknown as RunsValue).metadataPath].filter(Boolean).join('\n') }],
    },
    timeoutMs: 120000,
    presentCall: () => ({ card: 'generic', title: 'Media@Missher saved runs', kind: 'search' }),
    async execute(raw, exec): Promise<RunsValue> {
      if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('runs_arguments_invalid')
      const supplied = raw as Record<string, unknown>
      // The selection may arrive flat (the Harness tool's own schema) or nested
      // as one `export` object (the standalone Agent CLI's shape). Both are
      // validated by the same normalizer.
      const nested = supplied.export
      if (nested !== undefined && (nested === null || typeof nested !== 'object' || Array.isArray(nested))) throw new Error('runs_arguments_invalid')
      const args: Record<string, unknown> = { ...(nested as Record<string, unknown> | undefined), ...supplied }
      delete args.export
      const allowed = ['action', 'run_id', 'before', 'after', 'format', ...EXPORT_ARGUMENTS]
      if (Object.keys(args).some(key => !allowed.includes(key)) || !['list', 'export', 'compare', 'xhs-status', 'progress'].includes(args.action as string)) throw new Error('runs_arguments_invalid')
      if (args.action === 'progress') return inspectLocalProgress(config.outputRoot)
      const id = (value: unknown): string => {
        if (typeof value !== 'string' || !/^run-[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value)) throw new Error('run_id_invalid')
        return value
      }
      const command: string[] = []
      if (args.action === 'export') {
        const format = args.format ?? 'xlsx'
        if (!['xlsx', 'csv', 'json', 'jsonl', 'sqlite'].includes(format as string)) throw new Error('export_format_invalid')
        command.push('export', '--run-id', id(args.run_id), '--format', format as string)
        const selection = normalizeExportSelection({ run_id: id(args.run_id), record_kinds: args.record_kinds, platforms: args.platforms, topics: args.topics, targets: args.targets, fields: args.fields, field_groups: args.field_groups, format: format as string, ...(args.file_name === undefined ? {} : { file_name: args.file_name }), ...(args.overwrite === undefined ? {} : { overwrite: args.overwrite }) })
        command.push('--record-kinds', selection.recordKinds.join(','))
        if (selection.platforms.length) command.push('--platforms', selection.platforms.join(','))
        if (selection.topics.length) command.push('--topics', selection.topics.join(','))
        if (selection.targets.length) command.push('--targets', selection.targets.join(','))
        if (selection.fields.length) command.push('--fields', selection.fields.join(','))
        if (selection.fieldGroups.length) command.push('--field-groups', selection.fieldGroups.join(','))
        if (selection.fileName !== undefined) command.push('--file-name', selection.fileName)
        if (selection.overwrite) command.push('--overwrite')
      } else if (args.action === 'compare') command.push('compare', '--before', id(args.before), '--after', id(args.after))
      else if (args.action === 'list') command.push('list')
      // Existing runtime only: offline history must never install a runtime.
      const python = join(config.runtimeHome, 'venv', 'bin', 'python')
      const script = args.action === 'xhs-status'
        ? join(import.meta.dirname, '..', 'payload', 'runtime', 'scripts', 'xhs_safety.py')
        : join(import.meta.dirname, '..', 'payload', 'media-missher', 'scripts', 'manage_runs.py')
      if (args.action !== 'xhs-status') command.push('--data-root', config.outputRoot)
      const result = await runProcess(python, [script, ...command], { signal: exec.signal, timeoutMs: 60000, maxOutputBytes: 128 * 1024, env: { MEDIA_MISSHER_HOME: config.runtimeHome, PYTHONDONTWRITEBYTECODE: '1' } })
      const value = JSON.parse(result.stdout) as Record<string, unknown>
      if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('history_summary_invalid')
      if (args.action === 'xhs-status') {
        if (typeof value.reason !== 'string' || !['ready', 'xhs-cooldown', 'xhs-risk-latched', 'xhs-safety-busy', 'xhs-safety-state-invalid'].includes(value.reason)) throw new Error('safety_status_invalid')
        const remaining = Number.isSafeInteger(value.remaining_seconds) && (value.remaining_seconds as number) >= 0 ? value.remaining_seconds : 0
        return { status: result.code === 0 ? 'ok' : 'failed', summary: `${value.reason}; remaining ${remaining}s; limit 10 notes, 3 pages, 600s between starts.`, artifactPath: '', metadataPath: '' }
      }
      if (Object.keys(value).sort().join(',') !== 'artifactPath,metadataPath,status,summary' || !['ok', 'failed'].includes(value.status as string) || typeof value.summary !== 'string' || value.summary.length > 32000 || typeof value.artifactPath !== 'string' || typeof value.metadataPath !== 'string') throw new Error('history_summary_invalid')
      for (const candidate of [value.artifactPath, value.metadataPath]) {
        const child = relative(join(config.outputRoot, 'exports'), candidate)
        if (candidate && (child.startsWith(`..${sep}`) || child === '..' || isAbsolute(child))) throw new Error('history_path_invalid')
      }
      return value as unknown as RunsValue
    },
  }
}
