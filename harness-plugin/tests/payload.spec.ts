import { execFile } from 'node:child_process'
import { lstat, mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, relative, resolve } from 'node:path'
import { promisify } from 'node:util'
import { afterEach, describe, expect, it } from 'vitest'

const execute = promisify(execFile)
const pluginRoot = resolve(import.meta.dirname, '..')
const stageScript = resolve(pluginRoot, 'scripts', 'stage-payload.mjs')
const temporaryRoots: string[] = []

async function filesBelow(root: string, current = root): Promise<string[]> {
  const result: string[] = []
  for (const name of await readdir(current)) {
    const path = join(current, name)
    const metadata = await lstat(path)
    expect(metadata.isSymbolicLink()).toBe(false)
    if (metadata.isDirectory()) result.push(...await filesBelow(root, path))
    else result.push(relative(root, path).replaceAll('\\', '/'))
  }
  return result.sort()
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('embedded Media runtime payload', () => {
  it('stages only the exact private runtime source allowlist', async () => {
    const temporaryRoot = await mkdtemp(join(tmpdir(), 'media-payload-test-'))
    temporaryRoots.push(temporaryRoot)
    const payload = join(temporaryRoot, 'payload')

    await execute(process.execPath, [stageScript, '--output', payload])

    const files = await filesBelow(payload)
    expect(await readFile(join(payload, 'VERSION'), 'utf8')).toBe('17.0.2\n')
    expect(await readFile(join(payload, '.media-missher-source-tree'), 'utf8')).toBe(
      'media-missher-source-v1\n',
    )
    expect(files).toContain('runtime/requirements.lock')
    for (const name of ['LICENSE', 'THIRD_PARTY_NOTICES.md']) {
      expect(await readFile(join(payload, 'runtime', name))).toEqual(await readFile(resolve(pluginRoot, '..', name)))
    }
    expect(files).toContain('runtime/scripts/scrape_all.py')
    expect(files).toContain('runtime/media_missher_runtime/platforms/bilibili.py')
    expect(files).toContain('media-missher/scripts/run_collection.py')
    expect(files).toContain('media-missher/scripts/media_missher_adapter.py')
    expect(files).toContain('tools/install_media_missher.py')
    expect(files).toContain('tools/scan_active_residuals.py')
    expect(files.some(path => /(?:profile|cookie|credential|\.env|\.png|\.log|\.pyc|__pycache__)/iu.test(path))).toBe(false)
    expect(files.every(path => (
      path === 'VERSION'
      || path === '.media-missher-source-tree'
      || path.startsWith('runtime/')
      || path.startsWith('media-missher/scripts/')
      || path === 'tools/install_media_missher.py'
      || path === 'tools/scan_active_residuals.py'
    ))).toBe(true)
  })
})
