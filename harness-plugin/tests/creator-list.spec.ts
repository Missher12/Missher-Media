import { spawn } from 'node:child_process'
import { crc32, deflateRawSync, inflateRawSync } from 'node:zlib'
import ExcelJS from 'exceljs'
import { describe, expect, it, vi } from 'vitest'
import { buildCreatorTemplates, parseCreatorList } from '../src/creator-list.js'

const headers = 'platform,creator_name,homepage_url'
const xhsId = '5F1234567890abcdef123456'
const xhsUrl = `https://www.xiaohongshu.com/user/profile/${xhsId}`

function csv(...rows: string[]): Buffer {
  return Buffer.from([headers, ...rows].join('\r\n'), 'utf8')
}

async function xlsx(
  rows: ExcelJS.CellValue[][],
  customize?: (workbook: ExcelJS.Workbook) => void,
  streamFiles = false,
): Promise<Buffer> {
  const workbook = new ExcelJS.Workbook()
  const sheet = workbook.addWorksheet('Creators')
  sheet.addRow(headers.split(','))
  for (const row of rows) sheet.addRow(row)
  customize?.(workbook)
  return Buffer.from(await workbook.xlsx.writeBuffer({ zip: { streamFiles } }))
}

function zipDirectory(bytes: Buffer): { end: number; entries: { central: number; local: number; name: string }[] } {
  const end = bytes.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))
  let offset = bytes.readUInt32LE(end + 16)
  const entries = []
  for (let index = 0; index < bytes.readUInt16LE(end + 10); index++) {
    const nameLength = bytes.readUInt16LE(offset + 28)
    entries.push({
      central: offset,
      local: bytes.readUInt32LE(offset + 42),
      name: bytes.subarray(offset + 46, offset + 46 + nameLength).toString('utf8'),
    })
    offset += 46 + nameLength + bytes.readUInt16LE(offset + 30) + bytes.readUInt16LE(offset + 32)
  }
  return { end, entries }
}

/** Rewrite a trusted generated fixture without asking ExcelJS to expand malicious ranges. */
function rewriteXml(bytes: Buffer, part: string, transform: (xml: string) => string, replacementPart?: string): Buffer {
  const directory = zipDirectory(bytes)
  const locals: Buffer[] = []
  const centrals: Buffer[] = []
  let localOffset = 0
  for (const entry of directory.entries) {
    const localLength = 30 + bytes.readUInt16LE(entry.local + 26) + bytes.readUInt16LE(entry.local + 28)
    const centralLength = 46 + bytes.readUInt16LE(entry.central + 28)
      + bytes.readUInt16LE(entry.central + 30) + bytes.readUInt16LE(entry.central + 32)
    let local = Buffer.from(bytes.subarray(entry.local, entry.local + localLength))
    let central = Buffer.from(bytes.subarray(entry.central, entry.central + centralLength))
    const stored = bytes.readUInt16LE(entry.central + 10) === 0
    const original = bytes.subarray(entry.local + localLength, entry.local + localLength + central.readUInt32LE(20))
    let contents = stored ? original : inflateRawSync(original)
    if (entry.name === part) contents = Buffer.from(transform(contents.toString('utf8')))
    if (entry.name === part && replacementPart !== undefined) {
      const name = Buffer.from(replacementPart)
      local = Buffer.concat([local.subarray(0, 30), name, local.subarray(30 + local.readUInt16LE(26))])
      central = Buffer.concat([central.subarray(0, 46), name, central.subarray(46 + central.readUInt16LE(28))])
      local.writeUInt16LE(name.length, 26)
      central.writeUInt16LE(name.length, 28)
    }
    const compressed = stored ? contents : deflateRawSync(contents)
    for (const [header, offset] of [[local, 14], [central, 16]] as const) {
      header.writeUInt32LE(crc32(contents), offset)
      header.writeUInt32LE(compressed.length, offset + 4)
      header.writeUInt32LE(contents.length, offset + 8)
    }
    central.writeUInt32LE(localOffset, 42)
    locals.push(local, compressed)
    centrals.push(central)
    localOffset += local.length + compressed.length
  }
  const end = Buffer.from(bytes.subarray(directory.end))
  end.writeUInt32LE(centrals.reduce((size, central) => size + central.length, 0), 12)
  end.writeUInt32LE(localOffset, 16)
  return Buffer.concat([...locals, ...centrals, end])
}

