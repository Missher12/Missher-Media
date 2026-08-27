import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { afterEach, describe, expect, it } from 'vitest'
import { verifyPackage } from '../scripts/verify-package.mjs'

const execute = promisify(execFile)
const temporaryRoots: string[] = []

async function fakeArchive(extraFile?: string): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'media-package-test-'))
  temporaryRoots.push(root)
  const packageRoot = join(root, 'package')
  await mkdir(join(packageRoot, 'lib'), { recursive: true })
  await mkdir(join(packageRoot, 'payload'), { recursive: true })
  await writeFile(join(packageRoot, 'package.json'), JSON.stringify({
    name: 'dsh-media-missher',
    version: '0.1.0',
    private: true,
    os: ['darwin'],
    dsh: { bundle: { patch: './cordis.patch.yml' } },
  }))
  await writeFile(join(packageRoot, 'cordis.patch.yml'), '- insert:\n    - id: media-missher\n      name: dsh-media-missher\n')
  await writeFile(join(packageRoot, 'README.md'), '# private\n')
  await writeFile(join(packageRoot, 'lib', 'index.js'), 'export const name = "media-missher"\n')
  await writeFile(join(packageRoot, 'payload', 'VERSION'), '15.2.1\n')
  await writeFile(
    join(packageRoot, 'payload', '.media-missher-source-tree'),
    'media-missher-source-v1\n',
  )
  if (extraFile !== undefined) await writeFile(join(packageRoot, extraFile), 'forbidden\n')
  const archive = join(root, 'dsh-media-missher-0.1.0.tgz')
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
  })

  it('rejects a file outside the package allowlist', async () => {
    await expect(verifyPackage(await fakeArchive('profile.json'))).rejects.toThrow(
      'package_file_unexpected',
    )
  })
})
