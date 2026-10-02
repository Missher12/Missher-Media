// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { gunzipSync } from 'node:zlib'

const MAX_ARCHIVE = 16 * 1024 * 1024
const MAX_EXPANDED = 48 * 1024 * 1024
export const REQUIRED_PAYLOAD = [
  'payload/.media-missher-source-tree', 'payload/VERSION',
  ...['manage_runs', 'media_missher_adapter', 'media_missher_history', 'media_missher_progress', 'preflight', 'run_collection', 'validate_run'].map(name => `payload/media-missher/scripts/${name}.py`),
  ...['LICENSE', 'THIRD_PARTY_NOTICES.md', '__init__.py', 'requirements.lock'].map(name => `payload/runtime/${name}`),
  ...['__init__', 'browser', 'cli', 'continuation', 'detail_open', 'models', 'progress', 'safety', 'screenshots', 'shared_safety', 'storage', 'xhs_policy', 'backends', 'batch_policy', 'best_effort', 'capabilities', 'contracts', 'exporting', 'extraction', 'page_collection', 'plan_runner', 'batch_journal', 'page_risk', 'collection_pacing', 'safety_control', 'observations'].map(name => `payload/runtime/media_missher_runtime/${name}.py`),
  ...['__init__', '_xhs_detail_enrichment', 'bilibili', 'douyin', 'weibo', 'xhs', 'weibo_topic', 'x'].map(name => `payload/runtime/media_missher_runtime/platforms/${name}.py`),
  ...['scrape_all', 'scrape_bilibili', 'scrape_douyin', 'scrape_weibo', 'scrape_xhs', 'xhs_safety'].map(name => `payload/runtime/scripts/${name}.py`),
  ...['install_media_missher', 'scan_active_residuals'].map(name => `payload/tools/${name}.py`),
]
const fileAllowed = name => ['package.json', 'README.md', 'AGENT_INSTALL.md', 'DATA_CAPABILITIES.md', 'QUICKSTART.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'lib/index.js', 'bin/media-missher.mjs', 'src/skills.mjs', 'src/platform.mjs', 'src/targets.mjs', 'src/capabilities.mjs', 'skill/SKILL.md'].includes(name)
  || REQUIRED_PAYLOAD.includes(name)

/** Read only bounded, canonical regular-file npm tar members. Never extract untrusted paths. */
export function inspectArchive(compressed) {
  if (compressed.length > MAX_ARCHIVE) throw new Error('archive_too_large')
  let tar
  try { tar = gunzipSync(compressed, { maxOutputLength: MAX_EXPANDED }) }
  catch { throw new Error('archive_invalid') }
  const files = new Map()
  const text = value => value.toString('utf8').replace(/\0.*$/s, '')
  let offset = 0
  for (; offset + 512 <= tar.length; ) {
    const header = tar.subarray(offset, offset + 512)
    if (header.every(byte => byte === 0)) break
    let sum = 0
    for (let n = 0; n < 512; n++) sum += n >= 148 && n < 156 ? 32 : header[n]
    if (sum !== Number.parseInt(text(header.subarray(148, 156)).trim(), 8)) throw new Error('archive_header_invalid')
    const prefix = text(header.subarray(345, 500))
    const name = (prefix ? `${prefix}/` : '') + text(header.subarray(0, 100))
    const number = text(header.subarray(124, 136)).trim()
    if (!/^[0-7]+$/.test(number)) throw new Error('archive_size_invalid')
    const size = Number.parseInt(number, 8)
    if (size > 8 * 1024 * 1024 || offset + 512 + size > tar.length) throw new Error('archive_size_invalid')
    const type = header[156]
    if (![0, 48].includes(type) || !name.startsWith('package/') || name.includes('\\')
      || name.split('/').some(part => !part || part === '.' || part === '..')
      || !fileAllowed(name.slice(8)) || files.has(name) || files.size >= 256) throw new Error('archive_member_invalid')
    files.set(name, tar.subarray(offset + 512, offset + 512 + size))
    offset += 512 + Math.ceil(size / 512) * 512
  }
  if (offset + 1024 > tar.length || !tar.subarray(offset).every(byte => byte === 0)) throw new Error('archive_trailer_invalid')
  let manifest
  try { manifest = JSON.parse(files.get('package/package.json')?.toString('utf8')) }
  catch { throw new Error('archive_manifest_invalid') }
  if (manifest?.name !== '@missher/media-missher' || !/^\d+\.\d+\.\d+$/.test(manifest.version)
    || manifest.type !== 'module' || manifest.bin?.['media-missher'] !== 'bin/media-missher.mjs'
    || manifest.license !== 'SEE LICENSE IN LICENSE' || manifest.scripts?.preinstall || manifest.scripts?.install || manifest.scripts?.postinstall
    || Object.keys(manifest.dependencies ?? {}).sort().join(',') !== 'exceljs,saxes'
    || manifest.dependencies.exceljs !== '4.4.0' || manifest.dependencies.saxes !== '5.0.1') throw new Error('archive_manifest_invalid')
  for (const name of ['bin/media-missher.mjs', 'src/skills.mjs', 'src/platform.mjs', 'src/targets.mjs', 'src/capabilities.mjs', 'lib/index.js', 'skill/SKILL.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', ...REQUIRED_PAYLOAD]) {
    if (!files.has(`package/${name}`)) throw new Error('archive_incomplete')
  }
  if (files.get('package/payload/VERSION').toString() !== '17.0.2\n'
    || files.get('package/payload/.media-missher-source-tree').toString() !== 'media-missher-source-v1\n') throw new Error('archive_runtime_identity_invalid')
  return { manifest, files }
}