async function parseInLimitedChild(bytes: Buffer): Promise<{ code: number | null; signal: string | null; output: string }> {
  const moduleUrl = new URL('../src/creator-list.ts', import.meta.url).href
  const source = `
    import { readFileSync } from 'node:fs';
    import { parseCreatorList } from ${JSON.stringify(moduleUrl)};
    process.stdout.write('ready\\n');
    try {
      await parseCreatorList(readFileSync(0), 'xlsx');
      process.stdout.write('accepted');
    } catch (error) {
      const message = error instanceof Error ? error.message : '';
      process.stdout.write(/^creator_list_[a-z_]+(?::row_[0-9]+)?$/.test(message) ? message : 'unexpected_error');
    }
  `
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['--max-old-space-size=128', '--input-type=module', '-e', source], {
      stdio: ['pipe', 'pipe', 'ignore'],
      env: { ...process.env, NODE_OPTIONS: '' },
    })
    let output = ''
    let ready = false
    let timeout = setTimeout(() => child.kill('SIGKILL'), 15_000)
    child.stdout.on('data', (chunk: Buffer) => {
      output += chunk.toString('utf8')
      if (!ready && output.startsWith('ready\n')) {
        ready = true
        output = output.slice('ready\n'.length)
        clearTimeout(timeout)
        // Measure untrusted parsing separately from a loaded host's module startup.
        timeout = setTimeout(() => child.kill('SIGKILL'), 5000)
      }
    })
    child.once('error', error => { clearTimeout(timeout); reject(error) })
    child.once('close', (code, signal) => {
      clearTimeout(timeout)
      resolve({ code, signal, output })
    })
    child.stdin.on('error', () => {})
    child.stdin.end(bytes)
  })
}

