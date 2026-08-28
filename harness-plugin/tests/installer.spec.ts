import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
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

  it('uses the Harness app runtime instead of requiring system Node or pnpm', async () => {
    const setup = await readFile(
      resolve(repositoryRoot, 'Install Media@Missher Harness Plugin.command'),
      'utf8',
    )
    expect(setup).toContain('ELECTRON_RUN_AS_NODE=1')
    expect(setup).toContain('DSH_DESKTOP_PNPM_ENTRY')
    expect(setup).toContain('dsh-media-missher-0.1.0.tgz')
    expect(setup).toContain('tell application "DeepSeek Harness" to quit')
    expect(setup).toContain('/usr/bin/open -a "DeepSeek Harness"')
    expect(setup).not.toContain('command -v node')
    expect(setup).not.toContain('command -v pnpm')
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
})
