import { crc32, inflateRawSync } from 'node:zlib'
import ExcelJS from 'exceljs'
import { SaxesParser } from 'saxes'
import type { Platform } from './config.js'

export interface Creator {
  platform: Platform
  name: string
  homepage: string
  nativeId: string
}

const MAX_FILE_BYTES = 2 * 1024 * 1024
const MAX_CELL_LENGTH = 2048
const MAX_CREATORS = 200
const MAX_ZIP_ENTRIES = 128
const MAX_EXPANDED_BYTES = 8 * 1024 * 1024
const MAX_XML_ELEMENTS = 20_000
const MAX_XML_DEPTH = 32
const MAX_XML_TEXT = 64 * 1024
const MAX_WORKSHEET_COLUMNS = 64
const MAX_SHARED_STRINGS = 4096
const MAX_STYLE_RECORDS = 1024
const STYLE_COLLECTIONS = new Set([
  'numFmts', 'fonts', 'fills', 'borders', 'cellStyleXfs', 'cellXfs', 'cellStyles', 'dxfs', 'tableStyles', 'indexedColors',
])
const STYLE_RECORDS = new Set(['numFmt', 'font', 'fill', 'border', 'xf', 'cellStyle', 'dxf', 'tableStyle', 'rgbColor'])
const HEADERS = ['platform', 'creator_name', 'homepage_url'] as const
const CHINESE_HEADERS = ['平台', '博主名称', '主页链接'] as const
const PLATFORM_NAMES = new Map<string, Platform>([
  ['bilibili', 'bilibili'], ['b站', 'bilibili'], ['哔哩哔哩', 'bilibili'],
  ['xhs', 'xhs'], ['小红书', 'xhs'],
  ['douyin', 'douyin'], ['抖音', 'douyin'],
  ['weibo', 'weibo'], ['微博', 'weibo'],
  ['x', 'x'], ['twitter', 'x'], ['推特', 'x'],
])

interface InputRow {
  number: number
  cells: string[]
  hyperlinks?: Map<number, string>
}

function fail(reason: string, row?: number): never {
  throw new Error(`creator_list_${reason}${row === undefined ? '' : `:row_${row}`}`)
}

function checkedCell(value: string, row: number): string {
  if (value.length > MAX_CELL_LENGTH) fail('cell_limit', row)
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u.test(value)) fail('cell_invalid', row)
  const text = value.trim()
  if (/^[=+@-]/u.test(text)) fail('formula', row)
  return text
}

function csvRows(bytes: Buffer): InputRow[] {
  let text: string
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    fail('encoding_invalid')
  }
  const rows: InputRow[] = []
  let cells: string[] = []
  let cell = ''
  let state: 'unquoted' | 'quoted' | 'closed' = 'unquoted'
  const rowNumber = () => rows.length + 1
  const finishCell = () => {
    cells.push(cell)
    cell = ''
    state = 'unquoted'
  }
  const finishRow = () => {
    if (rowNumber() > MAX_CREATORS + 1) fail('row_limit', rowNumber())
    finishCell()
    rows.push({ number: rowNumber(), cells })
    cells = []
  }
  for (let index = 0; index < text.length; index++) {
    const character = text[index]!
    if (state === 'quoted') {
      if (character === '"') {
        if (text[index + 1] === '"') {
          cell += '"'
          index++
        } else state = 'closed'
      } else cell += character
    } else if (character === ',') {
      finishCell()
      if (cells.length > 3) fail(rows.length === 0 ? 'headers_invalid' : 'columns_invalid', rowNumber())
    } else if (character === '\r' || character === '\n') {
      finishRow()
      if (character === '\r' && text[index + 1] === '\n') index++
    } else if (state === 'closed') {
      fail('csv_invalid', rowNumber())
    } else if (character === '"') {
      if (cell !== '') fail('csv_invalid', rowNumber())
      state = 'quoted'
    } else cell += character
    if (cell.length > MAX_CELL_LENGTH) fail('cell_limit', rowNumber())
  }
  if (state === 'quoted') fail('csv_invalid', rowNumber())
  if (cell !== '' || cells.length > 0 || state === 'closed') finishRow()
  return rows
}

