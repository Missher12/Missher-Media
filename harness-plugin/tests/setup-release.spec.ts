import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { promisify } from 'node:util'
import { beforeAll, describe, expect, it } from 'vitest'

const execute = promisify(execFile)
const pluginRoot = resolve(import.meta.dirname, '..')
const repositoryRoot = resolve(pluginRoot, '..')
const setupArchive = resolve(
  pluginRoot,
  'dist',
  'Media-Missher-Harness-Setup-bundle-v0.1.1.zip',
)

describe('private GitHub setup release', () => {
  beforeAll(async () => {
    await execute('pnpm', ['run', 'pack:bundle'], { cwd: pluginRoot })
    const archive = await readFile(resolve(pluginRoot, 'dist', 'dsh-media-missher-0.1.1.tgz'))
    await writeFile(resolve(pluginRoot, 'dist', 'SHA256SUMS.txt'),
      `${createHash('sha256').update(archive).digest('hex')}  dsh-media-missher-0.1.1.tgz\n`)
  }, 30000)

  it('builds a self-contained setup archive with an exact allowlist', async () => {
    const built = await execute(process.execPath, [
      resolve(pluginRoot, 'scripts', 'build-setup.mjs'),
    ])
    const buildResult = JSON.parse(built.stdout)
    expect(buildResult.archive).toBe(setupArchive)

    const verified = await execute(process.execPath, [
      resolve(pluginRoot, 'scripts', 'verify-setup.mjs'),
      setupArchive,
    ])
    const verifyResult = JSON.parse(verified.stdout)
    expect(verifyResult.ok).toBe(true)
    expect(verifyResult.bundleVersion).toBe('0.1.1')
    expect(verifyResult.productVersion).toBe('15.2.1')

    const setupChecksum = await readFile(
      resolve(pluginRoot, 'dist', 'SETUP-SHA256.txt'),
      'utf8',
    )
    expect(setupChecksum).toBe(
      `${verifyResult.sha256}  Media-Missher-Harness-Setup-bundle-v0.1.1.zip\n`,
    )
  })

  it('documents the one-command private GitHub handoff for Harness Agents', async () => {
    const readme = await readFile(resolve(repositoryRoot, 'README.md'), 'utf8')
    expect(readme).toContain('gh release download v15.2.1')
    expect(readme).toContain('Install-Media-Missher-from-GitHub.command')
    expect(readme).toContain('私有 GitHub Release')
  })
})
