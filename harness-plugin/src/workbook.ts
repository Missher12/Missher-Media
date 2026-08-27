import { randomBytes } from 'node:crypto'
import {
  chmod,
  link,
  lstat,
  unlink,
} from 'node:fs/promises'
import { basename, join, resolve } from 'node:path'
import ExcelJS, { type Worksheet } from 'exceljs'
import type { CollectArgs, Platform } from './config.js'
import { PLATFORMS } from './config.js'
import type { RunEvidence } from './runtime.js'

export interface WorkbookOptions {
  fileName?: string
  generatedAt?: Date
}

const SHEET_NAMES: Record<Platform, string> = {
  bilibili: 'Bilibili',
  xhs: 'Xiaohongshu',
  douyin: 'Douyin',
  weibo: 'Weibo',
}

const IDENTIFIER_KEY = /(?:^|_)(?:id|uid)$|^(?:bvid|aweme_id|note_id|mblog_id|dynamic_id|native_id)$/iu
const FORMULA_PREFIX = /^[=+\-@]/u

function safeString(value: string): string {
  return FORMULA_PREFIX.test(value) ? `'${value}` : value
}

function cellValue(key: string, value: unknown): string | number | boolean | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'string') return safeString(value)
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('workbook_non_finite_number')
    return IDENTIFIER_KEY.test(key) ? String(value) : value
  }
  if (typeof value === 'boolean') return value
  return safeString(JSON.stringify(value))
}

function columnsFor(records: readonly Record<string, unknown>[], includePlatform: boolean): string[] {
  const columns = includePlatform ? ['platform'] : []
  const seen = new Set(columns)
  for (const record of records) {
    for (const key of Object.keys(record)) {
      if (seen.has(key)) continue
      seen.add(key)
      columns.push(key)
    }
  }
  return columns.length === 0 ? ['platform'] : columns
}

function styleHeader(sheet: Worksheet): void {
  const header = sheet.getRow(1)
  header.font = { bold: true, color: { argb: 'FFFFFFFF' } }
  header.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF385A7C' } }
  header.alignment = { vertical: 'middle', horizontal: 'center' }
  header.height = 22
  sheet.views = [{ state: 'frozen', ySplit: 1 }]
  sheet.autoFilter = {
    from: { row: 1, column: 1 },
    to: { row: 1, column: Math.max(1, sheet.columnCount) },
  }
  for (const column of sheet.columns) column.width = 18
}

function addRecordSheet(
  workbook: ExcelJS.Workbook,
  name: string,
  records: readonly Record<string, unknown>[],
  includePlatform: boolean,
): void {
  const sheet = workbook.addWorksheet(name)
  const columns = columnsFor(records, includePlatform)
  sheet.columns = columns.map(key => ({ header: key, key }))
  for (const record of records) {
    const row = Object.fromEntries(columns.map((key) => {
      const raw = key === 'platform' && record.platform === undefined
        ? name
        : record[key]
      return [key, cellValue(key, raw)]
    }))
    sheet.addRow(row)
  }
  styleHeader(sheet)
}

function safeFileName(requested: string | undefined, generatedAt: Date): string {
  if (requested !== undefined) {
    if (basename(requested) !== requested || !requested.endsWith('.xlsx')) {
      throw new Error('workbook_filename_invalid')
    }
    return requested
  }
  const timestamp = generatedAt.toISOString().replaceAll(/[-:.]/gu, '').replace('Z', 'Z')
  return `Media-Missher-全平台抓取结果-${timestamp}.xlsx`
}

/** Project one validated private run into an atomic, mode-0600 XLSX workbook. */
export async function writeWorkbook(
  evidence: RunEvidence,
  request: CollectArgs,
  options: WorkbookOptions = {},
): Promise<string> {
  const runDirectory = resolve(evidence.runDirectory)
  const directoryMetadata = await lstat(runDirectory)
  if (directoryMetadata.isSymbolicLink() || !directoryMetadata.isDirectory()) {
    throw new Error('workbook_run_directory_invalid')
  }
  if (process.platform !== 'win32') await chmod(runDirectory, 0o700)
  const generatedAt = options.generatedAt ?? new Date()
  if (!Number.isFinite(generatedAt.getTime())) throw new Error('workbook_time_invalid')
  const fileName = safeFileName(options.fileName, generatedAt)
  const destination = join(runDirectory, fileName)
  const temporary = join(
    runDirectory,
    `.${fileName}.${randomBytes(8).toString('hex')}.tmp`,
  )

  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'Media@Missher DeepSeek Harness Plugin'
  workbook.created = generatedAt
  workbook.modified = generatedAt
  const summary = workbook.addWorksheet('Summary')
  summary.columns = [
    { header: 'platform', key: 'platform' },
    { header: 'requested', key: 'requested' },
    { header: 'collected', key: 'collected' },
    { header: 'status', key: 'status' },
    { header: 'diagnostic_kind', key: 'diagnostic_kind' },
    { header: 'diagnostic_code', key: 'diagnostic_code' },
    { header: 'run_status', key: 'run_status' },
    { header: 'generated_at', key: 'generated_at' },
  ]
  const selected = new Set(request.platforms)
  for (const platform of PLATFORMS) {
    summary.addRow({
      platform,
      requested: selected.has(platform) ? request.count : 0,
      collected: evidence.records[platform].length,
      status: evidence.platformStatuses[platform],
      diagnostic_kind: evidence.diagnostics[platform].kind,
      diagnostic_code: evidence.diagnostics[platform].code,
      run_status: evidence.runStatus,
      generated_at: generatedAt.toISOString(),
    })
  }
  styleHeader(summary)

  const combined = PLATFORMS.flatMap(platform => evidence.records[platform].map(record => ({
    ...record,
    platform,
  })))
  addRecordSheet(workbook, 'All Platforms', combined, true)
  for (const platform of PLATFORMS) {
    addRecordSheet(workbook, SHEET_NAMES[platform], evidence.records[platform], false)
  }

  try {
    await workbook.xlsx.writeFile(temporary)
    if (process.platform !== 'win32') await chmod(temporary, 0o600)
    await link(temporary, destination)
    await unlink(temporary)
    if (process.platform !== 'win32') await chmod(destination, 0o600)
    return resolve(destination)
  } finally {
    await unlink(temporary).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error
    })
  }
}
