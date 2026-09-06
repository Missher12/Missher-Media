#!/usr/bin/env node

import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  chmod,
  copyFile,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  utimes,
  writeFile,
} from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { verifyPackage } from './verify-package.mjs'

const execute = promisify(execFile)
const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(scriptDirectory, '..')
const repositoryRoot = resolve(pluginRoot, '..')
const distributionDirectory = join(pluginRoot, 'dist')
const archiveName = 'Media-Missher-Harness-Setup-bundle-v0.1.1.zip'
const outputArchive = join(distributionDirectory, archiveName)
const checksumPath = join(distributionDirectory, 'SETUP-SHA256.txt')
const setupDirectoryName = 'Media-Missher-Harness-Setup'
const fixedTimestamp = new Date('2026-08-28T00:00:00.000Z')

const setupFiles = [
  {
    source: join(repositoryRoot, 'Install Media@Missher Harness Plugin.command'),
    destination: 'Install Media@Missher Harness Plugin.command',
    mode: 0o700,
  },
  {
    source: join(pluginRoot, 'scripts', 'install-current-profile.mjs'),
    destination: 'harness-plugin/scripts/install-current-profile.mjs',
    mode: 0o600,
  },
  {
    source: join(pluginRoot, 'scripts', 'verify-package.mjs'),
    destination: 'harness-plugin/scripts/verify-package.mjs',
    mode: 0o600,
  },
  {
    source: join(pluginRoot, 'AGENT.md'),
    destination: 'harness-plugin/AGENT.md',
    mode: 0o600,
  },
  {
    source: join(distributionDirectory, 'dsh-media-missher-0.1.1.tgz'),
    destination: 'harness-plugin/dist/dsh-media-missher-0.1.1.tgz',
    mode: 0o600,
  },
  {
    source: join(distributionDirectory, 'SHA256SUMS.txt'),
    destination: 'harness-plugin/dist/SHA256SUMS.txt',
    mode: 0o600,
  },
]

async function requireRegularFile(path) {
  const metadata = await lstat(path)
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error(`setup_source_invalid:${path}`)
}

async function normalizeTimestamps(path) {
  const metadata = await lstat(path)
  if (metadata.isDirectory()) {
    for (const name of (await readdir(path)).sort()) {
      await normalizeTimestamps(join(path, name))
    }
  }
  await utimes(path, fixedTimestamp, fixedTimestamp)
}

async function makeSetupArchive() {
  await mkdir(distributionDirectory, { recursive: true, mode: 0o700 })
  for (const file of setupFiles) await requireRegularFile(file.source)

  const bundle = await verifyPackage(
    join(distributionDirectory, 'dsh-media-missher-0.1.1.tgz'),
  )
  const bundleChecksum = await readFile(
    join(distributionDirectory, 'SHA256SUMS.txt'),
    'utf8',
  )
  if (bundleChecksum !== `${bundle.sha256}  dsh-media-missher-0.1.1.tgz\n`) {
    throw new Error('setup_bundle_checksum_invalid')
  }

  const workRoot = join(pluginRoot, '.work')
  await mkdir(workRoot, { recursive: true, mode: 0o700 })
  const temporary = await mkdtemp(join(workRoot, 'setup-release-'))
  const setupRoot = join(temporary, setupDirectoryName)
  await mkdir(setupRoot, { recursive: true, mode: 0o700 })

  try {
    for (const file of setupFiles) {
      const destination = join(setupRoot, file.destination)
      await mkdir(dirname(destination), { recursive: true, mode: 0o700 })
      await copyFile(file.source, destination)
      await chmod(destination, file.mode)
    }
    await normalizeTimestamps(setupRoot)

    await rm(outputArchive, { force: true })
    await execute('/usr/bin/zip', [
      '-X',
      '-q',
      '-r',
      outputArchive,
      setupDirectoryName,
    ], {
      cwd: temporary,
      env: { ...process.env, TZ: 'UTC' },
    })

    const bytes = await readFile(outputArchive)
    const sha256 = createHash('sha256').update(bytes).digest('hex')
    await writeFile(checksumPath, `${sha256}  ${archiveName}\n`, { mode: 0o600 })
    await chmod(outputArchive, 0o600)
    await chmod(checksumPath, 0o600)
    return {
      archive: outputArchive,
      bytes: bytes.byteLength,
      sha256,
      bundleSha256: bundle.sha256,
    }
  } finally {
    await rm(temporary, { recursive: true, force: true })
  }
}

const result = await makeSetupArchive()
process.stdout.write(`${JSON.stringify(result)}\n`)
