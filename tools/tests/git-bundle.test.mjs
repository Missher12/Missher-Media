// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFile } from 'node:child_process'
import { cp, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { promisify } from 'node:util'
import { verifyPackage } from '../../harness-plugin/scripts/verify-package.mjs'

const execute = promisify(execFile)
const repository = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const version = JSON.parse(await readFile(join(repository, 'package.json'), 'utf8')).version
const runtimeVersion = (await readFile(join(repository, 'VERSION'), 'utf8')).trim()
const release = `dist/v${version}/missher-dsh-media-missher-${version}.tgz`
const checksum = join(dirname(release), 'SHA256SUMS.txt')

async function fixture(t) {
  const temporary = await mkdtemp(join(tmpdir(), 'media-git-entry-test-'))
  t.after(() => rm(temporary, { recursive: true, force: true }))
  const root = join(temporary, 'repository')
  for (const name of [
    'package.json', 'VERSION', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md',
    'DATA_CAPABILITIES.md', 'QUICKSTART.md', 'AGENT_INSTALL.md', '.gitignore',
    'tools/sync-dsh-git.mjs', 'harness-plugin/scripts/verify-package.mjs', 'git-bundle',
  ]) {
    await mkdir(dirname(join(root, name)), { recursive: true })
    await cp(join(repository, name), join(root, name), { recursive: true })
  }
  // Build a synthetic release from the prepared Git payload. Frozen historical
  // archives keep their old package identity and are never rewritten by tests.
  const bundleManifest = join(root, 'git-bundle/package.json')
  const bundle = JSON.parse(await readFile(bundleManifest, 'utf8'))
  bundle.version = version
  await writeFile(bundleManifest, JSON.stringify(bundle, null, 2) + '\n')
  await writeFile(join(root, 'git-bundle/payload/VERSION'), runtimeVersion + '\n')
  const stage = join(temporary, 'release-stage')
  await mkdir(stage)
  await cp(join(root, 'git-bundle'), join(stage, 'package'), { recursive: true })
  await mkdir(dirname(join(root, release)), { recursive: true })
  await execute('/usr/bin/tar', ['-czf', join(root, release), '-C', stage, 'package'], {
    env: { ...process.env, COPYFILE_DISABLE: '1' },
  })
  const sha = createHash('sha256').update(await readFile(join(root, release))).digest('hex')
  await writeFile(join(root, checksum), `${sha}  ${basename(release)}\n`)
  return { root, temporary }
}

async function contents(root, prefix = '') {
  const files = new Map()
  for (const entry of await readdir(join(root, prefix), { withFileTypes: true })) {
    const name = join(prefix, entry.name)
    if (entry.isDirectory()) {
      for (const [path, bytes] of await contents(root, name)) files.set(path, bytes)
    } else files.set(name, await readFile(join(root, name)))
  }
  return files
}

test('a clean Git root packs a complete release with lifecycle scripts disabled', async t => {
  const { root, temporary } = await fixture(t)
  // Git installation must work without allowing dependency build scripts.
  await execute('npm', ['pack', '--pack-destination', temporary, '--ignore-scripts'], {
    cwd: root, timeout: 120000, maxBuffer: 4 * 1024 * 1024,
  })
  const archive = join(temporary, basename(release))
  await verifyPackage(join(root, release))
  const unpacked = join(temporary, 'unpacked')
  await mkdir(unpacked)
  await execute('/usr/bin/tar', ['-xzf', archive, '-C', unpacked])
  const frozen = join(temporary, 'frozen')
  await mkdir(frozen)
  await execute('/usr/bin/tar', ['-xzf', join(root, release), '-C', frozen])
  const releasedFiles = await contents(join(frozen, 'package'))
  assert.deepEqual(await contents(join(unpacked, 'package/git-bundle')), releasedFiles)
  const manifest = JSON.parse(await readFile(join(unpacked, 'package/package.json'), 'utf8'))
  assert.equal(manifest.dsh.bundle.patch, './git-bundle/cordis.patch.yml')
  assert.equal(manifest.name, '@missher/dsh-media-missher')
  for (const hook of ['prepare', 'prepack', 'prepublish', 'preinstall', 'install', 'postinstall']) {
    assert.equal(manifest.scripts?.[hook], undefined, `Git installs must not require ${hook}`)
  }
  assert.deepEqual(await readFile(join(unpacked, 'package', manifest.main)), releasedFiles.get('lib/index.js'))
  assert.deepEqual(await readFile(join(unpacked, 'package', manifest.exports['.'].import)), releasedFiles.get('lib/index.js'))
  await execute(process.execPath, ['tools/sync-dsh-git.mjs'], { cwd: root })
  assert.deepEqual(await contents(join(root, 'git-bundle')), releasedFiles)
})

for (const [name, edit, expected] of [
  ['missing bundle declaration', async root => {
    const path = join(root, 'package.json')
    const manifest = JSON.parse(await readFile(path, 'utf8'))
    delete manifest.dsh
    await writeFile(path, JSON.stringify(manifest))
  }, /git_bundle_entry_mismatch/u],
  ['release checksum mismatch', root => writeFile(join(root, checksum), '0'.repeat(64) + `  ${basename(release)}\n`), /package_checksum_mismatch/u],
  ['missing release checksum', root => rm(join(root, checksum)), /git_bundle_checksum_missing/u],
  ['unreleased runtime version', root => writeFile(join(root, 'VERSION'), '0.0.0\n'), /git_bundle_version_mismatch/u],
]) {
  test(`${name} refuses release sync before changing the existing bundle`, async t => {
    const { root } = await fixture(t)
    await writeFile(join(root, 'git-bundle/preserve.txt'), 'preserve\n')
    await edit(root)
    await assert.rejects(execute(process.execPath, ['tools/sync-dsh-git.mjs'], { cwd: root }), error => expected.test(error.stderr))
    assert.equal(await readFile(join(root, 'git-bundle/preserve.txt'), 'utf8'), 'preserve\n')
  })
}
