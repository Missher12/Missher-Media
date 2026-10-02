import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { afterEach, describe, expect, it } from 'vitest'
import { verifyPackage } from '../scripts/verify-package.mjs'

const execute = promisify(execFile)
const pluginRoot = resolve(import.meta.dirname, '..')
const verifyScript = resolve(pluginRoot, 'scripts', 'verify-package.mjs')
const temporaryRoots: string[] = []

async function fakeArchive(extraFile?: string, changedNotice = false): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'media-package-test-'))
  temporaryRoots.push(root)
  const packageRoot = join(root, 'package')
  await mkdir(join(packageRoot, 'lib'), { recursive: true })
  await mkdir(join(packageRoot, 'payload'), { recursive: true })
  await writeFile(join(packageRoot, 'package.json'), JSON.stringify({
    name: '@missher/dsh-media-missher',
    version: '17.0.2',
    private: true,
    author: 'Missher',
    license: 'SEE LICENSE IN LICENSE',
    os: ['darwin'],
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }))
  await mkdir(join(packageRoot, 'payload/runtime'), { recursive: true })
  for (const name of ['LICENSE', 'THIRD_PARTY_NOTICES.md']) {
    const bytes = await readFile(resolve(import.meta.dirname, '../..', name))
    await writeFile(join(packageRoot, name), bytes)
    await writeFile(join(packageRoot, 'payload/runtime', name), bytes)
  }
  await writeFile(join(packageRoot, 'cordis.patch.yml'), '- insert:\n    - id: media-missher\n      name: "@missher/dsh-media-missher"\n')
  await writeFile(join(packageRoot, 'README.md'), '# private\n')
  await writeFile(join(packageRoot, 'AGENT.md'), '# private onboarding\n')
  await writeFile(join(packageRoot, 'lib', 'index.js'), 'export const name = "media-missher"\n')
  await writeFile(join(packageRoot, 'payload', 'VERSION'), '17.0.2\n')
  await writeFile(
    join(packageRoot, 'payload', '.media-missher-source-tree'),
    'media-missher-source-v1\n',
  )
  if (extraFile !== undefined) await writeFile(join(packageRoot, extraFile), 'forbidden\n')
  if (changedNotice) await writeFile(join(packageRoot, 'LICENSE'), 'changed owner or permission\n')
  const archive = join(root, 'missher-dsh-media-missher-17.0.2.tgz')
  await execute('/usr/bin/tar', ['-czf', archive, '-C', root, 'package'])
  return archive
}

afterEach(async () => {
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('canonical package verification', () => {
  it('accepts the exact private package identity and returns its digest', async () => {
    const result = await verifyPackage(await fakeArchive())
    expect(result.bytes).toBeGreaterThan(0)
    expect(result.sha256).toMatch(/^[a-f0-9]{64}$/u)
    expect(result.entrySha256).toMatch(/^[a-f0-9]{64}$/u)
    expect(result.fileSha256['lib/index.js']).toBe(result.entrySha256)
    expect(result.fileSha256['payload/VERSION']).toMatch(/^[a-f0-9]{64}$/u)
    expect(Object.keys(result.fileSha256).every(name => !name.startsWith('package/'))).toBe(true)
  })

  it('rejects a file outside the package allowlist', async () => {
    await expect(verifyPackage(await fakeArchive('profile.json'))).rejects.toThrow(
      'package_file_unexpected',
    )
  })

  it('rejects a changed or replaced ownership notice', async () => {
    await expect(verifyPackage(await fakeArchive(undefined, true))).rejects.toThrow('package_notice_mismatch')
  })

  it('generates and re-validates its own checksum manifest beside the archive', async () => {
    const archive = await fakeArchive()
    const manifest = join(resolve(archive, '..'), 'SHA256SUMS.txt')

    const generated = JSON.parse((await execute(process.execPath, [
      verifyScript, '--write-checksum', archive,
    ])).stdout)
    expect(generated.checksum).toBe(manifest)
    expect(await readFile(manifest, 'utf8')).toBe(
      `${generated.sha256}  ${basename(archive)}\n`,
    )

    const validated = JSON.parse((await execute(process.execPath, [verifyScript, archive])).stdout)
    expect(validated.checksum).toBe(manifest)

    await writeFile(manifest, `${'0'.repeat(64)}  ${basename(archive)}\n`)
    await expect(execute(process.execPath, [verifyScript, archive])).rejects.toThrow(
      'package_checksum_mismatch',
    )
  })
})
