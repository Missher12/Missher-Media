import { lstat, mkdtemp, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import ExcelJS from 'exceljs'
import { afterEach, describe, expect, it } from 'vitest'
import { normalizeCollectArgs, normalizePluginConfig, PLATFORMS } from '../src/config.js'
import type { RunEvidence } from '../src/runtime.js'
import { writeWorkbook } from '../src/workbook.js'

const temporaryRoots: string[] = []

function evidence(runDirectory: string): RunEvidence {
  const records: RunEvidence['records'] = {
    bilibili: [],
    xhs: [],
    douyin: [],
    weibo: [],
  }
  for (const platform of PLATFORMS) {
    records[platform] = Array.from({ length: 10 }, (_, index) => ({
      platform,
      native_id: String(10_000_000_000_000_000n + BigInt(index)),
      title: `${platform}-${index}`,
      formula_text: '=SUM(1,1)',
      nested: { order: index },
    }))
  }
  return {
    runDirectory,
    manifestPath: join(runDirectory, 'manifest.json'),
    runStatus: 'complete',
    records,
    platformStatuses: {
      bilibili: 'complete', xhs: 'complete', douyin: 'complete', weibo: 'complete',
    },
    diagnostics: {
      bilibili: { kind: 'ok', code: 'ok' },
      xhs: { kind: 'ok', code: 'ok' },
      douyin: { kind: 'ok', code: 'ok' },
      weibo: { kind: 'ok', code: 'ok' },
    },
    totalCollected: 40,
  }
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('private inspection workbook', () => {
  it('writes six safe sheets and reopens with all four-platform rows', async () => {
    const runDirectory = await mkdtemp(join(tmpdir(), 'media-workbook-test-'))
    temporaryRoots.push(runDirectory)
    const config = normalizePluginConfig({}, join(runDirectory, 'dsh'), runDirectory)
    const request = normalizeCollectArgs({}, config)

    const workbookPath = await writeWorkbook(evidence(runDirectory), request, {
      fileName: 'inspection.xlsx',
      generatedAt: new Date('2026-08-28T00:00:00.000Z'),
    })

    const metadata = await lstat(workbookPath)
    expect(metadata.mode & 0o777).toBe(0o600)
    expect((await lstat(runDirectory)).mode & 0o777).toBe(0o700)
    expect((await readdir(runDirectory)).some(name => name.endsWith('.tmp'))).toBe(false)

    const reopened = new ExcelJS.Workbook()
    await reopened.xlsx.readFile(workbookPath)
    expect(reopened.worksheets.map(sheet => sheet.name)).toEqual([
      'Summary',
      'All Platforms',
      'Bilibili',
      'Xiaohongshu',
      'Douyin',
      'Weibo',
    ])
    expect(reopened.getWorksheet('Summary')?.rowCount).toBe(5)
    expect(reopened.getWorksheet('All Platforms')?.rowCount).toBe(41)
    for (const name of ['Bilibili', 'Xiaohongshu', 'Douyin', 'Weibo']) {
      const sheet = reopened.getWorksheet(name)
      expect(sheet?.rowCount).toBe(11)
      expect(sheet?.views[0]).toMatchObject({ state: 'frozen', ySplit: 1 })
      expect(sheet?.autoFilter).toBeDefined()
    }
    const combined = reopened.getWorksheet('All Platforms')
    const headers = (combined?.getRow(1).values as unknown[]).map(String)
    const idColumn = headers.indexOf('native_id')
    const formulaColumn = headers.indexOf('formula_text')
    const nestedColumn = headers.indexOf('nested')
    expect(combined?.getRow(2).getCell(idColumn).value).toBe('10000000000000000')
    expect(combined?.getRow(3).getCell(idColumn).value).toBe('10000000000000001')
    expect(combined?.getRow(2).getCell(formulaColumn).value).toBe("'=SUM(1,1)")
    expect(combined?.getRow(2).getCell(nestedColumn).value).toBe('{"order":0}')
  })
  it('rejects numeric identifiers that have already lost precision', async () => {
    const runDirectory = await mkdtemp(join(tmpdir(), 'media-workbook-test-'))
    temporaryRoots.push(runDirectory)
    const fixture = evidence(runDirectory)
    fixture.records.bilibili[0]!.native_id = Number.MAX_SAFE_INTEGER + 1
    const config = normalizePluginConfig({}, join(runDirectory, 'dsh'), runDirectory)
    await expect(writeWorkbook(fixture, normalizeCollectArgs({}, config)))
      .rejects.toThrow('workbook_unsafe_identifier')
    expect(await readdir(runDirectory)).toEqual([])
  })

})