describe('offline creator CSV import', () => {
  it('reads BOM, Chinese headers and quoted creator names without retaining URL tokens', async () => {
    const bytes = Buffer.from(`\uFEFF平台,博主名称,主页链接\r\n小红书,"作者, ""甲""",${xhsUrl}?xsec_token=private-value#private-fragment\r\n`)

    expect(await parseCreatorList(bytes, 'csv')).toEqual([{
      platform: 'xhs',
      name: '作者, "甲"',
      homepage: 'https://www.xiaohongshu.com/user/profile/5f1234567890abcdef123456',
      nativeId: '5f1234567890abcdef123456',
    }])
  })

  it.each([
    ['bilibili', 'https://space.bilibili.com/12345678901234567890/', 'https://space.bilibili.com/12345678901234567890', '12345678901234567890'],
    ['B站', 'https://space.bilibili.com/42', 'https://space.bilibili.com/42', '42'],
    ['哔哩哔哩', 'https://space.bilibili.com/43', 'https://space.bilibili.com/43', '43'],
    ['xhs', 'https://xiaohongshu.com/user/profile/5f1234567890abcdef123456', 'https://www.xiaohongshu.com/user/profile/5f1234567890abcdef123456', '5f1234567890abcdef123456'],
    ['抖音', 'https://douyin.com/user/MS4wLjABAAAA_test-safe.secUid/', 'https://www.douyin.com/user/MS4wLjABAAAA_test-safe.secUid', 'MS4wLjABAAAA_test-safe.secUid'],
    ['douyin', 'HTTPS://WWW.DOUYIN.COM:443/user/ABC_def-ghi.jkl', 'https://www.douyin.com/user/ABC_def-ghi.jkl', 'ABC_def-ghi.jkl'],
    ['微博', 'https://www.weibo.com/1234567890', 'https://weibo.com/u/1234567890', '1234567890'],
    ['weibo', 'https://weibo.com/u/1234567890/', 'https://weibo.com/u/1234567890', '1234567890'],
    ['微博', 'https://m.weibo.cn/u/1234567890?token=private', 'https://weibo.com/u/1234567890', '1234567890'],
  ])('normalizes official homepage variant %#', async (platform, homepage, normalized, nativeId) => {
    const result = await parseCreatorList(csv(`${platform},作者,${homepage}`), 'csv')
    expect(result).toEqual([{
      platform: platform === 'B站' || platform === '哔哩哔哩' ? 'bilibili'
        : platform === '抖音' ? 'douyin' : platform === '微博' ? 'weibo' : platform,
      name: '作者', homepage: normalized, nativeId,
    }])
  })

  it.each([
    ['bilibili', 'https://space.bilibili.com/'],
    ['weibo', 'https://weibo.com/'],
    ['weibo', 'https://www.weibo.com/u/'],
    ['weibo', 'https://m.weibo.cn/u/'],
  ])('bounds numeric identity length for %s homepage %s', async (platform, prefix) => {
    const acceptedId = '1'.repeat(32)
    const rejectedId = '1'.repeat(33)
    for (const format of ['csv', 'xlsx'] as const) {
      const acceptedBytes = format === 'csv'
        ? csv(`${platform},作者,${prefix}${acceptedId}`)
        : await xlsx([[platform, '作者', `${prefix}${acceptedId}`]])
      const rejectedBytes = format === 'csv'
        ? csv(`${platform},作者,${prefix}${rejectedId}`)
        : await xlsx([[platform, '作者', `${prefix}${rejectedId}`]])

      expect((await parseCreatorList(acceptedBytes, format))[0]?.nativeId).toBe(acceptedId)
      await expect(parseCreatorList(rejectedBytes, format))
        .rejects.toThrow(new Error('creator_list_homepage_invalid:row_2'))
    }
  })

  it('permits repeated display names and multiple creators on one platform', async () => {
    expect(await parseCreatorList(csv(
      'bilibili,同名,https://space.bilibili.com/1',
      'bilibili,同名,https://space.bilibili.com/2',
      'weibo,同名,https://weibo.com/u/1',
    ), 'csv')).toHaveLength(3)
  })

  it('supports quoted line breaks and all standard record line endings', async () => {
    const bytes = Buffer.from(`${headers}\rbilibili,"作\n者",https://space.bilibili.com/1\nweibo,作者,https://weibo.com/2\r\n`)
    const result = await parseCreatorList(bytes, 'csv')
    expect(result.map(creator => creator.name)).toEqual(['作\n者', '作者'])
  })

  it('rejects a repeated identity after platform and homepage normalization', async () => {
    await expect(parseCreatorList(csv(
      'weibo,作者甲,https://weibo.com/123',
      '微博,作者乙,https://m.weibo.cn/u/123?token=private',
    ), 'csv')).rejects.toThrow(new Error('creator_list_duplicate:row_3'))
  })

  it.each([
    ['xhs', 'http://www.xiaohongshu.com/user/profile/5f1234567890abcdef123456'],
    ['xhs', 'https://xhslink.com/short'],
    ['xhs', 'https://www.xiaohongshu.com/explore/5f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com/user/profile/too-short'],
    ['xhs', 'https://www.xiaohongshu.com/USER/PROFILE/5f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com.evil.example/user/profile/5f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com./user/profile/5f1234567890abcdef123456'],
    ['xhs', 'https://name:private@www.xiaohongshu.com/user/profile/5f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com:444/user/profile/5f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com/explore/../user/profile/5f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com/user/profile/%35f1234567890abcdef123456'],
    ['xhs', 'https://www.xiaohongshu.com/user/profile/5f1234567890abcdef123456/extra'],
    ['bilibili', 'https://www.bilibili.com/video/BV123'],
    ['bilibili', 'https://space.bilibili.com/name'],
    ['bilibili', 'https://weibo.com/u/123'],
    ['douyin', 'https://v.douyin.com/short'],
    ['douyin', 'https://www.douyin.com/video/1234567890'],
    ['douyin', 'https://www.douyin.com/user/%2e%2e'],
    ['weibo', 'https://weibo.com/screen-name'],
    ['weibo', 'https://m.weibo.cn/detail/1234567890'],
    ['weibo', 'https:\\weibo.com\\u\\1234567890'],
    ['weibo', 'https://wei\tbo.com/u/123'],
  ])('rejects unofficial, ambiguous or non-homepage URL %# with a sanitized row error', async (platform, homepage) => {
    await expect(parseCreatorList(csv(`${platform},作者,${homepage}?private=value`), 'csv'))
      .rejects.toThrow(new Error('creator_list_homepage_invalid:row_2'))
  })

  it.each([
    [Buffer.alloc(0), 'creator_list_empty'],
    [Buffer.from(headers), 'creator_list_empty'],
    [csv('', ',,'), 'creator_list_empty'],
    [Buffer.from('平台,creator_name,主页链接\nxhs,作者,' + xhsUrl), 'creator_list_headers_invalid:row_1'],
    [Buffer.from(headers + ',extra\nxhs,作者,' + xhsUrl), 'creator_list_headers_invalid:row_1'],
    [csv('xhs,作者'), 'creator_list_columns_invalid:row_2'],
    [csv('xhs,作者,' + xhsUrl + ',extra'), 'creator_list_columns_invalid:row_2'],
    [csv('xhs,作者,' + xhsUrl, ',,,'), 'creator_list_columns_invalid:row_3'],
    [csv('unknown,作者,' + xhsUrl), 'creator_list_platform_invalid:row_2'],
    [csv('xhs,  ,' + xhsUrl), 'creator_list_name_invalid:row_2'],
    [csv('xhs,作者,'), 'creator_list_homepage_invalid:row_2'],
    [csv('xhs,"unterminated,' + xhsUrl), 'creator_list_csv_invalid:row_2'],
    [csv('xhs,"name"junk,' + xhsUrl), 'creator_list_csv_invalid:row_2'],
    [csv('xhs,un"quoted,' + xhsUrl), 'creator_list_csv_invalid:row_2'],
    [csv('xhs,' + '名'.repeat(101) + ',' + xhsUrl), 'creator_list_name_invalid:row_2'],
    [csv('xhs,作者,' + 'a'.repeat(2049)), 'creator_list_cell_limit:row_2'],
    [Buffer.from([0xff, 0xfe, 0x61]), 'creator_list_encoding_invalid'],
    [Buffer.alloc(2 * 1024 * 1024 + 1), 'creator_list_file_limit'],
  ])('rejects malformed or oversized input %#', async (bytes, error) => {
    await expect(parseCreatorList(bytes, 'csv')).rejects.toThrow(new Error(error))
  })

  it.each(['=1+1', '+SUM(1)', '-1+2', '@SUM(1)', '  =1+1'])('rejects spreadsheet formula prefix %s', async (name) => {
    await expect(parseCreatorList(csv(`xhs,${name},${xhsUrl}`), 'csv'))
      .rejects.toThrow(new Error('creator_list_formula:row_2'))
  })

  it('bounds creator count at 200 rows', async () => {
    const rows = Array.from({ length: 200 }, (_, index) => `bilibili,作者${index},https://space.bilibili.com/${index + 1}`)
    expect(await parseCreatorList(csv(...rows), 'csv')).toHaveLength(200)
    await expect(parseCreatorList(csv(...rows, 'bilibili,额外作者,https://space.bilibili.com/999'), 'csv'))
      .rejects.toThrow(new Error('creator_list_row_limit:row_202'))
  })

  it('counts Unicode names by code point', async () => {
    expect((await parseCreatorList(csv(`xhs,${'😀'.repeat(100)},${xhsUrl}`), 'csv'))[0]?.name)
      .toBe('😀'.repeat(100))
  })
})