function normalizedHomepage(value: string, platform: Platform, row: number): Pick<Creator, 'homepage' | 'nativeId'> {
  if (/[\s\\]/u.test(value)) fail('homepage_invalid', row)
  const parts = /^https:\/\/([^/?#]+)(\/[^?#]*)?(?:[?#].*)?$/iu.exec(value)
  if (!parts) fail('homepage_invalid', row)
  let url: URL
  try {
    url = new URL(value)
  } catch {
    fail('homepage_invalid', row)
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.port
    || parts[1]!.toLowerCase().replace(/:443$/u, '') !== url.hostname) fail('homepage_invalid', row)
  // Match the original path: URL() would silently normalize dot segments and escapes.
  const path = parts[2] ?? ''
  let nativeId: string | undefined
  let homepage: string | undefined
  if (platform === 'bilibili' && url.hostname === 'space.bilibili.com') {
    nativeId = /^\/(\d{1,32})\/?$/u.exec(path)?.[1]
    homepage = `https://space.bilibili.com/${nativeId}`
  } else if (platform === 'xhs' && ['www.xiaohongshu.com', 'xiaohongshu.com'].includes(url.hostname)) {
    nativeId = /^\/user\/profile\/([a-fA-F\d]{24})\/?$/u.exec(path)?.[1]?.toLowerCase()
    homepage = `https://www.xiaohongshu.com/user/profile/${nativeId}`
  } else if (platform === 'douyin' && ['www.douyin.com', 'douyin.com'].includes(url.hostname)) {
    nativeId = /^\/user\/([A-Za-z0-9._-]{1,256})\/?$/u.exec(path)?.[1]
    if (nativeId === '.' || nativeId === '..') fail('homepage_invalid', row)
    homepage = `https://www.douyin.com/user/${nativeId}`
  } else if (platform === 'weibo') {
    if (['weibo.com', 'www.weibo.com'].includes(url.hostname)) {
      nativeId = /^\/(?:u\/)?(\d{1,32})\/?$/u.exec(path)?.[1]
    } else if (url.hostname === 'm.weibo.cn') nativeId = /^\/u\/(\d{1,32})\/?$/u.exec(path)?.[1]
    homepage = `https://weibo.com/u/${nativeId}`
  } else if (platform === 'x') {
    // A native X profile URL is the handle, and the handle is the stable identity
    // this list can verify. A numeric user ID is not inferred from a nickname.
    if (['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(url.hostname)) {
      nativeId = /^\/([A-Za-z0-9_]{1,15})\/?$/u.exec(path)?.[1]?.toLowerCase()
      if (nativeId && ['home', 'search', 'explore', 'settings', 'login', 'logout', 'i'].includes(nativeId)) fail('homepage_invalid', row)
    }
    homepage = `https://x.com/${nativeId}`
  }
  if (nativeId === undefined || homepage === undefined) fail('homepage_invalid', row)
  return { homepage, nativeId }
}

function creatorsFromRows(rows: InputRow[]): Creator[] {
  if (rows.length === 0) fail('empty')
  const header = rows[0]!.cells.map(value => checkedCell(value, 1))
  if (header.length !== 3
    || ![HEADERS, CHINESE_HEADERS].some(expected => expected.every((value, index) => value === header[index]))) {
    fail('headers_invalid', 1)
  }
  const creators: Creator[] = []
  const identities = new Set<string>()
  for (const row of rows.slice(1)) {
    const cells = row.cells.map(value => checkedCell(value, row.number))
    if (cells.length === 1 && cells[0] === '') continue
    if (cells.length !== 3) fail('columns_invalid', row.number)
    if (cells.every(value => value === '')) continue
    const platform = PLATFORM_NAMES.get(cells[0]!.toLowerCase())
    if (!platform) fail('platform_invalid', row.number)
    const name = cells[1]!
    if (!name || Array.from(name).length > 100) fail('name_invalid', row.number)
    const identity = normalizedHomepage(cells[2]!, platform, row.number)
    const hyperlink = row.hyperlinks?.get(3)
    if (hyperlink !== undefined && normalizedHomepage(hyperlink, platform, row.number).nativeId !== identity.nativeId) {
      fail('homepage_invalid', row.number)
    }
    const key = `${platform}:${identity.nativeId}`
    if (identities.has(key)) fail('duplicate', row.number)
    identities.add(key)
    creators.push({ platform, name, ...identity })
  }
  if (creators.length === 0) fail('empty')
  return creators
}

interface ZipEntry {
  name: Buffer
  part: XlsxPart
  local: number
  version: number
  flags: number
  method: number
  crc: number
  compressed: number
  expanded: number
}

type XlsxXmlPart = 'xml' | 'worksheet' | 'workbook' | 'shared_strings' | 'styles'
type XlsxPart = XlsxXmlPart | 'directory'

const XLSX_CORE_PARTS = new Map<string, XlsxXmlPart>([
  ['[Content_Types].xml', 'xml'], ['_rels/.rels', 'xml'],
  ['xl/workbook.xml', 'workbook'], ['xl/_rels/workbook.xml.rels', 'xml'],
  ['xl/sharedStrings.xml', 'shared_strings'], ['xl/styles.xml', 'styles'],
  ['docProps/app.xml', 'xml'], ['docProps/core.xml', 'xml'],
])
const XLSX_DIRECTORIES = new Set([
  '_rels/', 'xl/', 'xl/_rels/', 'xl/worksheets/', 'xl/worksheets/_rels/', 'xl/theme/', 'docProps/',
])

/** ExcelJS uses unanchored entry matchers; permit only this plain-roster subset. */
function classifyXlsxPart(name: string): XlsxPart {
  const core = XLSX_CORE_PARTS.get(name)
  if (core) return core
  if (XLSX_DIRECTORIES.has(name)) return 'directory'
  const worksheet = /^xl\/worksheets\/sheet([1-9]\d*)\.xml$/u.exec(name)
  if (worksheet && Number(worksheet[1]) <= MAX_ZIP_ENTRIES) return 'worksheet'
  const relationships = /^xl\/worksheets\/_rels\/sheet([1-9]\d*)\.xml\.rels$/u.exec(name)
  if (relationships && Number(relationships[1]) <= MAX_ZIP_ENTRIES) return 'xml'
  if (/^xl\/theme\/[A-Za-z0-9]{1,64}\.xml$/u.test(name)) return 'xml'
  // Embedded objects, tables, cell comments and VML are unnecessary for a roster.
  fail('xlsx_part_unsupported')
}

interface XmlBudget {
  elements: number
  sharedStrings: number
  styles: number
}

function boundedXmlInteger(value: string | undefined, maximum: number, minimum = 0): number {
  if (value === undefined || !/^(?:0|[1-9]\d*)$/u.test(value)) fail('xlsx_structure_invalid')
  const number = Number(value)
  if (!Number.isSafeInteger(number) || number < minimum || number > maximum) fail('xlsx_structure_invalid')
  return number
}

function boundedXmlRow(value: string | undefined): number {
  if (value === undefined || !/^[1-9]\d*$/u.test(value)) fail('xlsx_structure_invalid')
  const row = Number(value)
  if (row > MAX_CREATORS + 1) fail('row_limit', MAX_CREATORS + 2)
  return row
}

function boundedXmlAddress(value: string, cell: boolean): { row: number; column: number } {
  const match = /^\$?([A-Z]{1,3})\$?([1-9]\d*)$/u.exec(value)
  if (!match) fail('xlsx_structure_invalid')
  const row = Number(match[2])
  const column = Array.from(match[1]!).reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0)
  if (row > MAX_CREATORS + 1) {
    if (cell) fail('row_limit', MAX_CREATORS + 2)
    fail('xlsx_structure_invalid')
  }
  if (column > MAX_WORKSHEET_COLUMNS) {
    if (cell) fail('columns_invalid', row)
    fail('xlsx_structure_invalid')
  }
  return { row, column }
}

function boundedXmlRanges(value: string, reportCellLimits = false): void {
  const ranges = value.trim().split(/\s+/u)
  if (ranges.length > MAX_WORKSHEET_COLUMNS) fail('xlsx_structure_invalid')
  for (const range of ranges) {
    const ends = range.split(':')
    if (ends.length > 2) fail('xlsx_structure_invalid')
    const start = boundedXmlAddress(ends[0]!, reportCellLimits)
    const end = boundedXmlAddress(ends[1] ?? ends[0]!, reportCellLimits)
    if (end.row < start.row || end.column < start.column) fail('xlsx_structure_invalid')
  }
}

/** Reject compact XML instructions that allocate unbounded ExcelJS model ranges. */
function checkXlsxXml(contents: Buffer, part: XlsxXmlPart, budget: XmlBudget): void {
  let xml: string
  try {
    xml = new TextDecoder('utf-8', { fatal: true }).decode(contents)
  } catch {
    fail('xlsx_structure_invalid')
  }
  const worksheet = part === 'worksheet'
  const parser = new SaxesParser({ xmlns: true })
  const stack: string[] = []
  let rowCount = 0
  let columnCount = 0
  let cellCount = 0
  let currentRow: number | undefined
  let attributeCount = 0
  parser.on('error', () => fail('xlsx_structure_invalid'))
  parser.on('doctype', () => fail('xlsx_structure_invalid'))
  parser.on('xmldecl', declaration => {
    if (declaration.encoding && !/^utf-8$/iu.test(declaration.encoding)) fail('xlsx_structure_invalid')
  })
  parser.on('opentagstart', tag => {
    attributeCount = 0
    if (tag.name.length > 128 || stack.length >= MAX_XML_DEPTH) fail('xlsx_structure_invalid')
  })
  parser.on('attribute', attribute => {
    attributeCount++
    if (attributeCount > 32 || attribute.name.length > 128 || attribute.value.length > MAX_CELL_LENGTH) {
      fail('xlsx_structure_invalid')
    }
  })
  const checkText = (value: string) => {
    if (value.length > MAX_XML_TEXT) fail('xlsx_structure_invalid')
  }
  parser.on('text', checkText)
  parser.on('cdata', checkText)
  parser.on('opentag', tag => {
    const parent = stack.at(-1)
    if (worksheet && stack.length === 0 && tag.local !== 'worksheet') fail('xlsx_structure_invalid')
    stack.push(tag.local)
    budget.elements++
    if (budget.elements > MAX_XML_ELEMENTS) fail('xlsx_structure_invalid')
    const attribute = (name: string) => tag.attributes[name]?.value
    if (['mergeCells', 'mergeCell', 'definedNames', 'definedName'].includes(tag.local)) fail('xlsx_structure_invalid')
    if (part === 'workbook' && tag.local === 'sheet') {
      boundedXmlInteger(attribute('sheetId'), MAX_ZIP_ENTRIES, 1)
    }
    if (part === 'shared_strings') {
      if (tag.local === 'sst') {
        if (attribute('count') !== undefined) boundedXmlInteger(attribute('count'), MAX_XML_ELEMENTS)
        if (attribute('uniqueCount') !== undefined) boundedXmlInteger(attribute('uniqueCount'), MAX_SHARED_STRINGS)
      }
      if (tag.local === 'si' && ++budget.sharedStrings > MAX_SHARED_STRINGS) fail('xlsx_structure_invalid')
    }
    if (part === 'styles') {
      if (STYLE_COLLECTIONS.has(tag.local) && attribute('count') !== undefined) {
        boundedXmlInteger(attribute('count'), MAX_STYLE_RECORDS)
      }
      if (STYLE_RECORDS.has(tag.local) && ++budget.styles > MAX_STYLE_RECORDS) fail('xlsx_structure_invalid')
    }
    if (!worksheet) return
    if (tag.local === 'row') {
      if (++rowCount > MAX_CREATORS + 1) fail('row_limit', MAX_CREATORS + 2)
      if (parent !== 'sheetData') fail('xlsx_structure_invalid')
      currentRow = boundedXmlRow(attribute('r'))
      cellCount = 0
      const spans = attribute('spans')
      if (spans !== undefined) {
        const limits = spans.split(':')
        if (limits.length !== 2
          || boundedXmlInteger(limits[0], MAX_WORKSHEET_COLUMNS, 1) > boundedXmlInteger(limits[1], MAX_WORKSHEET_COLUMNS, 1)) {
          fail('xlsx_structure_invalid')
        }
      }
    } else if (tag.local === 'c') {
      if (parent !== 'row' || currentRow === undefined) fail('xlsx_structure_invalid')
      if (++cellCount > MAX_WORKSHEET_COLUMNS) fail('columns_invalid', currentRow)
      const address = boundedXmlAddress(attribute('r') ?? '', true)
      if (address.row !== currentRow) fail('xlsx_structure_invalid')
    } else if (tag.local === 'col') {
      if (++columnCount > MAX_WORKSHEET_COLUMNS || parent !== 'cols'
        || boundedXmlInteger(attribute('min'), MAX_WORKSHEET_COLUMNS, 1)
          > boundedXmlInteger(attribute('max'), MAX_WORKSHEET_COLUMNS, 1)) fail('xlsx_structure_invalid')
    } else if (tag.local === 'f') fail('formula', currentRow ?? 1)
    for (const name of ['ref', 'sqref', 'activeCell', 'topLeftCell']) {
      const value = attribute(name)
      if (value !== undefined) boundedXmlRanges(value, tag.local === 'dimension')
    }
  })
  parser.on('closetag', tag => {
    stack.pop()
    if (worksheet && tag.local === 'row') currentRow = undefined
  })
  for (let offset = 0; offset < xml.length; offset += 16_384) parser.write(xml.slice(offset, offset + 16_384))
  parser.close()
}

function checkZipExtra(bytes: Buffer, start: number, end: number): void {
  for (let offset = start; offset < end;) {
    if (offset + 4 > end) fail('zip_invalid')
    const kind = bytes.readUInt16LE(offset)
    const size = bytes.readUInt16LE(offset + 2)
    if (offset + 4 + size > end) fail('zip_invalid')
    // ZIP64, AES and alternate Unicode paths change the interpretation of the entry.
    if ([0x0001, 0x9901, 0x7075].includes(kind)) fail('zip_unsupported')
    offset += 4 + size
  }
}

/** Validate every declared bound before inflating any ZIP entry. */
function checkXlsxZip(bytes: Buffer): void {
  let end = -1
  for (let offset = bytes.length - 22; offset >= Math.max(0, bytes.length - 65_557); offset--) {
    if (bytes.readUInt32LE(offset) === 0x06054b50
      && offset + 22 + bytes.readUInt16LE(offset + 20) === bytes.length) {
      end = offset
      break
    }
  }
  if (end < 0) fail('zip_invalid')
  const count = bytes.readUInt16LE(end + 10)
  const directorySize = bytes.readUInt32LE(end + 12)
  const directoryStart = bytes.readUInt32LE(end + 16)
  if (bytes.readUInt16LE(end + 4) !== 0 || bytes.readUInt16LE(end + 6) !== 0
    || count === 0xffff || bytes.readUInt16LE(end + 8) === 0xffff
    || directorySize === 0xffffffff || directoryStart === 0xffffffff
    || (end >= 20 && bytes.readUInt32LE(end - 20) === 0x07064b50)) fail('zip_unsupported')
  if (count > MAX_ZIP_ENTRIES) fail('zip_limit')
  if (count === 0 || bytes.readUInt16LE(end + 8) !== count || directoryStart + directorySize !== end) fail('zip_invalid')

  const entries: ZipEntry[] = []
  const names = new Set<string>()
  let offset = directoryStart
  let expandedTotal = 0
  for (let index = 0; index < count; index++) {
    if (offset + 46 > end || bytes.readUInt32LE(offset) !== 0x02014b50) fail('zip_invalid')
    const nameLength = bytes.readUInt16LE(offset + 28)
    const extraLength = bytes.readUInt16LE(offset + 30)
    const recordEnd = offset + 46 + nameLength + extraLength + bytes.readUInt16LE(offset + 32)
    if (nameLength === 0 || recordEnd > end) fail('zip_invalid')
    const entry: Omit<ZipEntry, 'part'> = {
      name: bytes.subarray(offset + 46, offset + 46 + nameLength),
      local: bytes.readUInt32LE(offset + 42),
      version: bytes.readUInt16LE(offset + 6),
      flags: bytes.readUInt16LE(offset + 8),
      method: bytes.readUInt16LE(offset + 10),
      crc: bytes.readUInt32LE(offset + 16),
      compressed: bytes.readUInt32LE(offset + 20),
      expanded: bytes.readUInt32LE(offset + 24),
    }
    if (entry.version > 20 || (entry.flags & ~0x080e) !== 0 || ![0, 8].includes(entry.method)
      || bytes.readUInt16LE(offset + 34) !== 0
      || [entry.local, entry.compressed, entry.expanded].includes(0xffffffff)) fail('zip_unsupported')
    expandedTotal += entry.expanded
    if (expandedTotal > MAX_EXPANDED_BYTES) fail('zip_limit')
    checkZipExtra(bytes, offset + 46 + nameLength, offset + 46 + nameLength + extraLength)
    let name: string
    try {
      name = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(entry.name)
    } catch {
      fail('zip_invalid')
    }
    if (/^[\/]|[\\\u0000-\u001f\u007f]/u.test(name) || name.includes('//')
      || name.split('/').some(part => part === '.' || part === '..') || names.has(name)) fail('zip_invalid')
    names.add(name)
    const part = classifyXlsxPart(name)
    if (part === 'directory' && entry.expanded !== 0) fail('zip_invalid')
    entries.push({ ...entry, part })
    offset = recordEnd
  }
  if (offset !== end) fail('zip_invalid')

  // A forged small declaration must not reach ExcelJS's unbounded ZIP inflater.
  // Check local records, bounded actual inflation, CRC and non-overlapping ranges.
  let localEnd = 0
  const xmlBudget: XmlBudget = { elements: 0, sharedStrings: 0, styles: 0 }
  for (const entry of entries.sort((left, right) => left.local - right.local)) {
    const start = entry.local
    if (start !== localEnd || start + 30 > directoryStart || bytes.readUInt32LE(start) !== 0x04034b50) fail('zip_invalid')
    const nameLength = bytes.readUInt16LE(start + 26)
    const extraLength = bytes.readUInt16LE(start + 28)
    const dataStart = start + 30 + nameLength + extraLength
    const dataEnd = dataStart + entry.compressed
    if (dataEnd > directoryStart || bytes.readUInt16LE(start + 4) !== entry.version
      || bytes.readUInt16LE(start + 6) !== entry.flags || bytes.readUInt16LE(start + 8) !== entry.method
      || !bytes.subarray(start + 30, start + 30 + nameLength).equals(entry.name)) fail('zip_invalid')
    checkZipExtra(bytes, start + 30 + nameLength, dataStart)
    const descriptor = (entry.flags & 8) !== 0
    for (const [position, expected] of [[14, entry.crc], [18, entry.compressed], [22, entry.expanded]] as const) {
      const declared = bytes.readUInt32LE(start + position)
      if (declared !== expected && !(descriptor && declared === 0)) fail('zip_invalid')
    }
    localEnd = dataEnd
    if (descriptor) {
      if (localEnd + 12 > directoryStart) fail('zip_invalid')
      if (bytes.readUInt32LE(localEnd) === 0x08074b50) localEnd += 4
      if (localEnd + 12 > directoryStart
        || bytes.readUInt32LE(localEnd) !== entry.crc
        || bytes.readUInt32LE(localEnd + 4) !== entry.compressed
        || bytes.readUInt32LE(localEnd + 8) !== entry.expanded) fail('zip_invalid')
      localEnd += 12
    }
    let contents: Buffer
    try {
      const compressed = bytes.subarray(dataStart, dataEnd)
      contents = entry.method === 0 ? compressed : inflateRawSync(compressed, {
        maxOutputLength: Math.max(1, entry.expanded),
      })
    } catch {
      fail('zip_invalid')
    }
    if (contents.length !== entry.expanded || crc32(contents) !== entry.crc) fail('zip_invalid')
    if (entry.part !== 'directory') checkXlsxXml(contents, entry.part, xmlBudget)
  }
  if (localEnd !== directoryStart) fail('zip_invalid')
}

function xlsxCellText(cell: ExcelJS.Cell, row: number): string {
  const value = cell.value
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return checkedCell(value, row)
  if (typeof value !== 'object') fail('cell_invalid', row)
  if ('formula' in value || 'sharedFormula' in value) fail('formula', row)
  if ('richText' in value) return checkedCell(value.richText.map(part => part.text).join(''), row)
  if ('hyperlink' in value) {
    checkedCell(value.hyperlink, row)
    return checkedCell(value.text, row)
  }
  fail('cell_invalid', row)
}

async function xlsxRows(bytes: Buffer): Promise<InputRow[]> {
  checkXlsxZip(bytes)
  const workbook = new ExcelJS.Workbook()
  try {
    await workbook.xlsx.load(bytes as unknown as Parameters<typeof workbook.xlsx.load>[0], {
      // Only cell values and hyperlink identities are needed. These documented
      // exclusions also prevent irrelevant metadata from expanding model ranges.
      ignoreNodes: [
        'mergeCells', 'cols', 'dimension', 'sheetViews', 'sheetFormatPr', 'autoFilter', 'rowBreaks',
        'dataValidations', 'pageMargins', 'pageSetup', 'headerFooter', 'printOptions', 'picture',
        'drawing', 'sheetProtection', 'tableParts', 'conditionalFormatting', 'extLst',
      ],
    })
  } catch {
    fail('xlsx_invalid')
  }
  const dataSheet = workbook.worksheets.find(sheet => sheet.state === 'visible')
  if (!dataSheet) fail('xlsx_invalid')
  const rows: InputRow[] = []
  for (const sheet of workbook.worksheets) {
    if (sheet.rowCount > MAX_CREATORS + 1) fail('row_limit', MAX_CREATORS + 2)
    sheet.eachRow((source, rowNumber) => {
      const row: InputRow = { number: rowNumber, cells: ['', '', ''], hyperlinks: new Map() }
      source.eachCell((cell, column) => {
        const text = xlsxCellText(cell, rowNumber)
        if (sheet !== dataSheet) return
        if (column > 3) fail(rowNumber === 1 ? 'headers_invalid' : 'columns_invalid', rowNumber)
        if (cell.value && typeof cell.value === 'object' && 'hyperlink' in cell.value) {
          if (column !== 3 || rowNumber === 1) fail('cell_invalid', rowNumber)
          row.hyperlinks!.set(column, cell.value.hyperlink)
        }
        row.cells[column - 1] = text
      })
      if (sheet === dataSheet) rows.push(row)
    })
  }
  if (rows[0]?.number !== 1) fail('headers_invalid', 1)
  return rows
}

/** Import a bounded local list without resolving names or visiting any homepage. */
export async function parseCreatorList(bytes: Buffer, format: 'csv' | 'xlsx'): Promise<Creator[]> {
  if (!Buffer.isBuffer(bytes)) fail('input_invalid')
  if (bytes.length > MAX_FILE_BYTES) fail('file_limit')
  if (format !== 'csv' && format !== 'xlsx') fail('format_invalid')
  return creatorsFromRows(format === 'csv' ? csvRows(bytes) : await xlsxRows(bytes))
}

/** Produce empty editable templates; explanatory text is isolated from import rows. */
export async function buildCreatorTemplates(): Promise<{ csv: Buffer; xlsx: Buffer }> {
  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'Media@Missher'
  const sheet = workbook.addWorksheet('Creators')
  sheet.columns = HEADERS.map((header, index) => ({ header, width: [18, 28, 88][index]! }))
  sheet.getRow(1).font = { bold: true }
  sheet.views = [{ state: 'frozen', ySplit: 1 }]
  for (const column of sheet.columns) column.numFmt = '@'
  const instructions = workbook.addWorksheet('Instructions')
  instructions.columns = [{ header: '填写说明', width: 108 }]
  const lines = [
    '请在 Creators 工作表第 2 行开始填写；模板没有示例博主，空模板不能导入。',
    '保持三列顺序：platform（平台）、creator_name（博主名称）、homepage_url（主页链接）。',
    '也支持完整中文表头：平台、博主名称、主页链接；不要混用中英文表头。',
    '不支持合并单元格或命名范围；请在 Creators 工作表使用普通单元格。',
    '名单文件不支持图片、批注、Excel 表格对象或其他嵌入对象；请使用普通单元格或另存为 CSV。',
    '平台可填写 bilibili / B站 / 哔哩哔哩、xhs / 小红书、douyin / 抖音、weibo / 微博。',
    '博主名称必填，最多 100 个字符；同名可以保留，平台和原生 ID 相同的重复身份会被拒绝。',
    '仅接受 HTTPS 官方个人主页：space.bilibili.com/数字ID；www.xiaohongshu.com/user/profile/24位十六进制ID。',
    '抖音主页为 www.douyin.com/user/secUid；微博主页为 weibo.com/u/数字ID 或 m.weibo.cn/u/数字ID。',
    'X 主页为 x.com/handle；handle 只用于选择，昵称同名不会被当作同一帐号。',
    '请勿填写作品详情页、短链接、用户名代替主页、公式、密码或 Cookie；链接查询参数和片段会被移除。',
    '最多填写 200 行；文件最多 2 MiB；XLSX 展开后总量最多 8 MiB；请将每个单元格内容控制在 2048 个字符内。',
    '可填写多位同平台博主，导入后需要明确选择本次目标；导入不会访问平台或开始采集。',
    'CSV 请保存为 UTF-8 编码并保持相同三列表头；含逗号、引号或换行的内容应使用 CSV 引号规则。',
  ]
  for (const line of lines) instructions.addRow([line])
  instructions.getRow(1).font = { bold: true }
  instructions.eachRow(row => { row.alignment = { wrapText: true, vertical: 'top' } })
  return {
    csv: Buffer.from(`\uFEFF${HEADERS.join(',')}\r\n`, 'utf8'),
    xlsx: Buffer.from(await workbook.xlsx.writeBuffer()),
  }
}
