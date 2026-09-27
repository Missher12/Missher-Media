import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'
import { execFile } from 'node:child_process'
import { mkdir, mkdtemp, readFile, realpath, rm, symlink, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { describe, expect, it } from 'vitest'

const execute = promisify(execFile)
const pluginRoot = resolve(import.meta.dirname, '..')
const repositoryRoot = resolve(pluginRoot, '..')

describe('one-click and native lifecycle entrypoints', () => {
  it('exposes non-mutating help for install and native smoke', async () => {
    const install = await execute(process.execPath, [
      resolve(pluginRoot, 'scripts', 'install-current-profile.mjs'),
      '--help',
    ])
    const smoke = await execute(process.execPath, [
      resolve(pluginRoot, 'scripts', 'native-smoke.mjs'),
      '--help',
    ])
    expect(install.stdout).toContain('--archive')
    expect(install.stdout).toContain('--profile')
    expect(smoke.stdout).toContain('--cli')
    expect(smoke.stdout).toContain('--archive')
  })

  it('offers an authenticated private GitHub bootstrap without embedding a token', async () => {
    const bootstrap = await readFile(
      resolve(repositoryRoot, 'Install-Media-Missher-from-GitHub.command'),
      'utf8',
    )
    expect(bootstrap).toContain('Missher12/media-missher')
    expect(bootstrap).toContain('v15.2.1')
    expect(bootstrap).toContain('gh release download')
    expect(bootstrap).toContain('SETUP-SHA256.txt')
    expect(bootstrap).toContain('Media-Missher-Harness-Setup-v15.2.1.zip')
    expect(bootstrap).toContain('auth status --hostname github.com')
    expect(bootstrap).not.toMatch(/github_pat_|ghp_|GITHUB_TOKEN|GH_TOKEN/u)
  })

  it('forces same-spec refreshes and verifies the installed entry bytes', async () => {
    const installer = await readFile(
      resolve(pluginRoot, 'scripts', 'install-current-profile.mjs'),
      'utf8',
    )
    expect(installer).toContain("'add', '--force', stagedArchive")
    expect(installer).toContain('verified.sha256.slice(0, 16)')
    expect(installer).toContain('harness_plugin_bytes_mismatch')
  })
  it('detects both packaged runtime layouts and fails before mutation without pnpm', async () => {
    const root = await mkdtemp(join(tmpdir(), 'media-layout-test-'))
    const { resolveHarnessLayout } = await import(pathToFileURL(resolve(pluginRoot, 'scripts/install-current-profile.mjs')).href)
    const put = async (name: string) => {
      const path = join(root, name)
      await mkdir(dirname(path), { recursive: true })
      await writeFile(path, 'fixture')
      return path
    }
    try {
      const runtime = await put('Contents/Resources/runtime/node/bin/node')
      const cli = await put('Contents/Resources/runtime/app/lib/bin.js')
      await expect(resolveHarnessLayout(root, [])).rejects.toThrow('harness_external_pnpm_required')
      const target = await put('pnpm.mjs')
      const shim = join(root, 'pnpm')
      await symlink(target, shim)
      expect(await resolveHarnessLayout(root, [shim])).toMatchObject({ runtime, cli, pnpm: await realpath(target) })
      await rm(runtime)
      const legacyRuntime = await put('Contents/MacOS/DeepSeek Harness')
      await put('Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js')
      await put('Contents/Resources/app.asar.unpacked/node_modules/pnpm/bin/pnpm.cjs')
      expect(await resolveHarnessLayout(root, [])).toMatchObject({ runtime: legacyRuntime })
    } finally {
      await rm(root, { recursive: true, force: true })
    }
  })

  it('detects the Desktop ASAR layout with its bundled pnpm and Node shim', async () => {
    const root = await mkdtemp(join(tmpdir(), 'media-asar-layout-'))
    const { resolveHarnessLayout } = await import(pathToFileURL(resolve(pluginRoot, 'scripts/install-current-profile.mjs')).href)
    try {
      for (const name of ['Contents/MacOS/DeepSeek Harness', 'Contents/Resources/app.asar', 'Contents/Resources/runtime/pnpm/bin/pnpm.cjs']) {
        const path = join(root, name)
        await mkdir(dirname(path), { recursive: true })
        await writeFile(path, 'fixture')
      }
      expect(await resolveHarnessLayout(root, [])).toEqual({
        runtime: join(root, 'Contents/MacOS/DeepSeek Harness'),
        cli: join(root, 'Contents/Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js'),
        pnpm: join(root, 'Contents/Resources/runtime/pnpm/bin/pnpm.cjs'),
        pnpmBin: join(root, 'Contents/Resources/runtime/bin'),
      })
    } finally { await rm(root, { recursive: true, force: true }) }
  })

})