describe('bounded offline creator XLSX import', () => {
  it('imports the same rows as CSV and reads Chinese headers', async () => {
    const bytes = await xlsx([
      ['小红书', '作者甲', `${xhsUrl}?xsec_token=private-value`],
      ['抖音', '作者乙', 'https://www.douyin.com/user/MS4wLjABAAAA_test-safe.secUid'],
    ], (workbook) => {
      workbook.worksheets[0]!.getRow(1).values = ['平台', '博主名称', '主页链接']
    })

    expect(await parseCreatorList(bytes, 'xlsx')).toEqual(await parseCreatorList(csv(
      `小红书,作者甲,${xhsUrl}?xsec_token=private-value`,
      '抖音,作者乙,https://www.douyin.com/user/MS4wLjABAAAA_test-safe.secUid',
    ), 'csv'))
  })

  it('supports ordinary Excel hyperlink URLs and rich text names while stripping query tokens', async () => {
    const bytes = await xlsx([[
      '小红书',
      { richText: [{ text: '作者', font: { bold: true } }, { text: '甲' }] },
      { text: xhsUrl, hyperlink: `${xhsUrl}?xsec_token=private-value` },
    ]])
    const [creator] = await parseCreatorList(bytes, 'xlsx')
    expect(creator?.name).toBe('作者甲')
    expect(creator?.homepage).toBe(xhsUrl.toLowerCase())
    expect(JSON.stringify(creator)).not.toContain('private-value')
  })

  it('rejects misleading hyperlink targets even when displayed text is an official homepage', async () => {
    const bytes = await xlsx([[
      'xhs', '作者', { text: xhsUrl, hyperlink: 'https://evil.example/private?token=value' },
    ]])
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_homepage_invalid:row_2'))
  })

  it('rejects different official identities hidden behind a displayed homepage', async () => {
    const bytes = await xlsx([[
      'weibo', '作者', { text: 'https://weibo.com/u/123', hyperlink: 'https://weibo.com/u/456' },
    ]])
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_homepage_invalid:row_2'))
  })

  it.each([
    { formula: '1+1', result: '作者' },
    { formula: 'HYPERLINK("https://private.example/?token=value","作者")', result: '作者' },
    { sharedFormula: 'B1', result: '作者' },
  ])('rejects formula cells instead of trusting cached values %#', async (value) => {
    const bytes = await xlsx([['xhs', value, xhsUrl]], (workbook) => {
      if ('sharedFormula' in value) workbook.worksheets[0]!.getCell('B1').value = { formula: '1+1', result: 'creator_name' }
    })
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(/creator_list_formula:row_[12]$/u)
  })

  it('rejects formulas on ignored hidden worksheets', async () => {
    const bytes = await xlsx([['xhs', '作者', xhsUrl]], (workbook) => {
      workbook.addWorksheet('Hidden', { state: 'hidden' }).getCell('A4').value = { formula: '1+1', result: 2 }
    })
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_formula:row_4'))
  })

  it.each([
    [[['xhs', 123, xhsUrl]], 'creator_list_cell_invalid:row_2'],
    [[['xhs', new Date('2026-01-01'), xhsUrl]], 'creator_list_cell_invalid:row_2'],
    [[['xhs', '作者', xhsUrl, 'unexpected']], 'creator_list_columns_invalid:row_2'],
    [[['xhs', '名'.repeat(101), xhsUrl]], 'creator_list_name_invalid:row_2'],
    [[['xhs', '作者', 'x'.repeat(2049)]], 'creator_list_cell_limit:row_2'],
    [[['xhs', '=1+1', xhsUrl]], 'creator_list_formula:row_2'],
    [[['xhs', '作者', xhsUrl], ['小红书', '重名', xhsUrl.toLowerCase()]], 'creator_list_duplicate:row_3'],
  ] as const)('rejects invalid worksheet contents %#', async (rows, error) => {
    await expect(parseCreatorList(await xlsx(rows.map(row => [...row])), 'xlsx')).rejects.toThrow(new Error(error))
  })

  it('enforces the row limit even for a sparse worksheet', async () => {
    const bytes = await xlsx([['bilibili', '作者', 'https://space.bilibili.com/1']], (workbook) => {
      workbook.worksheets[0]!.getCell('A202').value = 'bilibili'
    })
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_row_limit:row_202'))
  })

  it('imports a valid ZIP that uses streaming data descriptors', async () => {
    const bytes = await xlsx([['bilibili', '作者', 'https://space.bilibili.com/1']], undefined, true)
    expect(await parseCreatorList(bytes, 'xlsx')).toHaveLength(1)
  })

  it.each([
    ['entry count', 'creator_list_zip_limit', (bytes: Buffer) => {
      const { end } = zipDirectory(bytes)
      bytes.writeUInt16LE(129, end + 8)
      bytes.writeUInt16LE(129, end + 10)
    }],
    ['declared expansion', 'creator_list_zip_limit', (bytes: Buffer) => {
      const { entries } = zipDirectory(bytes)
      bytes.writeUInt32LE(8 * 1024 * 1024 + 1, entries[0]!.central + 24)
    }],
    ['total declared expansion', 'creator_list_zip_limit', (bytes: Buffer) => {
      const { entries } = zipDirectory(bytes)
      for (const entry of entries.slice(0, 2)) bytes.writeUInt32LE(5 * 1024 * 1024, entry.central + 24)
    }],
    ['encrypted entry', 'creator_list_zip_unsupported', (bytes: Buffer) => {
      const entry = zipDirectory(bytes).entries[0]!
      bytes.writeUInt16LE(bytes.readUInt16LE(entry.central + 8) | 1, entry.central + 8)
    }],
    ['ZIP64 end record', 'creator_list_zip_unsupported', (bytes: Buffer) => {
      const { end } = zipDirectory(bytes)
      bytes.writeUInt16LE(0xffff, end + 8)
      bytes.writeUInt16LE(0xffff, end + 10)
    }],
    ['ZIP64 entry', 'creator_list_zip_unsupported', (bytes: Buffer) => {
      const entry = zipDirectory(bytes).entries[0]!
      bytes.writeUInt16LE(45, entry.central + 6)
    }],
    ['multiple disks', 'creator_list_zip_unsupported', (bytes: Buffer) => {
      bytes.writeUInt16LE(1, zipDirectory(bytes).end + 4)
    }],
    ['central directory signature', 'creator_list_zip_invalid', (bytes: Buffer) => {
      bytes.writeUInt32LE(0, zipDirectory(bytes).entries[0]!.central)
    }],
    ['local directory mismatch', 'creator_list_zip_invalid', (bytes: Buffer) => {
      const entry = zipDirectory(bytes).entries[0]!
      bytes.writeUInt32LE(999, entry.local + 22)
    }],
    ['overlapping local entries', 'creator_list_zip_invalid', (bytes: Buffer) => {
      const entries = zipDirectory(bytes).entries
      bytes.writeUInt32LE(entries[0]!.local, entries[1]!.central + 42)
    }],
    ['unsafe entry name', 'creator_list_zip_invalid', (bytes: Buffer) => {
      const entry = zipDirectory(bytes).entries.find(value => value.name.startsWith('xl/'))!
      bytes.write('../', entry.central + 46)
      bytes.write('../', entry.local + 30)
    }],
    ['CRC mismatch', 'creator_list_zip_invalid', (bytes: Buffer) => {
      const entry = zipDirectory(bytes).entries.find(value => !value.name.endsWith('/'))!
      const badCrc = (bytes.readUInt32LE(entry.central + 16) ^ 1) >>> 0
      bytes.writeUInt32LE(badCrc, entry.central + 16)
      bytes.writeUInt32LE(badCrc, entry.local + 14)
    }],
    ['forged low expansion size', 'creator_list_zip_invalid', (bytes: Buffer) => {
      const entry = zipDirectory(bytes).entries.find(value => !value.name.endsWith('/'))!
      bytes.writeUInt32LE(1, entry.central + 24)
      bytes.writeUInt32LE(1, entry.local + 22)
    }],
  ] as const)('rejects unsafe ZIP %s before Excel parsing', async (_name, error, modify) => {
    const bytes = await xlsx([['bilibili', '作者', 'https://space.bilibili.com/1']])
    modify(bytes)
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error(error))
  })

  it('rejects duplicate ZIP names', async () => {
    const bytes = await xlsx([['xhs', '作者', xhsUrl]], (workbook) => {
      workbook.addWorksheet('Instructions').getCell('A1').value = '说明'
    })
    const entry = zipDirectory(bytes).entries.find(value => value.name === 'xl/worksheets/sheet2.xml')!
    bytes.write('xl/worksheets/sheet1.xml', entry.central + 46)
    bytes.write('xl/worksheets/sheet1.xml', entry.local + 30)
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_zip_invalid'))
  })

  it('rejects a compressed document whose actual XML exceeds the expansion limit', async () => {
    const bytes = await xlsx([['xhs', 'x'.repeat(9 * 1024 * 1024), xhsUrl]])
    expect(bytes.length).toBeLessThan(2 * 1024 * 1024)
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_zip_limit'))
  })

  it.each([Buffer.from('private malformed file content'), Buffer.from('PK\u0003\u0004')])('rejects malformed XLSX without leaking content %#', async (bytes) => {
    await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_zip_invalid'))
  })
})

