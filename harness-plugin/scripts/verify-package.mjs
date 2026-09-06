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
import { pathToFileURL, fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const execute = promisify(execFile)
const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = resolve(pluginRoot, '..')
const MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
const forbiddenName = /(?:^|\/)(?:profile(?:\.json)?|cookies?|credentials?|screenshots?|runs?|state|\.env(?:\..*)?|__pycache__)(?:\/|$)|\.(?:pyc|png|log)$/iu

async function filePaths(root, current = root) {
  const result = []
  for (const name of await readdir(current)) {
    const path = join(current, name)
    const metadata = await lstat(path)
    if (metadata.isSymbolicLink()) throw new Error('package_symlink_forbidden')
    if (metadata.isDirectory()) result.push(...await filePaths(root, path))
    else if (metadata.isFile()) result.push(relative(root, path).replaceAll('\\', '/'))
    else throw new Error('package_file_type_invalid')
  }
  return result.sort()
}

function allowedFile(path) {
  return [
    'package/package.json',
    'package/cordis.patch.yml',
    'package/README.md',
    'package/AGENT.md',
  ].includes(path)
    || /^package\/lib\/.+\.(?:js|d\.ts)$/u.test(path)
    || path === 'package/payload/VERSION'
    || path === 'package/payload/.media-missher-source-tree'
    || /^package\/payload\/runtime\/.+/u.test(path)
    || /^package\/payload\/media-missher\/scripts\/.+\.py$/u.test(path)
    || /^package\/payload\/tools\/(?:install_media_missher|scan_active_residuals)\.py$/u.test(path)
}

/** Verify a canonical private Bundle archive without installing it. */
export async function verifyPackage(requestedArchive) {
  const archive = resolve(requestedArchive)
  const metadata = await lstat(archive)
  if (metadata.isSymbolicLink() || !metadata.isFile()) throw new Error('package_archive_invalid')
  if (metadata.size <= 0 || metadata.size > MAX_ARCHIVE_BYTES) throw new Error('package_archive_size_invalid')

  const listing = await execute('/usr/bin/tar', ['-tzf', archive], { maxBuffer: 8 * 1024 * 1024 })
  for (const raw of listing.stdout.split(/\r?\n/u).filter(Boolean)) {
    const path = raw.endsWith('/') ? raw.slice(0, -1) : raw
    if (!path.startsWith('package/') && path !== 'package') throw new Error('package_entry_root_invalid')
    if (path.split('/').includes('..') || path.startsWith('/')) throw new Error('package_entry_path_invalid')
  }

  const temporary = await mkdtemp(join(tmpdir(), 'dsh-media-package-'))
  let entrySha256 = ''
  try {
    await execute('/usr/bin/tar', ['-xzf', archive, '-C', temporary])
    const extractedRoot = join(temporary, 'package')
    const files = (await filePaths(temporary)).map(path => path.replaceAll('\\', '/'))
    const required = new Set([
      'package/package.json',
      'package/cordis.patch.yml',
      'package/README.md',
      'package/AGENT.md',
      'package/lib/index.js',
      'package/payload/VERSION',
      'package/payload/.media-missher-source-tree',
    ])
    for (const path of files) {
      if (!allowedFile(path) || forbiddenName.test(path)) throw new Error(`package_file_unexpected:${path}`)
      required.delete(path)
    }
    if (required.size > 0) throw new Error('package_file_missing')

    const manifest = JSON.parse(await readFile(join(extractedRoot, 'package.json'), 'utf8'))
    if (
      manifest.name !== 'dsh-media-missher'
      || manifest.version !== '0.1.1'
      || manifest.private !== true
      || JSON.stringify(manifest.os) !== '["darwin"]'
      || manifest.dsh?.bundle?.patch !== './cordis.patch.yml'
    ) throw new Error('package_identity_invalid')
    const patch = await readFile(join(extractedRoot, 'cordis.patch.yml'), 'utf8')
    if (!patch.includes('id: media-missher') || !patch.includes('name: dsh-media-missher')) {
      throw new Error('package_patch_invalid')
    }
    if (await readFile(join(extractedRoot, 'payload', 'VERSION'), 'utf8') !== '15.2.1\n') {
      throw new Error('package_payload_version_invalid')
    }
    if (
      await readFile(join(extractedRoot, 'payload', '.media-missher-source-tree'), 'utf8')
      !== 'media-missher-source-v1\n'
    ) throw new Error('package_payload_source_identity_invalid')
    entrySha256 = createHash('sha256')
      .update(await readFile(join(extractedRoot, 'lib', 'index.js')))
      .digest('hex')
    for (const path of files.filter(path => path.startsWith('package/lib/') && path.endsWith('.js'))) {
      const source = await readFile(join(temporary, path), 'utf8')
      for (const marker of [pluginRoot, repositoryRoot, pluginRoot.replaceAll('\\', '/'), repositoryRoot.replaceAll('\\', '/')]) {
        if (source.includes(marker)) throw new Error('package_build_path_leak')
      }
    }
  } finally {
    await rm(temporary, { recursive: true, force: true })
  }

  const bytes = await readFile(archive)
  return {
    archive,
    bytes: bytes.byteLength,
    sha256: createHash('sha256').update(bytes).digest('hex'),
    entrySha256,
  }
}

if (process.argv[1] !== undefined && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const requestedArchive = process.argv.slice(2).find(argument => argument !== '--')
  if (requestedArchive === undefined) throw new Error('usage: verify-package.mjs <archive.tgz>')
  const result = await verifyPackage(requestedArchive)
  process.stdout.write(`${JSON.stringify(result)}\n`)
}
