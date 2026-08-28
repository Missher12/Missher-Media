#!/usr/bin/env node

import { execFile } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  lstat,
  mkdtemp,
  readdir,
  readFile,
  rm,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { promisify } from 'node:util'
import { verifyPackage } from './verify-package.mjs'

const execute = promisify(execFile)
const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const pluginRoot = resolve(scriptDirectory, '..')
const repositoryRoot = resolve(pluginRoot, '..')
const setupDirectoryName = 'Media-Missher-Harness-Setup'
const archiveName = 'Media-Missher-Harness-Setup-v15.2.1.zip'
const defaultArchive = join(pluginRoot, 'dist', archiveName)
const maximumArchiveBytes = 128 * 1024 * 1024

const expectedFiles = new Map([
  [
    `${setupDirectoryName}/Install Media@Missher Harness Plugin.command`,
    join(repositoryRoot, 'Install Media@Missher Harness Plugin.command'),
  ],
  [
    `${setupDirectoryName}/harness-plugin/scripts/install-current-profile.mjs`,
    join(pluginRoot, 'scripts', 'install-current-profile.mjs'),
  ],
  [
    `${setupDirectoryName}/harness-plugin/scripts/verify-package.mjs`,
    join(pluginRoot, 'scripts', 'verify-package.mjs'),
  ],
  [
    `${setupDirectoryName}/harness-plugin/dist/dsh-media-missher-0.1.0.tgz`,
    join(pluginRoot, 'dist', 'dsh-media-missher-0.1.0.tgz'),
  ],
  [
    `${setupDirectoryName}/harness-plugin/dist/SHA256SUMS.txt`,
    join(pluginRoot, 'dist', 'SHA256SUMS.txt'),
  ],
])

async function filePaths(root, current = root) {
  const result = []
  for (const name of await readdir(current)) {
    const path = join(current, name)
    const metadata = await lstat(path)
    if (metadata.isSymbolicLink()) throw new Error('setup_symlink_forbidden')
    if (metadata.isDirectory()) result.push(...await filePaths(root, path))
    else if (metadata.isFile()) result.push(relative(root, path).replaceAll('\\', '/'))
    else throw new Error('setup_file_type_invalid')
  }
  return result.sort()
}

export async function verifySetup(requestedArchive = defaultArchive) {
  const archive = resolve(requestedArchive)
  const metadata = await lstat(archive)
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error('setup_archive_invalid')
  if (metadata.size <= 0 || metadata.size > maximumArchiveBytes) {
    throw new Error('setup_archive_size_invalid')
  }

  const listing = await execute('/usr/bin/unzip', ['-Z1', archive], {
    maxBuffer: 8 * 1024 * 1024,
  })
  const listedFiles = listing.stdout
    .split(/\r?\n/u)
    .filter(Boolean)
    .filter(path => !path.endsWith('/'))
    .sort()
  for (const path of listedFiles) {
    if (
      path.startsWith('/')
      || path.split('/').includes('..')
      || !path.startsWith(`${setupDirectoryName}/`)
    ) throw new Error('setup_entry_path_invalid')
  }
  if (JSON.stringify(listedFiles) !== JSON.stringify([...expectedFiles.keys()].sort())) {
    throw new Error('setup_entry_allowlist_invalid')
  }

  const temporary = await mkdtemp(join(tmpdir(), 'media-missher-setup-'))
  try {
    await execute('/usr/bin/unzip', ['-q', archive, '-d', temporary])
    const extractedFiles = await filePaths(temporary)
    if (JSON.stringify(extractedFiles) !== JSON.stringify([...expectedFiles.keys()].sort())) {
      throw new Error('setup_extracted_allowlist_invalid')
    }
    for (const [path, source] of expectedFiles) {
      const [extractedBytes, sourceBytes] = await Promise.all([
        readFile(join(temporary, path)),
        readFile(source),
      ])
      if (!extractedBytes.equals(sourceBytes)) throw new Error(`setup_source_bytes_mismatch:${path}`)
    }

    const bundlePath = join(
      temporary,
      setupDirectoryName,
      'harness-plugin',
      'dist',
      'dsh-media-missher-0.1.0.tgz',
    )
    const bundle = await verifyPackage(bundlePath)
    const bundleChecksum = await readFile(
      join(temporary, setupDirectoryName, 'harness-plugin', 'dist', 'SHA256SUMS.txt'),
      'utf8',
    )
    if (bundleChecksum !== `${bundle.sha256}  dsh-media-missher-0.1.0.tgz\n`) {
      throw new Error('setup_inner_checksum_invalid')
    }

    const bytes = await readFile(archive)
    return {
      ok: true,
      archive,
      bytes: bytes.byteLength,
      sha256: createHash('sha256').update(bytes).digest('hex'),
      bundleSha256: bundle.sha256,
      bundleVersion: '0.1.0',
      productVersion: '15.2.1',
    }
  } finally {
    await rm(temporary, { recursive: true, force: true })
  }
}

if (process.argv[1] !== undefined && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const requestedArchive = process.argv.slice(2).find(argument => argument !== '--')
  const result = await verifySetup(requestedArchive)
  process.stdout.write(`${JSON.stringify(result)}\n`)
}