describe('empty creator templates', () => {
  it('creates BOM CSV with only the required header', async () => {
    const templates = await buildCreatorTemplates()
    expect(templates.csv.toString('utf8')).toBe(`\uFEFF${headers}\r\n`)
    await expect(parseCreatorList(templates.csv, 'csv')).rejects.toThrow(new Error('creator_list_empty'))
  })

  it('creates an editable empty creator sheet with separate instructions', async () => {
    const templates = await buildCreatorTemplates()
    const workbook = new ExcelJS.Workbook()
    await workbook.xlsx.load(templates.xlsx as unknown as Parameters<typeof workbook.xlsx.load>[0])
    expect(workbook.worksheets.map(sheet => sheet.name)).toEqual(['Creators', 'Instructions'])
    const sheet = workbook.getWorksheet('Creators')!
    expect(sheet.getRow(1).values).toEqual([undefined, 'platform', 'creator_name', 'homepage_url'])
    expect(sheet.rowCount).toBe(1)
    expect(sheet.state).toBe('visible')
    expect(sheet.model.sheetProtection).toBeUndefined()
    expect(workbook.getWorksheet('Instructions')!.rowCount).toBeGreaterThan(1)
    await expect(parseCreatorList(templates.xlsx, 'xlsx')).rejects.toThrow(new Error('creator_list_empty'))

    sheet.addRow(['bilibili', '我的作者', 'https://space.bilibili.com/123'])
    expect(await parseCreatorList(Buffer.from(await workbook.xlsx.writeBuffer()), 'xlsx')).toEqual([{
      platform: 'bilibili', name: '我的作者', homepage: 'https://space.bilibili.com/123', nativeId: '123',
    }])
  })
})

