#!/usr/bin/env node
// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { execFile } from 'node:child_process'
import { cp, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { verifyChecksumFile, verifyPackage } from '../harness-plugin/scripts/verify-package.mjs'

// Maintainer-only release step. Git installs carry these prepared files and
// never run a lifecycle script or build the development tree.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const manifest = JSON.parse(await readFile(join(root, 'package.json'), 'utf8'))
const version = (await readFile(join(root, 'VERSION'), 'utf8')).trim()
if (!/^\d+\.\d+\.\d+$/u.test(version) || manifest.version !== version) {
  throw new Error('git_bundle_version_mismatch')
}
const archive = join(root, 'dist', `v${version}`, `dsh-media-missher-${version}.tgz`)
const verified = await verifyPackage(archive)
if (await verifyChecksumFile(archive, verified.sha256) === null) {
  throw new Error('git_bundle_checksum_missing')
}

const temporary = await mkdtemp(join(tmpdir(), 'media-git-bundle-'))
try {
  await promisify(execFile)('/usr/bin/tar', ['-xzf', archive, '-C', temporary])
  const source = join(temporary, 'package')
  const released = JSON.parse(await readFile(join(source, 'package.json'), 'utf8'))
  // Refuse metadata drift before touching generated files. A version bump must
  // ship the matching release, dependency set, and checksum together.
  for (const key of [
    'name', 'version', 'private', 'type', 'license', 'author', 'os', 'engines',
    'dependencies',
  ]) {
    if (JSON.stringify(manifest[key]) !== JSON.stringify(released[key])) {
      throw new Error(`git_bundle_manifest_mismatch:${key}`)
    }
  }
  if (manifest.main !== `git-bundle/${released.main}`
    || manifest.types !== `git-bundle/${released.types}`
    || manifest.exports?.['.']?.import !== `./git-bundle/${released.main}`
    || manifest.exports?.['.']?.types !== `./git-bundle/${released.types}`
    || manifest.dsh?.bundle?.patch !== './git-bundle/cordis.patch.yml') {
    throw new Error('git_bundle_entry_mismatch')
  }
  const target = join(root, 'git-bundle')
  await rm(target, { recursive: true, force: true })
  await cp(source, target, { recursive: true })
  process.stdout.write(`DSH Git release synced: ${manifest.name}@${version} (${verified.sha256})\n`)
} finally {
  await rm(temporary, { recursive: true, force: true })
}