describe('XLSX structure limits before ExcelJS allocation', () => {
  const worksheet = 'xl/worksheets/sheet1.xml'
  const append = (addition: string) => (xml: string) => xml.replace('</worksheet>', `${addition}</worksheet>`)

  it.each([
    ['huge merge', worksheet, append('<mergeCells><mergeCell ref="D1:XFD1048576"/></mergeCells>'), 'creator_list_xlsx_structure_invalid'],
    ['namespaced merge', worksheet, append('<s:mergeCells xmlns:s="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><s:mergeCell ref="D1:XFD1048576"/></s:mergeCells>'), 'creator_list_xlsx_structure_invalid'],
    ['huge column range', worksheet, append('<cols><col min="1" max="4294967294" width="12"/></cols>'), 'creator_list_xlsx_structure_invalid'],
    ['entity encoded column range', worksheet, append('<cols><col min="1" max="&#52;294967294" width="12"/></cols>'), 'creator_list_xlsx_structure_invalid'],
    ['huge row coordinate', worksheet, (xml: string) => xml.replace('<row r="2"', '<row r="4294967294"'), 'creator_list_row_limit:row_202'],
    ['huge cell row coordinate', worksheet, (xml: string) => xml.replace('r="A2"', 'r="A4294967294"'), 'creator_list_row_limit:row_202'],
    ['huge cell column coordinate', worksheet, (xml: string) => xml.replace('r="A2"', 'r="XFD2"'), 'creator_list_columns_invalid:row_2'],
    ['huge row spans', worksheet, (xml: string) => xml.replace('<row r="2" spans="1:3"', '<row r="2" spans="1:4294967294"'), 'creator_list_xlsx_structure_invalid'],
    ['huge workbook sheet ID', 'xl/workbook.xml', (xml: string) => xml.replace('sheetId="1"', 'sheetId="4294967294"'), 'creator_list_xlsx_structure_invalid'],
    ['huge validation range', worksheet, append('<dataValidations><dataValidation type="whole" sqref="A1:XFD1048576"><formula1>1</formula1></dataValidation></dataValidations>'), 'creator_list_xlsx_structure_invalid'],
    ['huge defined name range', 'xl/workbook.xml', (xml: string) => xml.replace('</workbook>', '<definedNames><definedName name="wide">Creators!$A$1:$XFD$1048576</definedName></definedNames></workbook>'), 'creator_list_xlsx_structure_invalid'],
    ['too many physical rows', worksheet, (xml: string) => xml.replace('</sheetData>', `${'<row r="3"/>'.repeat(202)}</sheetData>`), 'creator_list_row_limit:row_202'],
    ['deep XML nesting', worksheet, append(`<extLst>${'<ext>'.repeat(40)}${'</ext>'.repeat(40)}</extLst>`), 'creator_list_xlsx_structure_invalid'],
    ['too many XML nodes', worksheet, append(`<extLst>${'<ext/>'.repeat(20_001)}</extLst>`), 'creator_list_xlsx_structure_invalid'],
    ['too many shared strings', 'xl/sharedStrings.xml', (xml: string) => xml.replace('</sst>', `${'<si><t>x</t></si>'.repeat(4097)}</sst>`), 'creator_list_xlsx_structure_invalid'],
    ['too many styles', 'xl/styles.xml', (xml: string) => xml.replace('</cellXfs>', `${'<xf/>'.repeat(1025)}</cellXfs>`), 'creator_list_xlsx_structure_invalid'],
    ['document type declaration', worksheet, (xml: string) => xml.replace('?>', '?><!DOCTYPE worksheet>'), 'creator_list_xlsx_structure_invalid'],
  ] as const)('rejects %s in a 128 MiB child without crashing', async (_name, part, transform, error) => {
    const original = await xlsx([['bilibili', '作者', 'https://space.bilibili.com/1']])
    const malicious = rewriteXml(original, part, transform)
    expect(malicious.length).toBeLessThan(2 * 1024 * 1024)
    expect(await parseInLimitedChild(malicious)).toEqual({ code: 0, signal: null, output: error })
  }, 25_000)

  it('rejects ZIP path aliases that ExcelJS would normalize after XML preflight', async () => {
    const original = await xlsx([['bilibili', '作者', 'https://space.bilibili.com/1']])
    const bytes = rewriteXml(original, worksheet, xml => xml, 'xl//worksheets/sheet1.xml')
    expect(await parseInLimitedChild(bytes)).toEqual({ code: 0, signal: null, output: 'creator_list_zip_invalid' })
  }, 25_000)

  it('treats text and comments containing merge markup as text, preserving a valid workbook', async () => {
    const original = await xlsx([['bilibili', '作者', 'https://space.bilibili.com/1']])
    const bytes = rewriteXml(original, worksheet, append(
      '<!-- <mergeCells><mergeCell ref="D1:XFD1048576"/></mergeCells> -->'
        + '<extLst><ext><![CDATA[<mergeCells ref="D1:XFD1048576"/>]]></ext></extLst>',
    ))
    expect(await parseInLimitedChild(bytes)).toEqual({ code: 0, signal: null, output: 'accepted' })
  }, 25_000)
})

describe('canonical XLSX part boundary', () => {
  const coreParts = [
    '[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels',
    'xl/sharedStrings.xml', 'xl/styles.xml', 'docProps/app.xml', 'docProps/core.xml',
    'xl/worksheets/sheet1.xml', 'xl/worksheets/_rels/sheet1.xml.rels', 'xl/theme/theme1.xml',
  ]
  const rejectedNames = [
    ...coreParts.flatMap(part => [[part, `prefix/${part}`], [part, `${part}.extra`]]),
    ['xl/worksheets/sheet1.xml', '\uFEFFxl/worksheets/sheet1.xml'],
    ...[
      'xl/drawings/drawing1.xml', 'prefix/xl/drawings/drawing1.xml', 'xl/drawings/drawing1.xml.extra',
      'xl/drawings/_rels/drawing1.xml.rels', 'xl/comments1.xml', 'xl/tables/table1.xml',
      'xl/media/image1.png', 'xl/drawings/vmlDrawing1.vml', 'xl/drawings/vmlDrawing1.vml.extra',
      'prefix/xl/drawings/vmlDrawing1.vml', 'xl/drawings/', 'xl/custom/',
    ].map(part => ['docProps/app.xml', part]),
  ]

  it.each(rejectedNames)('rejects renamed part %s as %s before requesting ExcelJS', async (originalPart, replacementPart) => {
    const homepage = 'https://space.bilibili.com/1'
    const original = await xlsx([['bilibili', '作者', { text: homepage, hyperlink: homepage }]])
    expect(zipDirectory(original).entries.some(entry => entry.name === originalPart)).toBe(true)
    const bytes = rewriteXml(original, originalPart!, xml => xml, replacementPart)
    const excelAccess = vi.spyOn(ExcelJS.Workbook.prototype, 'xlsx', 'get')
    try {
      await expect(parseCreatorList(bytes, 'xlsx')).rejects.toThrow(new Error('creator_list_xlsx_part_unsupported'))
      expect(excelAccess).not.toHaveBeenCalled()
    } finally {
      excelAccess.mockRestore()
    }
  })
})
